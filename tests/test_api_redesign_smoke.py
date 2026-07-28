"""HTTP smoke against FastAPI TestClient."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp(prefix="omc-api-")
os.environ["OMC_DB_PATH"] = str(Path(tmp) / "api.db")

from fastapi.testclient import TestClient

from apps.api.main import app


def main() -> None:
    c = TestClient(app)
    r = c.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"]

    r = c.get("/api/templates")
    assert any(t["id"] == "tpl-sdlc" for t in r.json()["templates"])

    r = c.post(
        "/api/projects",
        json={
            "name": "Smoke Project",
            "working_directory": "/tmp/smoke",
            "github_repo": "acme/smoke",
        },
    )
    assert r.status_code == 200, r.text

    r = c.post("/api/workflows/clone", json={"name": "Play Co", "template_id": "tpl-sdlc"})
    assert r.status_code == 200
    wid = r.json()["id"]

    r = c.patch(f"/api/workflows/{wid}", json={"reasoning_engine": "claude"})
    assert r.json()["reasoning_engine"] == "claude"

    pm = next(a for a in r.json()["agents"] if a["role_id"] == "pm")
    r = c.patch(
        f"/api/workflows/{wid}/agents/{pm['id']}",
        json={"reasoning_engine": "claude"},
    )
    assert r.json()["reasoning_engine"] == "claude"

    r = c.post(
        f"/api/workflows/{wid}/mcp",
        json={"catalog_id": "mcp-filesystem", "enabled": True},
    )
    assert r.status_code == 200

    r = c.get(f"/api/workflows/{wid}/cron")
    assert len(r.json()["jobs"]) >= 1

    r = c.get("/api/engines")
    assert {e["id"] for e in r.json()["engines"]} == {
        "hermes",
        "claude",
        "cursor",
        "opencode",
        "codex",
    }

    # Chat connection test probe (missing token → ok=false, not 500)
    chats = c.get(f"/api/workflows/{wid}").json()["chats"]
    assert chats, "seeded workflow should have chats"
    chat = chats[0]
    r = c.post(
        f"/api/workflows/{wid}/chats/{chat['id']}/test",
        json={"platform": chat["platform"], "secrets": {}, "config": {}},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert "message" in r.json()

    # Tracking connection upsert + clear
    r = c.get("/api/tracking-providers")
    assert r.status_code == 200
    assert "jira" in r.json()["providers"]
    r = c.put(
        f"/api/workflows/{wid}/tracking",
        json={
            "provider": "jira",
            "label": "Jira #1",
            "config": {
                "base_url": "https://example.atlassian.net",
                "email": "bot@example.com",
                "project_key": "OMC",
            },
            "secrets": {"api_token": "test-token"},
        },
    )
    assert r.status_code == 200
    assert r.json()["tracking_provider"] == "jira"
    assert r.json()["tracking"]["configured"] is True
    assert r.json()["tracking"]["label"] == "Jira #1"
    assert len(r.json()["trackings"]) == 1
    assert r.json()["trackings"][0]["is_active"] is True
    r = c.delete(f"/api/workflows/{wid}/tracking")
    assert r.status_code == 200
    assert r.json()["tracking_provider"] == "none"
    assert r.json()["tracking"]["configured"] is False
    assert r.json()["trackings"] == []

    # Multi-tracking: two connections, only one active
    r = c.post(
        f"/api/workflows/{wid}/trackings",
        json={
            "provider": "jira",
            "label": "Jira HOAO",
            "config": {
                "base_url": "https://example.atlassian.net",
                "email": "bot@example.com",
                "project_key": "HOAO",
            },
            "secrets": {"api_token": "jira-token"},
            "activate": True,
        },
    )
    assert r.status_code == 200, r.text
    jira_id = r.json()["trackings"][0]["id"]
    assert r.json()["tracking"]["is_active"] is True
    r = c.post(
        f"/api/workflows/{wid}/trackings",
        json={
            "provider": "plane",
            "label": "Plane Acme",
            "config": {
                "base_url": "https://api.plane.so",
                "workspace_slug": "acme",
                "project_id": "proj-1",
            },
            "secrets": {"api_key": "plane-key"},
            "activate": False,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["trackings"]) == 2
    assert body["tracking_provider"] == "jira"
    assert body["tracking"]["label"] == "Jira HOAO"
    plane = next(t for t in body["trackings"] if t["provider"] == "plane")
    assert plane["is_active"] is False
    r = c.post(f"/api/workflows/{wid}/trackings/{plane['id']}/activate")
    assert r.status_code == 200
    assert r.json()["tracking_provider"] == "plane"
    assert r.json()["tracking"]["label"] == "Plane Acme"
    assert sum(1 for t in r.json()["trackings"] if t["is_active"]) == 1
    r = c.delete(f"/api/workflows/{wid}/trackings/{jira_id}")
    assert r.status_code == 200
    assert len(r.json()["trackings"]) == 1
    assert r.json()["trackings"][0]["is_active"] is True

    # Probe (missing/invalid → ok=false, not 404)
    plane_id = r.json()["trackings"][0]["id"]
    r = c.post(
        f"/api/workflows/{wid}/trackings/{plane_id}/test",
        json={"provider": "plane", "config": {}, "secrets": {}},
    )
    assert r.status_code == 200
    assert "ok" in r.json()
    assert "message" in r.json()

    print("API smoke OK")


if __name__ == "__main__":
    main()
