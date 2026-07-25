"""Seed SDLC Workflow system template and default workflow instance from current OMC layout."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.db import Database, REPO_ROOT, _json, _now, new_id

SDLC_AGENTS = [
    {"role_id": "pm", "display_name": "Product Manager", "mention": "PM", "kind": "persona", "persona_file": "pm.md"},
    {"role_id": "sa", "display_name": "Systems Analyst", "mention": "SA", "kind": "persona", "persona_file": "sa.md"},
    {"role_id": "coder", "display_name": "Coder", "mention": "Coder", "kind": "coding", "persona_file": "coder.md", "coding_backend": None},
    {"role_id": "qa", "display_name": "QA", "mention": "QA", "kind": "persona", "persona_file": "qa.md"},
    {"role_id": "devops", "display_name": "DevOps", "mention": "DevOps", "kind": "persona", "persona_file": "devops.md"},
    {"role_id": "marketing", "display_name": "Marketing", "mention": "Marketing", "kind": "persona", "persona_file": "marketing.md"},
    {"role_id": "standup", "display_name": "Standup", "mention": "Standup", "kind": "persona", "persona_file": "standup.md"},
    {"role_id": "hermes", "display_name": "Hermes", "mention": "Hermes", "kind": "coding", "persona_file": "coder.md", "coding_backend": "hermes"},
    {"role_id": "claude", "display_name": "Claude", "mention": "Claude", "kind": "coding", "persona_file": "coder.md", "coding_backend": "claude"},
    {"role_id": "cursor", "display_name": "Cursor", "mention": "Cursor", "kind": "coding", "persona_file": "coder.md", "coding_backend": "cursor"},
    {"role_id": "opencode", "display_name": "OpenCode", "mention": "OpenCode", "kind": "coding", "persona_file": "coder.md", "coding_backend": "opencode"},
    {"role_id": "codex", "display_name": "Codex", "mention": "Codex", "kind": "coding", "persona_file": "coder.md", "coding_backend": "codex"},
]

SDLC_CHANNELS = [
    {"name": "product", "agents": ["pm", "sa"], "ticket_create_roles": ["pm", "sa"]},
    {"name": "engineering", "agents": ["pm", "sa", "coder", "qa", "devops", "hermes", "claude", "cursor", "opencode", "codex"], "ticket_create_roles": ["pm", "sa"]},
    {"name": "marketing", "agents": ["pm", "marketing"], "ticket_create_roles": ["pm"]},
    {"name": "support", "agents": ["pm", "sa", "coder", "qa", "hermes", "claude", "cursor", "opencode", "codex"], "ticket_create_roles": ["pm", "sa"]},
    {"name": "standup", "agents": ["standup"], "ticket_create_roles": []},
]

SDLC_ROUTES = {
    "pm": ["sa", "devops", "marketing", "coder"],
    "sa": ["pm", "coder", "qa"],
    "coder": ["sa", "qa", "devops"],
    "qa": ["sa", "coder", "devops"],
    "devops": ["pm", "coder", "qa"],
    "marketing": ["pm"],
    "standup": [],
    "hermes": ["sa", "qa", "devops"],
    "claude": ["sa", "qa", "devops"],
    "cursor": ["sa", "qa", "devops"],
    "opencode": ["sa", "qa", "devops"],
    "codex": ["sa", "qa", "devops"],
}

SDLC_STATUS = {
    "pm": ["backlog", "todo", "done", "cancelled"],
    "sa": ["todo", "in progress"],
    "coder": ["in progress", "in review"],
    "qa": ["qa review", "qa failed", "qa verified", "ready to deploy"],
    "devops": ["ready to deploy", "deployed"],
    "marketing": [],
    "standup": [],
    "hermes": ["in progress", "in review"],
    "claude": ["in progress", "in review"],
    "cursor": ["in progress", "in review"],
    "opencode": ["in progress", "in review"],
    "codex": ["in progress", "in review"],
}

BUILTIN_MCP = [
    {
        "id": "mcp-filesystem",
        "name": "Filesystem",
        "description": "Read/write files in a sandbox directory",
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "."],
        "docs_url": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "id": "mcp-fetch",
        "name": "Fetch",
        "description": "HTTP fetch tool server",
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-fetch"],
        "docs_url": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "id": "mcp-memory",
        "name": "Memory",
        "description": "Simple knowledge graph memory MCP server",
        "transport": "stdio",
        "command": ["npx", "-y", "@modelcontextprotocol/server-memory"],
        "docs_url": "https://github.com/modelcontextprotocol/servers",
    },
]


def sdlc_payload() -> dict[str, Any]:
    return {
        "reasoning_engine": "hermes",
        "coding_default": "hermes",
        "memory_provider": "hermes",
        "memory_config": {"root_folder": "OMC"},
        "tracking_provider": "none",
        "tracking_config": {},
        "routes": SDLC_ROUTES,
        "status_authority": SDLC_STATUS,
        "playbooks": {
            "feature": ["pm", "sa", "coder", "qa", "devops"],
            "bug": ["pm", "sa", "coder", "qa"],
        },
        "agents": SDLC_AGENTS,
        "chats": [{"platform": "discord", "label": "Primary Discord"}],
        "channels": SDLC_CHANNELS,
        "cron_jobs": [
            {
                "name": "Daily PM standup",
                "cron_expr": "0 9 * * 1-5",
                "agent_role": "pm",
                "channel_name": "standup",
                "prompt": "@PM Please post a concise daily project status digest for the Boss.",
                "enabled": True,
            }
        ],
        "mcp_servers": [],
    }


def seed_database(db: Database, activate: bool = True) -> dict[str, str]:
    """Ensure system template + builtin MCP + default workflow exist."""
    db.init_schema()
    now = _now()
    with db.connect() as conn:
        # Builtin MCP catalog
        for item in BUILTIN_MCP:
            conn.execute(
                "INSERT OR IGNORE INTO mcp_catalog(id, name, description, transport, command_json, env_json, docs_url, is_builtin) "
                "VALUES (?, ?, ?, ?, ?, '{}', ?, 1)",
                (
                    item["id"],
                    item["name"],
                    item["description"],
                    item["transport"],
                    _json(item["command"]),
                    item.get("docs_url", ""),
                ),
            )

        # System template
        tpl_id = "tpl-sdlc"
        row = conn.execute("SELECT id FROM templates WHERE id = ?", (tpl_id,)).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO templates(id, name, description, is_system, payload_json, created_at, updated_at) "
                "VALUES (?, ?, ?, 1, ?, ?, ?)",
                (
                    tpl_id,
                    "SDLC Workflow",
                    "Standard One Man Company software delivery (PM→SA→Coder→QA→DevOps)",
                    _json(sdlc_payload()),
                    now,
                    now,
                ),
            )

        # Default workflow instance if none
        existing = conn.execute("SELECT id FROM workflows LIMIT 1").fetchone()
        wf_id = None
        if not existing:
            wf_id = clone_template_into_conn(conn, tpl_id, name="SDLC Company", activate=activate)
        else:
            wf_id = existing["id"]
            if activate:
                # ensure at least one active if requested and none active
                active = conn.execute(
                    "SELECT id FROM workflows WHERE is_active = 1 LIMIT 1"
                ).fetchone()
                if not active:
                    conn.execute("UPDATE workflows SET is_active = 1 WHERE id = ?", (wf_id,))

        conn.execute(
            "INSERT INTO settings(key, value) VALUES('max_active_workflows', '5') "
            "ON CONFLICT(key) DO NOTHING"
        )
        conn.execute(
            "INSERT INTO settings(key, value) VALUES('agents_dir', ?) "
            "ON CONFLICT(key) DO NOTHING",
            (str(REPO_ROOT / "agents"),),
        )

    return {"template_id": "tpl-sdlc", "workflow_id": wf_id or ""}


def clone_template_into_conn(
    conn,
    template_id: str,
    name: str,
    activate: bool = False,
) -> str:
    row = conn.execute(
        "SELECT payload_json FROM templates WHERE id = ?", (template_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"Template not found: {template_id}")
    payload = json.loads(row["payload_json"])
    return _insert_workflow_from_payload(conn, name, payload, activate=activate)


def _insert_workflow_from_payload(
    conn, name: str, payload: dict[str, Any], activate: bool = False
) -> str:
    now = _now()
    wf_id = new_id("wf_")
    conn.execute(
        "INSERT INTO workflows(id, name, description, is_active, reasoning_engine, coding_default, "
        "coding_workspace, memory_provider, memory_config_json, tracking_provider, tracking_config_json, "
        "routes_json, status_authority_json, playbooks_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            wf_id,
            name,
            payload.get("description", ""),
            1 if activate else 0,
            payload.get("reasoning_engine", "hermes"),
            payload.get("coding_default", "hermes"),
            payload.get("coding_workspace", ""),
            payload.get("memory_provider", "hermes"),
            _json(payload.get("memory_config") or {}),
            payload.get("tracking_provider", "none"),
            _json(payload.get("tracking_config") or {}),
            _json(payload.get("routes") or {}),
            _json(payload.get("status_authority") or {}),
            _json(payload.get("playbooks") or {}),
            now,
            now,
        ),
    )

    for ag in payload.get("agents") or []:
        conn.execute(
            "INSERT INTO agents(id, workflow_id, role_id, display_name, mention, kind, persona_file, "
            "reasoning_engine, coding_backend, tools_json, mcp_allowlist_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id("ag_"),
                wf_id,
                ag["role_id"],
                ag.get("display_name") or ag["role_id"],
                ag.get("mention") or ag["role_id"],
                ag.get("kind") or "persona",
                ag.get("persona_file") or f"{ag['role_id']}.md",
                ag.get("reasoning_engine"),
                ag.get("coding_backend"),
                _json(ag.get("tools") or []),
                _json(ag.get("mcp_allowlist") or []),
            ),
        )

    chat_ids: list[str] = []
    for chat in payload.get("chats") or [{"platform": "discord", "label": "Primary"}]:
        cid = new_id("ch_")
        chat_ids.append(cid)
        conn.execute(
            "INSERT INTO chats(id, workflow_id, platform, label, credentials_ref, config_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                cid,
                wf_id,
                chat.get("platform", "discord"),
                chat.get("label", ""),
                chat.get("credentials_ref", ""),
                _json(chat.get("config") or {}),
            ),
        )

    primary_chat = chat_ids[0] if chat_ids else None
    for ch in payload.get("channels") or []:
        if not primary_chat:
            break
        conn.execute(
            "INSERT INTO channels(id, workflow_id, chat_id, name, external_id, agents_json, ticket_create_roles_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                new_id("cn_"),
                wf_id,
                primary_chat,
                ch["name"],
                ch.get("external_id", ""),
                _json(ch.get("agents") or []),
                _json(ch.get("ticket_create_roles") or []),
            ),
        )

    for job in payload.get("cron_jobs") or []:
        conn.execute(
            "INSERT INTO cron_jobs(id, workflow_id, name, cron_expr, agent_role, channel_name, prompt, enabled) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                new_id("cron_"),
                wf_id,
                job["name"],
                job["cron_expr"],
                job["agent_role"],
                job["channel_name"],
                job.get("prompt", ""),
                1 if job.get("enabled", True) else 0,
            ),
        )

    for mcp_id in payload.get("mcp_servers") or []:
        conn.execute(
            "INSERT OR IGNORE INTO mcp_workflow(id, workflow_id, catalog_id, enabled, config_json) "
            "VALUES (?, ?, ?, 1, '{}')",
            (new_id("mw_"), wf_id, mcp_id),
        )

    return wf_id


def clone_template(db: Database, template_id: str, name: str, activate: bool = False) -> str:
    with db.connect() as conn:
        # Deactivate others only if activating and we want exclusive? Multi-active allowed —
        # just set this one's flag; conflict check happens in workflow service.
        return clone_template_into_conn(conn, template_id, name, activate=activate)
