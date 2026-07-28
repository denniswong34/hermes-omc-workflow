"""Workflow repository — load/save workflows from SQLite."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from core.db import Database, _json, _now, _parse, new_id
from core.db.seed import clone_template, seed_database


@dataclass
class AgentRecord:
    id: str
    workflow_id: str
    role_id: str
    display_name: str
    mention: str
    kind: str
    persona_file: str
    reasoning_engine: Optional[str] = None
    coding_backend: Optional[str] = None
    hermes_profile: str = ""
    llm_model: str = ""
    platform_identity: dict[str, Any] = field(default_factory=dict)
    tools: list[str] = field(default_factory=list)
    mcp_allowlist: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "role_id": self.role_id,
            "display_name": self.display_name,
            "mention": self.mention,
            "kind": self.kind,
            "persona_file": self.persona_file,
            "reasoning_engine": self.reasoning_engine,
            "coding_backend": self.coding_backend,
            "hermes_profile": self.hermes_profile,
            "llm_model": self.llm_model,
            "platform_identity": self.platform_identity,
            "tools": self.tools,
            "mcp_allowlist": self.mcp_allowlist,
        }


@dataclass
class ChannelRecord:
    id: str
    workflow_id: str
    chat_id: str
    name: str
    external_id: str
    agents: list[str]
    ticket_create_roles: list[str]
    platform: str = "discord"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "chat_id": self.chat_id,
            "name": self.name,
            "external_id": self.external_id,
            "agents": self.agents,
            "ticket_create_roles": self.ticket_create_roles,
            "platform": self.platform,
        }


@dataclass
class ChatRecord:
    id: str
    workflow_id: str
    platform: str
    label: str
    credentials_ref: str
    config: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "platform": self.platform,
            "label": self.label,
            "credentials_ref": self.credentials_ref,
            "config": self.config,
        }


@dataclass
class TrackingConnectionRecord:
    id: str
    workflow_id: str
    provider: str
    label: str
    config: dict[str, Any]
    is_active: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "provider": self.provider,
            "label": self.label,
            "config": self.config,
            "is_active": self.is_active,
        }


@dataclass
class CronRecord:
    id: str
    workflow_id: str
    name: str
    cron_expr: str
    agent_role: str
    channel_name: str
    prompt: str
    enabled: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "name": self.name,
            "cron_expr": self.cron_expr,
            "agent_role": self.agent_role,
            "channel_name": self.channel_name,
            "prompt": self.prompt,
            "enabled": self.enabled,
        }


@dataclass
class WorkflowRecord:
    id: str
    name: str
    description: str
    is_active: bool
    reasoning_engine: str
    coding_default: str
    coding_workspace: str
    memory_provider: str
    memory_config: dict[str, Any]
    tracking_provider: str
    tracking_config: dict[str, Any]
    routes: dict[str, list[str]]
    status_authority: dict[str, list[str]]
    playbooks: dict[str, list[str]]
    agents: list[AgentRecord] = field(default_factory=list)
    chats: list[ChatRecord] = field(default_factory=list)
    trackings: list[TrackingConnectionRecord] = field(default_factory=list)
    channels: list[ChannelRecord] = field(default_factory=list)
    cron_jobs: list[CronRecord] = field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    project_id: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "is_active": self.is_active,
            "project_id": self.project_id,
            "reasoning_engine": self.reasoning_engine,
            "coding_default": self.coding_default,
            "coding_workspace": self.coding_workspace,
            "memory_provider": self.memory_provider,
            "memory_config": self.memory_config,
            "tracking_provider": self.tracking_provider,
            "tracking_config": self.tracking_config,
            "routes": self.routes,
            "status_authority": self.status_authority,
            "playbooks": self.playbooks,
            "agents": [a.to_dict() for a in self.agents],
            "chats": [c.to_dict() for c in self.chats],
            "trackings": [t.to_dict() for t in self.trackings],
            "channels": [c.to_dict() for c in self.channels],
            "cron_jobs": [j.to_dict() for j in self.cron_jobs],
            "mcp_servers": self.mcp_servers,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ChannelConflictError(Exception):
    def __init__(self, conflicts: list[dict[str, str]]):
        self.conflicts = conflicts
        msgs = [
            f"{c['platform']}:{c['external_id']} owned by '{c['owner_name']}' ({c['owner_id']})"
            for c in conflicts
        ]
        super().__init__("Channel conflict: " + "; ".join(msgs))


class WorkflowRepository:
    def __init__(self, db: Database):
        self.db = db

    def ensure_seeded(self) -> None:
        seed_database(self.db, activate=True)

    def list_workflows(self, project_id: str | None = None) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            if project_id:
                rows = conn.execute(
                    "SELECT id, name, description, is_active, project_id, reasoning_engine, memory_provider, "
                    "tracking_provider, created_at, updated_at FROM workflows "
                    "WHERE project_id = ? ORDER BY name",
                    (project_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, name, description, is_active, project_id, reasoning_engine, memory_provider, "
                    "tracking_provider, created_at, updated_at FROM workflows ORDER BY name"
                ).fetchall()
            return [dict(r) | {"is_active": bool(r["is_active"])} for r in rows]

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowRecord]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflows WHERE id = ?", (workflow_id,)
            ).fetchone()
            if not row:
                return None
            agents = [
                self._agent_from_row(a)
                for a in conn.execute(
                    "SELECT * FROM agents WHERE workflow_id = ? ORDER BY role_id",
                    (workflow_id,),
                ).fetchall()
            ]
            chats = [
                ChatRecord(
                    id=c["id"],
                    workflow_id=c["workflow_id"],
                    platform=c["platform"],
                    label=c["label"],
                    credentials_ref=c["credentials_ref"],
                    config=_parse(c["config_json"], {}),
                )
                for c in conn.execute(
                    "SELECT * FROM chats WHERE workflow_id = ?", (workflow_id,)
                ).fetchall()
            ]
            trackings = [
                TrackingConnectionRecord(
                    id=t["id"],
                    workflow_id=t["workflow_id"],
                    provider=t["provider"],
                    label=t["label"] or "",
                    config=_parse(t["config_json"], {}),
                    is_active=bool(t["is_active"]),
                )
                for t in conn.execute(
                    "SELECT * FROM tracking_connections WHERE workflow_id = ? "
                    "ORDER BY is_active DESC, label ASC",
                    (workflow_id,),
                ).fetchall()
            ]
            chat_platform = {c.id: c.platform for c in chats}
            channels = [
                ChannelRecord(
                    id=c["id"],
                    workflow_id=c["workflow_id"],
                    chat_id=c["chat_id"],
                    name=c["name"],
                    external_id=c["external_id"] or "",
                    agents=_parse(c["agents_json"], []),
                    ticket_create_roles=_parse(c["ticket_create_roles_json"], []),
                    platform=chat_platform.get(c["chat_id"], "discord"),
                )
                for c in conn.execute(
                    "SELECT * FROM channels WHERE workflow_id = ? ORDER BY name",
                    (workflow_id,),
                ).fetchall()
            ]
            cron_jobs = [
                CronRecord(
                    id=j["id"],
                    workflow_id=j["workflow_id"],
                    name=j["name"],
                    cron_expr=j["cron_expr"],
                    agent_role=j["agent_role"],
                    channel_name=j["channel_name"],
                    prompt=j["prompt"],
                    enabled=bool(j["enabled"]),
                )
                for j in conn.execute(
                    "SELECT * FROM cron_jobs WHERE workflow_id = ?", (workflow_id,)
                ).fetchall()
            ]
            mcp_servers = [
                {
                    "id": m["id"],
                    "catalog_id": m["catalog_id"],
                    "enabled": bool(m["enabled"]),
                    "config": _parse(m["config_json"], {}),
                    "name": m["name"],
                    "description": m["description"],
                    "transport": m["transport"],
                    "command": _parse(m["command_json"], []),
                    "docs_url": m["docs_url"],
                }
                for m in conn.execute(
                    "SELECT mw.*, mc.name, mc.description, mc.transport, mc.command_json, mc.docs_url "
                    "FROM mcp_workflow mw JOIN mcp_catalog mc ON mc.id = mw.catalog_id "
                    "WHERE mw.workflow_id = ?",
                    (workflow_id,),
                ).fetchall()
            ]
            return WorkflowRecord(
                id=row["id"],
                name=row["name"],
                description=row["description"] or "",
                is_active=bool(row["is_active"]),
                project_id=row["project_id"] or "",
                reasoning_engine=row["reasoning_engine"],
                coding_default=row["coding_default"],
                coding_workspace=row["coding_workspace"] or "",
                memory_provider=row["memory_provider"],
                memory_config=_parse(row["memory_config_json"], {}),
                tracking_provider=row["tracking_provider"],
                tracking_config=_parse(row["tracking_config_json"], {}),
                routes=_parse(row["routes_json"], {}),
                status_authority=_parse(row["status_authority_json"], {}),
                playbooks=_parse(row["playbooks_json"], {}),
                agents=agents,
                chats=chats,
                trackings=trackings,
                channels=channels,
                cron_jobs=cron_jobs,
                mcp_servers=mcp_servers,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def list_active(self) -> list[WorkflowRecord]:
        with self.db.connect() as conn:
            ids = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM workflows WHERE is_active = 1"
                ).fetchall()
            ]
        return [w for wid in ids if (w := self.get_workflow(wid))]

    def find_channel_conflicts(
        self, workflow_id: str, channels: Optional[list[ChannelRecord]] = None
    ) -> list[dict[str, str]]:
        wf = self.get_workflow(workflow_id)
        if not wf:
            return []
        check = channels if channels is not None else wf.channels
        conflicts: list[dict[str, str]] = []
        with self.db.connect() as conn:
            for ch in check:
                ext = (ch.external_id or "").strip()
                if not ext or ext.startswith("REPLACE_"):
                    continue
                platform = ch.platform
                rows = conn.execute(
                    "SELECT c.external_id, c.name, c.workflow_id, w.name AS wf_name, ch.platform "
                    "FROM channels c "
                    "JOIN workflows w ON w.id = c.workflow_id "
                    "JOIN chats ch ON ch.id = c.chat_id "
                    "WHERE w.is_active = 1 AND w.id != ? AND c.external_id = ? AND ch.platform = ?",
                    (workflow_id, ext, platform),
                ).fetchall()
                for r in rows:
                    conflicts.append(
                        {
                            "platform": r["platform"],
                            "external_id": r["external_id"],
                            "channel_name": r["name"],
                            "owner_id": r["workflow_id"],
                            "owner_name": r["wf_name"],
                        }
                    )
        return conflicts

    def set_active(self, workflow_id: str, active: bool) -> WorkflowRecord:
        wf = self.get_workflow(workflow_id)
        if not wf:
            raise ValueError(f"Workflow not found: {workflow_id}")
        if active:
            max_active = int(self.db.get_setting("max_active_workflows", "5") or "5")
            actives = self.list_active()
            if not wf.is_active and len(actives) >= max_active:
                raise ValueError(
                    f"Soft limit: at most {max_active} active workflows. Deactivate another first."
                )
            conflicts = self.find_channel_conflicts(workflow_id)
            if conflicts:
                raise ChannelConflictError(conflicts)
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE workflows SET is_active = ?, updated_at = ? WHERE id = ?",
                (1 if active else 0, _now(), workflow_id),
            )
        out = self.get_workflow(workflow_id)
        assert out
        return out

    def update_workflow(self, workflow_id: str, patch: dict[str, Any]) -> WorkflowRecord:
        allowed = {
            "name",
            "description",
            "reasoning_engine",
            "coding_default",
            "coding_workspace",
            "memory_provider",
            "memory_config",
            "tracking_provider",
            "tracking_config",
            "routes",
            "status_authority",
            "playbooks",
        }
        cols = []
        vals: list[Any] = []
        mapping = {
            "memory_config": "memory_config_json",
            "tracking_config": "tracking_config_json",
            "routes": "routes_json",
            "status_authority": "status_authority_json",
            "playbooks": "playbooks_json",
        }
        for k, v in patch.items():
            if k not in allowed:
                continue
            col = mapping.get(k, k)
            if col.endswith("_json"):
                vals.append(_json(v))
            else:
                vals.append(v)
            cols.append(f"{col} = ?")
        if not cols:
            wf = self.get_workflow(workflow_id)
            if not wf:
                raise ValueError("not found")
            return wf
        cols.append("updated_at = ?")
        vals.append(_now())
        vals.append(workflow_id)
        with self.db.connect() as conn:
            conn.execute(
                f"UPDATE workflows SET {', '.join(cols)} WHERE id = ?",
                vals,
            )
        wf = self.get_workflow(workflow_id)
        assert wf
        return wf

    def update_channel_external_id(
        self, channel_id: str, external_id: str
    ) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE channels SET external_id = ? WHERE id = ?",
                (external_id, channel_id),
            )

    def _agent_from_row(self, row) -> AgentRecord:
        keys = set(row.keys()) if hasattr(row, "keys") else set()
        hermes_profile = ""
        llm_model = ""
        platform_identity: dict[str, Any] = {}
        if "hermes_profile" in keys:
            hermes_profile = row["hermes_profile"] or ""
        if "llm_model" in keys:
            llm_model = row["llm_model"] or ""
        if "platform_identity_json" in keys:
            platform_identity = _parse(row["platform_identity_json"], {})
        return AgentRecord(
            id=row["id"],
            workflow_id=row["workflow_id"],
            role_id=row["role_id"],
            display_name=row["display_name"],
            mention=row["mention"],
            kind=row["kind"],
            persona_file=row["persona_file"],
            reasoning_engine=row["reasoning_engine"],
            coding_backend=row["coding_backend"],
            hermes_profile=hermes_profile,
            llm_model=llm_model,
            platform_identity=platform_identity,
            tools=_parse(row["tools_json"], []),
            mcp_allowlist=_parse(row["mcp_allowlist_json"], []),
        )

    def update_agent(self, agent_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "display_name",
            "mention",
            "kind",
            "persona_file",
            "reasoning_engine",
            "coding_backend",
            "hermes_profile",
            "llm_model",
            "platform_identity",
            "tools",
            "mcp_allowlist",
        }
        cols = []
        vals: list[Any] = []
        for k, v in patch.items():
            if k not in allowed:
                continue
            if k in ("tools", "mcp_allowlist"):
                cols.append(f"{k}_json = ?")
                vals.append(_json(v))
            elif k == "platform_identity":
                cols.append("platform_identity_json = ?")
                vals.append(_json(v or {}))
            else:
                cols.append(f"{k} = ?")
                vals.append(v)
        if cols:
            vals.append(agent_id)
            with self.db.connect() as conn:
                conn.execute(
                    f"UPDATE agents SET {', '.join(cols)} WHERE id = ?", vals
                )
                row = conn.execute(
                    "SELECT * FROM agents WHERE id = ?", (agent_id,)
                ).fetchone()
                if not row:
                    raise ValueError("agent not found")
                return self._agent_from_row(row).to_dict()
        raise ValueError("no fields")

    def add_agent(self, workflow_id: str, data: dict[str, Any]) -> dict[str, Any]:
        if not self.get_workflow(workflow_id):
            raise ValueError("workflow not found")
        role_id = (data.get("role_id") or "").strip().lower().replace(" ", "_")
        if not role_id:
            raise ValueError("role_id required")
        mention = (data.get("mention") or role_id).strip()
        display = (data.get("display_name") or mention).strip()
        kind = (data.get("kind") or "persona").strip().lower()
        persona_file = (data.get("persona_file") or f"{role_id}.md").strip()
        aid = new_id("ag_")
        hermes_profile = (data.get("hermes_profile") or f"omc-{role_id}").strip()
        llm_model = (data.get("llm_model") or "").strip()
        platform_identity = data.get("platform_identity") or {}
        with self.db.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM agents WHERE workflow_id = ? AND role_id = ?",
                (workflow_id, role_id),
            ).fetchone()
            if existing:
                raise ValueError(f"Agent role_id already exists: {role_id}")
            conn.execute(
                "INSERT INTO agents(id, workflow_id, role_id, display_name, mention, kind, persona_file, "
                "reasoning_engine, coding_backend, hermes_profile, llm_model, platform_identity_json, "
                "tools_json, mcp_allowlist_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    aid,
                    workflow_id,
                    role_id,
                    display,
                    mention,
                    kind,
                    persona_file,
                    data.get("reasoning_engine"),
                    data.get("coding_backend"),
                    hermes_profile,
                    llm_model,
                    _json(platform_identity),
                    _json(data.get("tools") or []),
                    _json(data.get("mcp_allowlist") or []),
                ),
            )
            row = conn.execute("SELECT * FROM agents WHERE id = ?", (aid,)).fetchone()
        return self._agent_from_row(row).to_dict()

    def delete_agent(self, workflow_id: str, agent_id: str) -> None:
        with self.db.connect() as conn:
            cur = conn.execute(
                "DELETE FROM agents WHERE id = ? AND workflow_id = ?",
                (agent_id, workflow_id),
            )
            if cur.rowcount == 0:
                raise ValueError("agent not found")

    def add_chat(self, workflow_id: str, data: dict[str, Any]) -> dict[str, Any]:
        from core.secrets import PLATFORMS

        if not self.get_workflow(workflow_id):
            raise ValueError("workflow not found")
        platform = (data.get("platform") or "discord").strip().lower()
        if platform not in PLATFORMS:
            raise ValueError(f"platform must be one of {PLATFORMS}")
        label = (data.get("label") or f"Primary {platform.title()}").strip()
        cid = new_id("ch_")
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO chats(id, workflow_id, platform, label, credentials_ref, config_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    cid,
                    workflow_id,
                    platform,
                    label,
                    data.get("credentials_ref") or workflow_id,
                    _json(data.get("config") or {}),
                ),
            )
        return {
            "id": cid,
            "workflow_id": workflow_id,
            "platform": platform,
            "label": label,
            "credentials_ref": data.get("credentials_ref") or workflow_id,
            "config": data.get("config") or {},
        }

    def update_chat(self, workflow_id: str, chat_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        from core.secrets import PLATFORMS

        cols = []
        vals: list[Any] = []
        if "platform" in patch and patch["platform"] is not None:
            platform = str(patch["platform"]).strip().lower()
            if platform not in PLATFORMS:
                raise ValueError(f"platform must be one of {PLATFORMS}")
            cols.append("platform = ?")
            vals.append(platform)
        if "label" in patch and patch["label"] is not None:
            cols.append("label = ?")
            vals.append(patch["label"])
        if "credentials_ref" in patch and patch["credentials_ref"] is not None:
            cols.append("credentials_ref = ?")
            vals.append(patch["credentials_ref"])
        if "config" in patch and patch["config"] is not None:
            cols.append("config_json = ?")
            vals.append(_json(patch["config"]))
        if not cols:
            raise ValueError("no fields")
        vals.extend([chat_id, workflow_id])
        with self.db.connect() as conn:
            cur = conn.execute(
                f"UPDATE chats SET {', '.join(cols)} WHERE id = ? AND workflow_id = ?",
                vals,
            )
            if cur.rowcount == 0:
                raise ValueError("chat not found")
            row = conn.execute(
                "SELECT * FROM chats WHERE id = ?", (chat_id,)
            ).fetchone()
        return ChatRecord(
            id=row["id"],
            workflow_id=row["workflow_id"],
            platform=row["platform"],
            label=row["label"],
            credentials_ref=row["credentials_ref"],
            config=_parse(row["config_json"], {}),
        ).to_dict()

    def delete_chat(self, workflow_id: str, chat_id: str) -> None:
        with self.db.connect() as conn:
            # channels cascade via FK if ON DELETE CASCADE works
            conn.execute(
                "DELETE FROM channels WHERE chat_id = ? AND workflow_id = ?",
                (chat_id, workflow_id),
            )
            cur = conn.execute(
                "DELETE FROM chats WHERE id = ? AND workflow_id = ?",
                (chat_id, workflow_id),
            )
            if cur.rowcount == 0:
                raise ValueError("chat not found")

    def _tracking_from_row(self, row) -> TrackingConnectionRecord:
        return TrackingConnectionRecord(
            id=row["id"],
            workflow_id=row["workflow_id"],
            provider=row["provider"],
            label=row["label"] or "",
            config=_parse(row["config_json"], {}),
            is_active=bool(row["is_active"]),
        )

    def _sync_active_tracking_cache(
        self, conn, workflow_id: str
    ) -> None:
        """Keep workflows.tracking_* synced with the active connection."""
        row = conn.execute(
            "SELECT * FROM tracking_connections "
            "WHERE workflow_id = ? AND is_active = 1 LIMIT 1",
            (workflow_id,),
        ).fetchone()
        now = _now()
        if not row:
            conn.execute(
                "UPDATE workflows SET tracking_provider = 'none', "
                "tracking_config_json = '{}', updated_at = ? WHERE id = ?",
                (now, workflow_id),
            )
            return
        conn.execute(
            "UPDATE workflows SET tracking_provider = ?, tracking_config_json = ?, "
            "updated_at = ? WHERE id = ?",
            (row["provider"], row["config_json"], now, workflow_id),
        )

    def add_tracking(self, workflow_id: str, data: dict[str, Any]) -> dict[str, Any]:
        from core.secrets import TRACKING_PROVIDERS

        if not self.get_workflow(workflow_id):
            raise ValueError("workflow not found")
        provider = (data.get("provider") or "").strip().lower()
        if provider not in TRACKING_PROVIDERS:
            raise ValueError(f"provider must be one of {TRACKING_PROVIDERS}")
        label = (data.get("label") or f"{provider[:1].upper()}{provider[1:]} #1").strip()
        tid = new_id("trk_")
        activate = bool(data.get("is_active", False))
        with self.db.connect() as conn:
            active_count = conn.execute(
                "SELECT COUNT(1) AS n FROM tracking_connections "
                "WHERE workflow_id = ? AND is_active = 1",
                (workflow_id,),
            ).fetchone()
            if activate or not active_count or int(active_count["n"] or 0) == 0:
                activate = True
                conn.execute(
                    "UPDATE tracking_connections SET is_active = 0 WHERE workflow_id = ?",
                    (workflow_id,),
                )
            conn.execute(
                "INSERT INTO tracking_connections"
                "(id, workflow_id, provider, label, config_json, is_active) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    tid,
                    workflow_id,
                    provider,
                    label,
                    _json(data.get("config") or {}),
                    1 if activate else 0,
                ),
            )
            if activate:
                self._sync_active_tracking_cache(conn, workflow_id)
        return {
            "id": tid,
            "workflow_id": workflow_id,
            "provider": provider,
            "label": label,
            "config": data.get("config") or {},
            "is_active": activate,
        }

    def update_tracking(
        self, workflow_id: str, tracking_id: str, patch: dict[str, Any]
    ) -> dict[str, Any]:
        from core.secrets import TRACKING_PROVIDERS

        cols = []
        vals: list[Any] = []
        if "provider" in patch and patch["provider"] is not None:
            provider = str(patch["provider"]).strip().lower()
            if provider not in TRACKING_PROVIDERS:
                raise ValueError(f"provider must be one of {TRACKING_PROVIDERS}")
            cols.append("provider = ?")
            vals.append(provider)
        if "label" in patch and patch["label"] is not None:
            cols.append("label = ?")
            vals.append(patch["label"])
        if "config" in patch and patch["config"] is not None:
            cols.append("config_json = ?")
            vals.append(_json(patch["config"]))
        if not cols:
            raise ValueError("no fields")
        vals.extend([tracking_id, workflow_id])
        with self.db.connect() as conn:
            cur = conn.execute(
                f"UPDATE tracking_connections SET {', '.join(cols)} "
                "WHERE id = ? AND workflow_id = ?",
                vals,
            )
            if cur.rowcount == 0:
                raise ValueError("tracking connection not found")
            row = conn.execute(
                "SELECT * FROM tracking_connections WHERE id = ?", (tracking_id,)
            ).fetchone()
            if row and bool(row["is_active"]):
                self._sync_active_tracking_cache(conn, workflow_id)
        return self._tracking_from_row(row).to_dict()

    def delete_tracking(self, workflow_id: str, tracking_id: str) -> None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT is_active FROM tracking_connections "
                "WHERE id = ? AND workflow_id = ?",
                (tracking_id, workflow_id),
            ).fetchone()
            if not row:
                raise ValueError("tracking connection not found")
            was_active = bool(row["is_active"])
            conn.execute(
                "DELETE FROM tracking_connections WHERE id = ? AND workflow_id = ?",
                (tracking_id, workflow_id),
            )
            if was_active:
                nxt = conn.execute(
                    "SELECT id FROM tracking_connections WHERE workflow_id = ? "
                    "ORDER BY label ASC LIMIT 1",
                    (workflow_id,),
                ).fetchone()
                if nxt:
                    conn.execute(
                        "UPDATE tracking_connections SET is_active = 1 WHERE id = ?",
                        (nxt["id"],),
                    )
                self._sync_active_tracking_cache(conn, workflow_id)

    def set_active_tracking(self, workflow_id: str, tracking_id: str) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM tracking_connections "
                "WHERE id = ? AND workflow_id = ?",
                (tracking_id, workflow_id),
            ).fetchone()
            if not row:
                raise ValueError("tracking connection not found")
            conn.execute(
                "UPDATE tracking_connections SET is_active = 0 WHERE workflow_id = ?",
                (workflow_id,),
            )
            conn.execute(
                "UPDATE tracking_connections SET is_active = 1 WHERE id = ?",
                (tracking_id,),
            )
            self._sync_active_tracking_cache(conn, workflow_id)
            row = conn.execute(
                "SELECT * FROM tracking_connections WHERE id = ?", (tracking_id,)
            ).fetchone()
        return self._tracking_from_row(row).to_dict()

    def add_channel(self, workflow_id: str, data: dict[str, Any]) -> dict[str, Any]:
        wf = self.get_workflow(workflow_id)
        if not wf:
            raise ValueError("workflow not found")
        name = (data.get("name") or "").strip().lower().replace(" ", "_")
        if not name:
            raise ValueError("name required")
        chat_id = data.get("chat_id")
        if not chat_id:
            if not wf.chats:
                raise ValueError("Create a chat connection first")
            chat_id = wf.chats[0].id
        cid = new_id("cn_")
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO channels(id, workflow_id, chat_id, name, external_id, agents_json, ticket_create_roles_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    cid,
                    workflow_id,
                    chat_id,
                    name,
                    data.get("external_id") or "",
                    _json(data.get("agents") or []),
                    _json(data.get("ticket_create_roles") or []),
                ),
            )
        wf2 = self.get_workflow(workflow_id)
        assert wf2
        ch = next(c for c in wf2.channels if c.id == cid)
        return ch.to_dict()

    def delete_channel(self, workflow_id: str, channel_id: str) -> None:
        with self.db.connect() as conn:
            cur = conn.execute(
                "DELETE FROM channels WHERE id = ? AND workflow_id = ?",
                (channel_id, workflow_id),
            )
            if cur.rowcount == 0:
                raise ValueError("channel not found")

    def list_templates(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT id, name, description, is_system, created_at, updated_at FROM templates ORDER BY name"
            ).fetchall()
            return [dict(r) | {"is_system": bool(r["is_system"])} for r in rows]

    def clone_from_template(
        self,
        template_id: str,
        name: str,
        *,
        project_id: str,
        coding_workspace: str | None = None,
    ) -> WorkflowRecord:
        if not project_id:
            raise ValueError("Create a project first")
        wf_id = clone_template(
            self.db,
            template_id,
            name,
            activate=False,
            project_id=project_id,
            coding_workspace=coding_workspace,
        )
        wf = self.get_workflow(wf_id)
        assert wf
        return wf

    def save_as_template(self, workflow_id: str, name: str, description: str = "") -> dict[str, Any]:
        wf = self.get_workflow(workflow_id)
        if not wf:
            raise ValueError("workflow not found")
        payload = {
            "description": description or wf.description,
            "reasoning_engine": wf.reasoning_engine,
            "coding_default": wf.coding_default,
            "coding_workspace": wf.coding_workspace,
            "memory_provider": wf.memory_provider,
            "memory_config": wf.memory_config,
            "tracking_provider": wf.tracking_provider,
            "tracking_config": wf.tracking_config,
            "routes": wf.routes,
            "status_authority": wf.status_authority,
            "playbooks": wf.playbooks,
            "agents": [
                {
                    "role_id": a.role_id,
                    "display_name": a.display_name,
                    "mention": a.mention,
                    "kind": a.kind,
                    "persona_file": a.persona_file,
                    "reasoning_engine": a.reasoning_engine,
                    "coding_backend": a.coding_backend,
                    "hermes_profile": a.hermes_profile,
                    "llm_model": a.llm_model,
                    "tools": a.tools,
                    "mcp_allowlist": a.mcp_allowlist,
                }
                for a in wf.agents
            ],
            "chats": [
                {
                    "platform": c.platform,
                    "label": c.label,
                    "credentials_ref": c.credentials_ref,
                    "config": c.config,
                }
                for c in wf.chats
            ],
            "channels": [
                {
                    "name": c.name,
                    "external_id": "",
                    "agents": c.agents,
                    "ticket_create_roles": c.ticket_create_roles,
                }
                for c in wf.channels
            ],
            "cron_jobs": [
                {
                    "name": j.name,
                    "cron_expr": j.cron_expr,
                    "agent_role": j.agent_role,
                    "channel_name": j.channel_name,
                    "prompt": j.prompt,
                    "enabled": j.enabled,
                }
                for j in wf.cron_jobs
            ],
            "mcp_servers": [m["catalog_id"] for m in wf.mcp_servers if m.get("enabled")],
        }
        tid = new_id("tpl_")
        now = _now()
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO templates(id, name, description, is_system, payload_json, created_at, updated_at) "
                "VALUES (?, ?, ?, 0, ?, ?, ?)",
                (tid, name, description or wf.description, _json(payload), now, now),
            )
        return {"id": tid, "name": name, "description": description, "is_system": False}

    def channel_ownership_map(self) -> dict[tuple[str, str], str]:
        """(platform, external_id) -> workflow_id for active workflows."""
        mapping: dict[tuple[str, str], str] = {}
        for wf in self.list_active():
            for ch in wf.channels:
                ext = (ch.external_id or "").strip()
                if ext and not ext.startswith("REPLACE_"):
                    mapping[(ch.platform, ext)] = wf.id
        return mapping
