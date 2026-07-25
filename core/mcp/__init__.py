"""MCP marketplace — local catalog, workflow install, tool proxy hints."""

from __future__ import annotations

from typing import Any, Optional

from core.db import Database, _json, _now, _parse, new_id


class McpCatalog:
    def __init__(self, db: Database):
        self.db = db

    def list_catalog(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM mcp_catalog ORDER BY name"
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "description": r["description"],
                    "transport": r["transport"],
                    "command": _parse(r["command_json"], []),
                    "env": _parse(r["env_json"], {}),
                    "docs_url": r["docs_url"],
                    "is_builtin": bool(r["is_builtin"]),
                }
                for r in rows
            ]

    def add_custom(
        self,
        name: str,
        description: str = "",
        transport: str = "stdio",
        command: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
        docs_url: str = "",
    ) -> dict[str, Any]:
        cid = new_id("mcp_")
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO mcp_catalog(id, name, description, transport, command_json, env_json, docs_url, is_builtin) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                (
                    cid,
                    name,
                    description,
                    transport,
                    _json(command or []),
                    _json(env or {}),
                    docs_url,
                ),
            )
        return {
            "id": cid,
            "name": name,
            "description": description,
            "transport": transport,
            "command": command or [],
            "env": env or {},
            "docs_url": docs_url,
            "is_builtin": False,
        }

    def enable_on_workflow(
        self, workflow_id: str, catalog_id: str, enabled: bool = True, config: Optional[dict] = None
    ) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id FROM mcp_workflow WHERE workflow_id = ? AND catalog_id = ?",
                (workflow_id, catalog_id),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE mcp_workflow SET enabled = ?, config_json = ? WHERE id = ?",
                    (1 if enabled else 0, _json(config or {}), row["id"]),
                )
                mid = row["id"]
            else:
                mid = new_id("mw_")
                conn.execute(
                    "INSERT INTO mcp_workflow(id, workflow_id, catalog_id, enabled, config_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (mid, workflow_id, catalog_id, 1 if enabled else 0, _json(config or {})),
                )
        return {"id": mid, "workflow_id": workflow_id, "catalog_id": catalog_id, "enabled": enabled}

    def workflow_servers(self, workflow_id: str, enabled_only: bool = True) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            sql = (
                "SELECT mw.*, mc.name, mc.description, mc.transport, mc.command_json, mc.env_json, mc.docs_url "
                "FROM mcp_workflow mw JOIN mcp_catalog mc ON mc.id = mw.catalog_id "
                "WHERE mw.workflow_id = ?"
            )
            if enabled_only:
                sql += " AND mw.enabled = 1"
            rows = conn.execute(sql, (workflow_id,)).fetchall()
            return [
                {
                    "id": r["id"],
                    "catalog_id": r["catalog_id"],
                    "enabled": bool(r["enabled"]),
                    "name": r["name"],
                    "description": r["description"],
                    "transport": r["transport"],
                    "command": _parse(r["command_json"], []),
                    "env": _parse(r["env_json"], {}),
                    "docs_url": r["docs_url"],
                    "config": _parse(r["config_json"], {}),
                }
                for r in rows
            ]

    def resolve_for_agent(
        self, workflow_id: str, allowlist: list[str]
    ) -> list[dict[str, Any]]:
        """Return enabled MCP servers filtered by agent allowlist (catalog ids)."""
        servers = self.workflow_servers(workflow_id, enabled_only=True)
        if not allowlist:
            return servers
        allow = set(allowlist)
        return [s for s in servers if s["catalog_id"] in allow or s["id"] in allow]
