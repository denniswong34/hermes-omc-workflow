"""
Plane.so ticket tracker.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import quote, urljoin

from core.tickets.base import TicketRef, TicketTracker
from core.tickets.formatting import plain_to_html
from core.tickets.status import SdlcStatus
from core.tickets.status_map import (
    build_plane_status_map,
    merge_status_maps,
    nonempty_status_map,
    resolve_plane_state_id,
)

logger = logging.getLogger(__name__)


class PlaneTracker(TicketTracker):
    """Plane.so REST API client (API key / session cookie via config)."""

    def __init__(
        self,
        base_url: str,
        workspace: str,
        project_id: str,
        api_key: str = "",
        status_map: Optional[dict[str, str]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.workspace = workspace
        self.project_id = project_id
        self.api_key = api_key
        self.status_map = nonempty_status_map(status_map)
        self._states_cache: list[dict[str, Any]] | None = None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Referer": f"{self.base_url}/",
        }
        if self.api_key:
            # Support both API key header and cookie session styles
            if self.api_key.lower().startswith("session=") or "sessionid" in self.api_key.lower():
                headers["Cookie"] = self.api_key
            else:
                headers["X-API-Key"] = self.api_key
                headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _request(self, method: str, path: str, data: Any = None) -> Any:
        import aiohttp

        url = urljoin(self.base_url + "/", path.lstrip("/"))
        async with aiohttp.ClientSession() as sess:
            async with sess.request(method, url, headers=self._headers(), json=data) as r:
                if r.status in (200, 201):
                    return await r.json()
                if r.status == 204:
                    return True
                body = await r.text()
                logger.error(f"Plane API {method} {path}: {r.status} {body[:200]}")
                return None

    def _state_paths(self) -> list[str]:
        ws = quote(self.workspace, safe="")
        pid = quote(self.project_id, safe="")
        return [
            f"/api/v1/workspaces/{ws}/projects/{pid}/states/",
            f"/api/workspaces/{ws}/projects/{pid}/states/",
        ]

    def _issue_paths(self, issue_id: str = "") -> list[str]:
        ws = quote(self.workspace, safe="")
        pid = quote(self.project_id, safe="")
        base = f"/api/v1/workspaces/{ws}/projects/{pid}/issues/"
        legacy = f"/api/workspaces/{ws}/projects/{pid}/issues/"
        if issue_id:
            iid = quote(issue_id, safe="")
            return [f"{base}{iid}/", f"{legacy}{iid}/"]
        return [base, legacy]

    async def _request_first(self, method: str, paths: list[str], data: Any = None) -> Any:
        last = None
        for path in paths:
            last = await self._request(method, path, data)
            if last is not None:
                return last
        return last

    async def list_states(self, *, force: bool = False) -> list[dict[str, Any]]:
        if self._states_cache is not None and not force:
            return self._states_cache
        data = await self._request_first("GET", self._state_paths())
        if isinstance(data, dict):
            states = data.get("results") or data.get("states") or []
        elif isinstance(data, list):
            states = data
        else:
            states = []
        self._states_cache = [s for s in states if isinstance(s, dict) and s.get("id")]
        return self._states_cache

    async def ensure_status_map(self) -> dict[str, str]:
        """Auto-map SDLC statuses onto Plane state UUIDs when map is incomplete."""
        if len(self.status_map) >= len(SdlcStatus) and all(
            self.status_map.get(s.value) for s in SdlcStatus
        ):
            return self.status_map
        states = await self.list_states()
        if not states:
            return self.status_map
        self.status_map = build_plane_status_map(states, preferred_map=self.status_map)
        return self.status_map

    def _state_id(self, status: SdlcStatus) -> Optional[str]:
        return self.status_map.get(status.value) or None

    def get_url(self, external_id: str) -> str:
        return f"{self.base_url}/projects/{self.project_id}/issues/{external_id}"

    async def create_issue(
        self,
        name: str,
        description: str = "",
        status: SdlcStatus = SdlcStatus.BACKLOG,
    ) -> Optional[TicketRef]:
        await self.ensure_status_map()
        state_id = self._state_id(status)
        if not state_id and self._states_cache:
            state_id = resolve_plane_state_id(status, self._states_cache)
        summary = (name or "").strip()[:255] or "New work item"
        desc_text = (description or "").strip()
        if not desc_text or desc_text == summary:
            desc_text = (
                "## Overview\n"
                f"Track and deliver: {summary}\n\n"
                "## Requirements\n"
                "- Clarify acceptance criteria with the requester.\n"
                "- Attach evidence (logs/screenshots) as work progresses."
            )
        payload: dict[str, Any] = {
            "name": summary,
            "description_html": plain_to_html(desc_text),
            "priority": "medium",
        }
        if state_id:
            payload["state"] = state_id

        result = await self._request_first("POST", self._issue_paths(), payload)
        if not result or "id" not in result:
            logger.error(f"Plane: failed to create issue {summary[:50]!r}")
            return None

        issue_id = result["id"]
        seq = result.get("sequence_id", "")
        url = self.get_url(issue_id)
        logger.info(f"Plane: created {summary[:50]} → {url}")
        return TicketRef(
            external_id=issue_id,
            url=url,
            key=str(seq) if seq != "" else "",
            name=summary,
        )

    async def add_comment(self, external_id: str, body: str) -> bool:
        text = (body or "").strip()
        if not external_id or not text:
            return False
        html = plain_to_html(text)
        payload = {"comment_html": html, "access": "INTERNAL"}
        paths = self._comment_paths(external_id)
        result = await self._request_first("POST", paths, payload)
        if result is None:
            # Older Plane installs may omit access / use issues path only
            result = await self._request_first(
                "POST",
                paths,
                {"comment_html": html},
            )
        ok = result is not None
        if ok:
            logger.info(f"Plane: commented on {external_id[:8]}")
        return ok

    def _comment_paths(self, issue_id: str) -> list[str]:
        ws = quote(self.workspace, safe="")
        pid = quote(self.project_id, safe="")
        iid = quote(issue_id, safe="")
        return [
            f"/api/v1/workspaces/{ws}/projects/{pid}/work-items/{iid}/comments/",
            f"/api/v1/workspaces/{ws}/projects/{pid}/issues/{iid}/comments/",
            f"/api/workspaces/{ws}/projects/{pid}/issues/{iid}/comments/",
        ]

    async def update_status(self, external_id: str, status: SdlcStatus) -> bool:
        await self.ensure_status_map()
        state_id = self._state_id(status)
        if not state_id and self._states_cache:
            state_id = resolve_plane_state_id(status, self._states_cache)
            if state_id:
                self.status_map[status.value] = state_id
        if not state_id:
            logger.warning(f"Plane: no status_map entry for {status.value}")
            return False
        result = await self._request_first(
            "PATCH",
            self._issue_paths(external_id),
            {"state": state_id},
        )
        ok = result is not None
        if ok:
            logger.info(f"Plane: updated {external_id[:8]} → {status.display}")
        return ok

    def apply_status_map(self, status_map: dict[str, str] | None) -> None:
        self.status_map = merge_status_maps(self.status_map, nonempty_status_map(status_map))
