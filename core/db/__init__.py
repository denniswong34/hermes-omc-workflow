"""SQLite database for OMC Agentic OS multi-workflow control plane."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DB_PATH = Path(
    os.environ.get("OMC_DB_PATH", str(Path.home() / ".hermes" / "omc" / "omc.db"))
).expanduser()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def _parse(raw: Optional[str], default: Any = None) -> Any:
    if not raw:
        return default if default is not None else {}
    try:
        return json.loads(raw)
    except Exception:
        return default if default is not None else {}


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  working_directory TEXT NOT NULL DEFAULT '',
  github_repo TEXT NOT NULL DEFAULT '',
  github_username TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS templates (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  is_system INTEGER NOT NULL DEFAULT 0,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflows (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  is_active INTEGER NOT NULL DEFAULT 0,
  project_id TEXT,
  reasoning_engine TEXT NOT NULL DEFAULT 'hermes',
  coding_default TEXT NOT NULL DEFAULT 'hermes',
  coding_workspace TEXT DEFAULT '',
  memory_provider TEXT NOT NULL DEFAULT 'hermes',
  memory_config_json TEXT NOT NULL DEFAULT '{}',
  tracking_provider TEXT NOT NULL DEFAULT 'none',
  tracking_config_json TEXT NOT NULL DEFAULT '{}',
  routes_json TEXT NOT NULL DEFAULT '{}',
  status_authority_json TEXT NOT NULL DEFAULT '{}',
  playbooks_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  role_id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  mention TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'persona',
  persona_file TEXT NOT NULL,
  reasoning_engine TEXT,
  coding_backend TEXT,
  hermes_profile TEXT NOT NULL DEFAULT '',
  llm_model TEXT NOT NULL DEFAULT '',
  platform_identity_json TEXT NOT NULL DEFAULT '{}',
  tools_json TEXT NOT NULL DEFAULT '[]',
  mcp_allowlist_json TEXT NOT NULL DEFAULT '[]',
  UNIQUE(workflow_id, role_id),
  FOREIGN KEY(workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chats (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  credentials_ref TEXT NOT NULL DEFAULT '',
  config_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tracking_connections (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  config_json TEXT NOT NULL DEFAULT '{}',
  is_active INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS channels (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  name TEXT NOT NULL,
  external_id TEXT NOT NULL DEFAULT '',
  agents_json TEXT NOT NULL DEFAULT '[]',
  ticket_create_roles_json TEXT NOT NULL DEFAULT '[]',
  UNIQUE(workflow_id, name),
  FOREIGN KEY(workflow_id) REFERENCES workflows(id) ON DELETE CASCADE,
  FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cron_jobs (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  name TEXT NOT NULL,
  cron_expr TEXT NOT NULL,
  agent_role TEXT NOT NULL,
  channel_name TEXT NOT NULL,
  prompt TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  FOREIGN KEY(workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mcp_catalog (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  transport TEXT NOT NULL DEFAULT 'stdio',
  command_json TEXT NOT NULL DEFAULT '[]',
  env_json TEXT NOT NULL DEFAULT '{}',
  docs_url TEXT DEFAULT '',
  is_builtin INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mcp_workflow (
  id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  catalog_id TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  config_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(workflow_id, catalog_id),
  FOREIGN KEY(workflow_id) REFERENCES workflows(id) ON DELETE CASCADE,
  FOREIGN KEY(catalog_id) REFERENCES mcp_catalog(id) ON DELETE CASCADE
);
"""


