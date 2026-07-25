"""
Jira Cloud ticket tracker.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Optional

from core.tickets.base import TicketRef, TicketTracker
from core.tickets.formatting import plain_to_adf
from core.tickets.status import SdlcStatus
from core.tickets.status_map import (
    default_jira_status_map,
    merge_status_maps,
    nonempty_status_map,
    pick_jira_transition,
)

logger = logging.getLogger(__name__)


class JiraTracker(TicketTracker):
    """Jira Cloud REST v3 client (email + API token)."""

    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        project_key: str,
        status_map: Optional[dict[str, str]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.api_token = api_token
        self.project_key = project_key
        # Prefer configured map; fill gaps from Jira defaults (names may still
        # be remapped at transition time against the live workflow).
        self.status_map = merge_status_maps(default_jira_status_map(), status_map)
        token = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        self._auth_header = f"Basic {token}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, data: Any = None) -> Any:
        import aiohttp

        url = f"{self.base_url}{path}"
        async with aiohttp.ClientSession() as sess:
            async with sess.request(method, url, headers=self._headers(), json=data) as r:
                if r.status in (200, 201):
                    if r.content_type and "json" in r.content_type:
                        return await r.json()
                    return True
                if r.status == 204:
                    return True
                body = await r.text()
                logger.error(f"Jira API {method} {path}: {r.status} {body[:200]}")
                return None

    def get_url(self, external_id: str) -> str:
        # external_id may be issue key (PROJ-1) or numeric id
        return f"{self.base_url}/browse/{external_id}"

    def _target_status_name(self, status: SdlcStatus) -> Optional[str]:
        return self.status_map.get(status.value) or None

    async def create_issue(
        self,
        name: str,
        description: str = "",
        status: SdlcStatus = SdlcStatus.BACKLOG,
    ) -> Optional[TicketRef]:
        summary = (name or "").strip()[:255] or "New work item"
        desc_text = (description or "").strip()
        # Never fall back to repeating the title as the only description body
        if not desc_text or desc_text == summary:
            desc_text = (
                "## Overview\n"
                f"Track and deliver: {summary}\n\n"
                "## Requirements\n"
                "- Clarify acceptance criteria with the requester.\n"
                "- Attach evidence (logs/screenshots) as work progresses."
            )
        payload = {
            "fields": {
                "project": {"key": self.project_key},
                "summary": summary,
                "description": plain_to_adf(desc_text),
                "issuetype": {"name": "Task"},
            }
        }
        result = await self._request("POST", "/rest/api/3/issue", payload)
        if not result or "id" not in result:
            logger.error(f"Jira: failed to create issue {summary[:50]!r}")
            return None

        key = result.get("key", "")
        issue_id = result["id"]
        url = self.get_url(key or issue_id)
        logger.info(f"Jira: created {key or issue_id} → {url}")

        # Best-effort transition to requested status
        if status != SdlcStatus.BACKLOG and key:
            await self.update_status(key, status)

        return TicketRef(
            external_id=key or issue_id,
            url=url,
            key=key,
            name=summary,
        )

    async def add_comment(self, external_id: str, body: str) -> bool:
        text = (body or "").strip()
        if not external_id or not text:
            return False
        result = await self._request(
            "POST",
            f"/rest/api/3/issue/{external_id}/comment",
            {"body": plain_to_adf(text)},
        )
        ok = result is not None
        if ok:
            logger.info(f"Jira: commented on {external_id}")
        return ok

    async def update_status(self, external_id: str, status: SdlcStatus) -> bool:
        preferred = self._target_status_name(status)

        transitions = await self._request(
            "GET",
            f"/rest/api/3/issue/{external_id}/transitions",
        )
        if not transitions or "transitions" not in transitions:
            return False

        available = transitions["transitions"]
        chosen = pick_jira_transition(
            available,
            status,
            preferred_target=preferred,
        )
        if not chosen:
            logger.warning(
                f"Jira: no transition for {status.value} on {external_id}; "
                f"preferred={preferred!r} "
                f"available={[t.get('name') for t in available]}"
            )
            return False

        transition_id = chosen.get("id")
        dest = ((chosen.get("to") or {}).get("name")) or chosen.get("name")
        result = await self._request(
            "POST",
            f"/rest/api/3/issue/{external_id}/transitions",
            {"transition": {"id": transition_id}},
        )
        ok = result is not None
        if ok:
            logger.info(
                f"Jira: updated {external_id} → {status.display} "
                f"(board status '{dest}')"
            )
            # Remember the live mapping so later updates stay consistent
            if dest:
                self.status_map[status.value] = dest
        return ok

    def apply_status_map(self, status_map: dict[str, str] | None) -> None:
        self.status_map = merge_status_maps(self.status_map, nonempty_status_map(status_map))
