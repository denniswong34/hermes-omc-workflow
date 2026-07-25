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
    r = c.delete(f"/api/workflows/{wid}/tracking")
    assert r.status_code == 200
    assert r.json()["tracking_provider"] == "none"
    assert r.json()["tracking"]["configured"] is False

    # Re-add tracking then probe (missing/invalid → ok=false, not 404)
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
    r = c.post(
        f"/api/workflows/{wid}/tracking/test",
        json={"provider": "jira", "config": {}, "secrets": {}},
    )
    assert r.status_code == 200
    assert "ok" in r.json()
    assert "message" in r.json()

    print("API smoke OK")


if __name__ == "__main__":
    main()