class Database:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or DEFAULT_DB_PATH).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate_projects(conn)
            self._migrate_agents(conn)
            self._migrate_tracking_connections(conn)

    def _migrate_tracking_connections(self, conn: sqlite3.Connection) -> None:
        """Ensure tracking_connections table + seed from legacy workflow columns."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tracking_connections (
              id TEXT PRIMARY KEY,
              workflow_id TEXT NOT NULL,
              provider TEXT NOT NULL,
              label TEXT NOT NULL DEFAULT '',
              config_json TEXT NOT NULL DEFAULT '{}',
              is_active INTEGER NOT NULL DEFAULT 0,
              FOREIGN KEY(workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
            )
            """
        )
        workflows = conn.execute(
            "SELECT id, tracking_provider, tracking_config_json FROM workflows"
        ).fetchall()
        for row in workflows:
            provider = (row["tracking_provider"] or "none").strip().lower()
            if provider in ("", "none"):
                continue
            existing = conn.execute(
                "SELECT COUNT(1) AS n FROM tracking_connections WHERE workflow_id = ?",
                (row["id"],),
            ).fetchone()
            if existing and int(existing["n"] or 0) > 0:
                continue
            cfg = _parse(row["tracking_config_json"], {})
            label = str((cfg or {}).get("label") or "").strip()
            if not label:
                label = f"{provider[:1].upper()}{provider[1:]} #1"
            conn.execute(
                "INSERT INTO tracking_connections"
                "(id, workflow_id, provider, label, config_json, is_active) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (new_id("trk_"), row["id"], provider, label, _json(cfg or {})),
            )

    def _migrate_agents(self, conn: sqlite3.Connection) -> None:
        """Add per-agent Hermes profile / gateway identity columns on legacy DBs."""
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(agents)").fetchall()
        }
        if not cols:
            return
        if "hermes_profile" not in cols:
            conn.execute(
                "ALTER TABLE agents ADD COLUMN hermes_profile TEXT NOT NULL DEFAULT ''"
            )
        if "llm_model" not in cols:
            conn.execute(
                "ALTER TABLE agents ADD COLUMN llm_model TEXT NOT NULL DEFAULT ''"
            )
        if "platform_identity_json" not in cols:
            conn.execute(
                "ALTER TABLE agents ADD COLUMN platform_identity_json TEXT NOT NULL DEFAULT '{}'"
            )
        # Backfill empty hermes_profile from workflow_id + role_id
        rows = conn.execute(
            "SELECT id, workflow_id, role_id, hermes_profile FROM agents"
        ).fetchall()
        for row in rows:
            profile = (row["hermes_profile"] or "").strip()
            if profile:
                continue
            default = f"omc-{row['role_id']}"
            conn.execute(
                "UPDATE agents SET hermes_profile = ? WHERE id = ?",
                (default, row["id"]),
            )

    def _migrate_projects(self, conn: sqlite3.Connection) -> None:
        """Add project_id to legacy DBs and backfill orphan workflows."""
        cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(workflows)").fetchall()
        }
        if "project_id" not in cols:
            conn.execute("ALTER TABLE workflows ADD COLUMN project_id TEXT")

        orphans = conn.execute(
            "SELECT id, coding_workspace FROM workflows "
            "WHERE project_id IS NULL OR project_id = ''"
        ).fetchall()
        if not orphans:
            # Still ensure active_project_id points at a real project when possible
            active = conn.execute(
                "SELECT value FROM settings WHERE key = 'active_project_id'"
            ).fetchone()
            if active and active["value"]:
                exists = conn.execute(
                    "SELECT id FROM projects WHERE id = ?", (active["value"],)
                ).fetchone()
                if exists:
                    return
            first = conn.execute(
                "SELECT id FROM projects ORDER BY created_at LIMIT 1"
            ).fetchone()
            if first:
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES('active_project_id', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (first["id"],),
                )
            return

        workspace = ""
        for row in orphans:
            ws = (row["coding_workspace"] or "").strip()
            if ws:
                workspace = ws
                break

        now = _now()
        project_id = new_id("proj_")
        conn.execute(
            "INSERT INTO projects(id, name, working_directory, github_repo, github_username, created_at, updated_at) "
            "VALUES (?, ?, ?, '', '', ?, ?)",
            (project_id, "Default Project", workspace, now, now),
        )
        conn.execute(
            "UPDATE workflows SET project_id = ? "
            "WHERE project_id IS NULL OR project_id = ''",
            (project_id,),
        )
        conn.execute(
            "INSERT INTO settings(key, value) VALUES('active_project_id', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (project_id,),
        )

    def get_setting(self, key: str, default: str = "") -> str:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )


def new_id(prefix: str = "") -> str:
    uid = uuid.uuid4().hex[:12]
    return f"{prefix}{uid}" if prefix else uid


def get_db(path: Path | str | None = None) -> Database:
    db = Database(path)
    db.init_schema()
    return db
