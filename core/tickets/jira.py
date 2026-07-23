"""
Jira Cloud ticket tracker.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Optional

from core.tickets.base import TicketRef, TicketTracker
from core.tickets.status import SdlcStatus

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
        self.status_map = {k: v for k, v in (status_map or {}).items() if v}
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
        return self.status_map.get(status.value)

    async def create_issue(
        self,
        name: str,
        description: str = "",
        status: SdlcStatus = SdlcStatus.BACKLOG,
    ) -> Optional[TicketRef]:
        payload = {
            "fields": {
                "project": {"key": self.project_key},
                "summary": name,
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": description or name}],
                        }
                    ],
                },
                "issuetype": {"name": "Task"},
            }
        }
        result = await self._request("POST", "/rest/api/3/issue", payload)
        if not result or "id" not in result:
            logger.error(f"Jira: failed to create issue {name[:50]!r}")
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
            name=name,
        )

    async def update_status(self, external_id: str, status: SdlcStatus) -> bool:
        target = self._target_status_name(status)
        if not target:
            logger.warning(f"Jira: no status_map entry for {status.value}")
            return False

        transitions = await self._request(
            "GET",
            f"/rest/api/3/issue/{external_id}/transitions",
        )
        if not transitions or "transitions" not in transitions:
            return False

        transition_id = None
        target_lower = target.lower()
        for t in transitions["transitions"]:
            name = (t.get("name") or "").lower()
            to_name = ((t.get("to") or {}).get("name") or "").lower()
            if name == target_lower or to_name == target_lower:
                transition_id = t.get("id")
                break

        if not transition_id:
            logger.warning(
                f"Jira: no transition to '{target}' for {external_id}; "
                f"available={[t.get('name') for t in transitions['transitions']]}"
            )
            return False

        result = await self._request(
            "POST",
            f"/rest/api/3/issue/{external_id}/transitions",
            {"transition": {"id": transition_id}},
        )
        ok = result is not None
        if ok:
            logger.info(f"Jira: updated {external_id} → {status.display}")
        return ok
