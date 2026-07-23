"""
Plane.so ticket tracker.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urljoin

from core.tickets.base import TicketRef, TicketTracker
from core.tickets.status import SdlcStatus

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
        self.status_map = {k: v for k, v in (status_map or {}).items() if v}

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
        state_id = self._state_id(status)
        payload: dict[str, Any] = {
            "name": name,
            "description_html": f"<p>{description}</p>" if description else "<p></p>",
            "priority": "medium",
        }
        if state_id:
            payload["state"] = state_id

        result = await self._request(
            "POST",
            f"/api/workspaces/{self.workspace}/projects/{self.project_id}/issues/",
            payload,
        )
        if not result or "id" not in result:
            logger.error(f"Plane: failed to create issue {name[:50]!r}")
            return None

        issue_id = result["id"]
        seq = result.get("sequence_id", "")
        url = self.get_url(issue_id)
        logger.info(f"Plane: created {name[:50]} → {url}")
        return TicketRef(
            external_id=issue_id,
            url=url,
            key=str(seq) if seq != "" else "",
            name=name,
        )

    async def update_status(self, external_id: str, status: SdlcStatus) -> bool:
        state_id = self._state_id(status)
        if not state_id:
            logger.warning(f"Plane: no status_map entry for {status.value}")
            return False
        result = await self._request(
            "PATCH",
            f"/api/workspaces/{self.workspace}/projects/{self.project_id}/issues/{external_id}/",
            {"state": state_id},
        )
        ok = result is not None
        if ok:
            logger.info(f"Plane: updated {external_id[:8]} → {status.display}")
        return ok
