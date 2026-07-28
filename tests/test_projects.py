"""Projects + scoping + PAT write-only storage."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp(prefix="omc-projects-")
os.environ["OMC_DB_PATH"] = str(Path(tmp) / "projects.db")
os.environ["OMC_PROJECT_SECRETS_DIR"] = str(Path(tmp) / "project-secrets")

from fastapi.testclient import TestClient

from apps.api.main import app
from core.db import get_db
from core.secrets import resolve_project_secrets


def main() -> None:
    c = TestClient(app)

    # Fresh DB: no projects → workflow list rejected
    r = c.get("/api/workflows")
    assert r.status_code == 400, r.text
    assert "Create a project first" in r.text

    r = c.post("/api/workflows/clone", json={"name": "A", "template_id": "tpl-sdlc"})
    assert r.status_code == 400

    # Create project with PAT
    r = c.post(
        "/api/projects",
        json={
            "name": "Alpha",
            "working_directory": "/tmp/alpha",
            "github_repo": "acme/alpha",
            "github_username": "alice",
            "github_pat": "ghp_secret_alpha",
        },
    )
    assert r.status_code == 200, r.text
    alpha = r.json()
    assert alpha["id"]
    assert alpha["has_pat"] is True
    assert "github_pat" not in alpha
    assert "ghp_secret" not in r.text

    secrets = resolve_project_secrets(alpha["id"])
    assert secrets.get("GITHUB_PAT") == "ghp_secret_alpha"
    assert secrets.get("GITHUB_USERNAME") == "alice"

    # Active project set
    r = c.get("/api/projects/active")
    assert r.status_code == 200
    assert r.json()["project"]["id"] == alpha["id"]

    # Clone workflow into active project; workspace defaulted
    r = c.post("/api/workflows/clone", json={"name": "Alpha Co", "template_id": "tpl-sdlc"})
    assert r.status_code == 200, r.text
    wf_a = r.json()
    assert wf_a["project_id"] == alpha["id"]
    assert wf_a["coding_workspace"] == "/tmp/alpha"

    r = c.get("/api/workflows")
    assert r.status_code == 200
    assert len(r.json()["workflows"]) == 1
    assert r.json()["workflows"][0]["id"] == wf_a["id"]

    # Second project
    r = c.post(
        "/api/projects",
        json={
            "name": "Beta",
            "working_directory": "/tmp/beta",
            "github_repo": "acme/beta",
            "make_active": True,
        },
    )
    assert r.status_code == 200
    beta = r.json()
    assert beta["has_pat"] is False

    r = c.get("/api/workflows")
    assert r.status_code == 200
    assert r.json()["workflows"] == []
    assert r.json()["project_id"] == beta["id"]

    r = c.post("/api/workflows/clone", json={"name": "Beta Co", "template_id": "tpl-sdlc"})
    assert r.status_code == 200
    wf_b = r.json()
    assert wf_b["project_id"] == beta["id"]

    # Header overrides active project
    r = c.get("/api/workflows", headers={"X-OMC-Project-Id": alpha["id"]})
    assert r.status_code == 200
    assert len(r.json()["workflows"]) == 1
    assert r.json()["workflows"][0]["id"] == wf_a["id"]

    # Switch active back to alpha
    r = c.put("/api/projects/active", json={"project_id": alpha["id"]})
    assert r.status_code == 200
    r = c.get("/api/workflows")
    assert len(r.json()["workflows"]) == 1
    assert r.json()["workflows"][0]["id"] == wf_a["id"]

    # Migration: orphan workflow gets Default Project
    db = get_db()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO workflows(id, name, description, is_active, project_id, reasoning_engine, "
            "coding_default, coding_workspace, memory_provider, memory_config_json, tracking_provider, "
            "tracking_config_json, routes_json, status_authority_json, playbooks_json, created_at, updated_at) "
            "VALUES ('wf_orphan', 'Orphan', '', 0, NULL, 'hermes', 'hermes', '/tmp/orphan', 'hermes', '{}', "
            "'none', '{}', '{}', '{}', '{}', '2020-01-01T00:00:00Z', '2020-01-01T00:00:00Z')"
        )
    # Re-init schema triggers migration
    db2 = get_db(Path(tmp) / "projects.db")
    with db2.connect() as conn:
        row = conn.execute(
            "SELECT project_id, coding_workspace FROM workflows WHERE id = 'wf_orphan'"
        ).fetchone()
        assert row["project_id"]
        proj = conn.execute(
            "SELECT name, working_directory FROM projects WHERE id = ?",
            (row["project_id"],),
        ).fetchone()
        # May reuse an existing project if migration only runs for NULL project_ids
        # Our orphan had NULL so it should be assigned
        assert proj is not None

    # PAT never echoed on GET/PATCH
    r = c.get(f"/api/projects/{alpha['id']}")
    assert r.json()["has_pat"] is True
    assert "ghp_secret" not in r.text

    r = c.patch(
        f"/api/projects/{alpha['id']}",
        json={"github_pat": "ghp_rotated"},
    )
    assert r.status_code == 200
    assert r.json()["has_pat"] is True
    assert "ghp_rotated" not in r.text
    assert resolve_project_secrets(alpha["id"]).get("GITHUB_PAT") == "ghp_rotated"

    print("test_projects: OK")


if __name__ == "__main__":
    main()
