"""Probe ticket tracker credentials (Jira / Plane)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from core.chat_test import _http_json


def test_jira(
    base_url: str,
    email: str,
    api_token: str,
    project_key: str,
) -> dict[str, Any]:
    base_url = (base_url or "").rstrip("/")
    email = (email or "").strip()
    api_token = (api_token or "").strip()
    project_key = (project_key or "").strip()
    if not base_url or not email or not api_token or not project_key:
        return {
            "ok": False,
            "platform": "jira",
            "message": "Base URL, email, API token, and project key are required",
        }
    if not base_url.startswith("http"):
        base_url = "https://" + base_url

    from base64 import b64encode

    auth = b64encode(f"{email}:{api_token}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Accept": "application/json",
    }

    # Auth + identity
    status, me = _http_json(f"{base_url}/rest/api/3/myself", headers=headers)
    if status != 200 or not isinstance(me, dict) or not me.get("accountId"):
        err = (me or {}).get("errorMessages") or (me or {}).get("message") or (me or {}).get("error")
        if isinstance(err, list):
            err = "; ".join(str(x) for x in err)
        return {
            "ok": False,
            "platform": "jira",
            "message": str(err or f"Auth failed (HTTP {status})"),
        }

    # Project access
    key_q = quote(project_key, safe="")
    p_status, proj = _http_json(f"{base_url}/rest/api/3/project/{key_q}", headers=headers)
    if p_status != 200 or not isinstance(proj, dict) or not proj.get("id"):
        err = (proj or {}).get("errorMessages") or (proj or {}).get("error") or f"HTTP {p_status}"
        if isinstance(err, list):
            err = "; ".join(str(x) for x in err)
        return {
            "ok": False,
            "platform": "jira",
            "message": f"Auth OK as {me.get('displayName') or email}, but project '{project_key}' failed: {err}",
            "details": {"account": me.get("displayName"), "email": me.get("emailAddress")},
        }

    name = me.get("displayName") or me.get("emailAddress") or email
    pname = proj.get("name") or project_key
    return {
        "ok": True,
        "platform": "jira",
        "message": f"Connected as {name} · project {pname} ({project_key})",
        "details": {
            "account_id": me.get("accountId"),
            "project_id": proj.get("id"),
            "project_key": project_key,
        },
    }


def test_plane(
    base_url: str,
    workspace: str,
    project_id: str,
    api_key: str,
) -> dict[str, Any]:
    base_url = (base_url or "").rstrip("/")
    workspace = (workspace or "").strip()
    project_id = (project_id or "").strip()
    api_key = (api_key or "").strip()
    if not base_url or not workspace or not project_id or not api_key:
        return {
            "ok": False,
            "platform": "plane",
            "message": "Base URL, workspace, project ID, and API key are required",
        }
    if not base_url.startswith("http"):
        base_url = "https://" + base_url

    headers: dict[str, str] = {
        "Accept": "application/json",
        "Referer": f"{base_url}/",
    }
    if api_key.lower().startswith("session=") or "sessionid" in api_key.lower():
        headers["Cookie"] = api_key
    else:
        headers["X-API-Key"] = api_key
        headers["Authorization"] = f"Bearer {api_key}"

    # Workspace detail validates key + workspace slug
    ws = quote(workspace, safe="")
    status, data = _http_json(f"{base_url}/api/v1/workspaces/{ws}/", headers=headers)
    if status != 200 or not isinstance(data, dict):
        err = (data or {}).get("detail") or (data or {}).get("error") or (data or {}).get("message")
        return {
            "ok": False,
            "platform": "plane",
            "message": str(err or f"Workspace lookup failed (HTTP {status})"),
        }
    if data.get("slug") or data.get("id") or data.get("name"):
        pass
    else:
        # Some Plane installs wrap payload
        pass

    # Project access
    pid = quote(project_id, safe="")
    p_status, proj = _http_json(
        f"{base_url}/api/v1/workspaces/{ws}/projects/{pid}/",
        headers=headers,
    )
    if p_status != 200 or not isinstance(proj, dict):
        err = (proj or {}).get("detail") or (proj or {}).get("error") or f"HTTP {p_status}"
        ws_name = data.get("name") or workspace
        return {
            "ok": False,
            "platform": "plane",
            "message": f"Workspace OK ({ws_name}), but project failed: {err}",
        }

    ws_name = data.get("name") or workspace
    pname = proj.get("name") or project_id
    return {
        "ok": True,
        "platform": "plane",
        "message": f"Connected to workspace {ws_name} · project {pname}",
        "details": {
            "workspace": workspace,
            "project_id": project_id,
            "project_name": pname,
        },
    }


def test_tracking_connection(provider: str, credentials: dict[str, str]) -> dict[str, Any]:
    p = (provider or "").strip().lower()
    creds = {k: (v or "").strip() for k, v in (credentials or {}).items()}
    if p == "jira":
        return test_jira(
            creds.get("base_url", ""),
            creds.get("email", ""),
            creds.get("api_token", ""),
            creds.get("project_key", ""),
        )
    if p == "plane":
        return test_plane(
            creds.get("base_url", ""),
            creds.get("workspace", ""),
            creds.get("project_id", ""),
            creds.get("api_key", ""),
        )
    return {"ok": False, "platform": p or "unknown", "message": f"Unsupported provider: {p}"}
