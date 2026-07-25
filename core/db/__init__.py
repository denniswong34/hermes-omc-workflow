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
  updated_at TEXT NOT NULL
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
