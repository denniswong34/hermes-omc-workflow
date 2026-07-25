"""Discover and build SDLC → provider status_map from live Jira / Plane boards."""

from __future__ import annotations

from base64 import b64encode
from typing import Any
from urllib.parse import quote

from core.chat_test import _http_json
from core.tickets.status_map import (
    build_plane_status_map,
    build_status_map_from_names,
    default_jira_status_map,
    nonempty_status_map,
)


def discover_jira_status_map(
    base_url: str,
    email: str,
    api_token: str,
    project_key: str,
    *,
    preferred_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Fetch project statuses and build a best-fit status_map.

    Returns {ok, status_map, available, message}.
    """
    base_url = (base_url or "").rstrip("/")
    email = (email or "").strip()
    api_token = (api_token or "").strip()
    project_key = (project_key or "").strip()
    if not base_url.startswith("http"):
        base_url = "https://" + base_url
    if not all([base_url, email, api_token, project_key]):
        return {"ok": False, "status_map": {}, "available": [], "message": "Missing Jira credentials"}

    auth = b64encode(f"{email}:{api_token}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
    key_q = quote(project_key, safe="")
    status_code, data = _http_json(
        f"{base_url}/rest/api/3/project/{key_q}/statuses",
        headers=headers,
    )
    if status_code != 200 or not isinstance(data, list):
        err = (data or {}).get("errorMessages") if isinstance(data, dict) else None
        if isinstance(err, list):
            err = "; ".join(str(x) for x in err)
        return {
            "ok": False,
            "status_map": {},
            "available": [],
            "message": str(err or f"Failed to list project statuses (HTTP {status_code})"),
        }

    names: list[str] = []
    categories: dict[str, str] = {}
    for issuetype in data:
        for s in issuetype.get("statuses") or []:
            name = (s.get("name") or "").strip()
            if not name:
                continue
            if name not in names:
                names.append(name)
            cat = ((s.get("statusCategory") or {}).get("key")) or ""
            if cat and name not in categories:
                categories[name] = cat

    preferred = nonempty_status_map(preferred_map) or default_jira_status_map()
    status_map = build_status_map_from_names(
        names,
        preferred_map=preferred,
        categories=categories,
    )
    return {
        "ok": bool(status_map),
        "status_map": status_map,
        "available": names,
        "message": f"Mapped {len(status_map)} SDLC statuses onto {len(names)} Jira statuses",
    }


def _plane_headers(base_url: str, api_key: str) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Referer": f"{base_url.rstrip('/')}/",
    }
    key = (api_key or "").strip()
    if key.lower().startswith("session=") or "sessionid" in key.lower():
        headers["Cookie"] = key
    elif key:
        headers["X-API-Key"] = key
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _plane_states_paths(workspace: str, project_id: str) -> list[str]:
    ws = quote(workspace, safe="")
    pid = quote(project_id, safe="")
    return [
        f"/api/v1/workspaces/{ws}/projects/{pid}/states/",
        f"/api/workspaces/{ws}/projects/{pid}/states/",
    ]


def discover_plane_status_map(
    base_url: str,
    workspace: str,
    project_id: str,
    api_key: str,
    *,
    preferred_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Fetch Plane project states and build sdlc → state UUID map.

    Returns {ok, status_map, available, message}.
    """
    base_url = (base_url or "").rstrip("/")
    workspace = (workspace or "").strip()
    project_id = (project_id or "").strip()
    api_key = (api_key or "").strip()
    if not base_url.startswith("http"):
        base_url = "https://" + base_url
    if not all([base_url, workspace, project_id, api_key]):
        return {"ok": False, "status_map": {}, "available": [], "message": "Missing Plane credentials"}

    headers = _plane_headers(base_url, api_key)
    last_err = "Failed to list Plane states"
    data: Any = None
    for path in _plane_states_paths(workspace, project_id):
        status_code, payload = _http_json(f"{base_url}{path}", headers=headers)
        if status_code == 200:
            data = payload
            break
        err = None
        if isinstance(payload, dict):
            err = payload.get("detail") or payload.get("error") or payload.get("message")
        last_err = str(err or f"HTTP {status_code} for {path}")

    if data is None:
        return {"ok": False, "status_map": {}, "available": [], "message": last_err}

    # Plane may return a list or {results: [...]}
    if isinstance(data, dict):
        states = data.get("results") or data.get("states") or []
    elif isinstance(data, list):
        states = data
    else:
        states = []

    if not isinstance(states, list) or not states:
        return {
            "ok": False,
            "status_map": {},
            "available": [],
            "message": "Plane returned no project states",
        }

    status_map = build_plane_status_map(states, preferred_map=preferred_map)
    available = [
        {
            "id": str(s.get("id") or ""),
            "name": str(s.get("name") or ""),
            "group": str(s.get("group") or ""),
        }
        for s in states
        if s.get("id")
    ]
    return {
        "ok": bool(status_map),
        "status_map": status_map,
        "available": available,
        "message": f"Mapped {len(status_map)} SDLC statuses onto {len(available)} Plane states",
    }


def discover_tracking_status_map(provider: str, credentials: dict[str, str]) -> dict[str, Any]:
    p = (provider or "").strip().lower()
    creds = {k: (v or "").strip() for k, v in (credentials or {}).items()}

    if p == "jira":
        return discover_jira_status_map(
            creds.get("base_url", ""),
            creds.get("email", ""),
            creds.get("api_token", ""),
            creds.get("project_key", ""),
        )
    if p == "plane":
        return discover_plane_status_map(
            creds.get("base_url", ""),
            creds.get("workspace", ""),
            creds.get("project_id", ""),
            creds.get("api_key", ""),
        )
    return {"ok": False, "status_map": {}, "available": [], "message": f"Unsupported provider: {p}"}
