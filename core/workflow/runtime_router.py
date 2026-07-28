"""Build AgentRouter instances from WorkflowRuntime (multi-workflow bridge)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from adapters.base import ChannelAdapter
from core.agent_router import AgentRouter
from core.chat_messages import DEFAULT_MESSAGE_FORMAT, normalize_message_format
from core.coding import create_coding_registry
from core.config import load_workflow_agent_prompt
from core.db.seed import SDLC_CHANNELS
from core.sdlc_tracker import SDLCTracker
from core.secrets import build_tracker_config, load_workflow_secrets_into_environ
from core.tickets.factory import create_tracker
from core.workflow import WorkflowRuntime

logger = logging.getLogger(__name__)

# Fallback topic agents when channel.agents is empty (e.g. after channel dialog sync)
_DEFAULT_TOPIC_AGENTS = {c["name"]: list(c["agents"]) for c in SDLC_CHANNELS}
_DEFAULT_TICKET_ROLES = {
    c["name"]: list(c.get("ticket_create_roles") or []) for c in SDLC_CHANNELS
}


def _load_prompt(agents_dir: Path, role: str, persona_file: str) -> str:
    return load_workflow_agent_prompt(agents_dir, role, persona_file)


def topics_from_runtime(rt: WorkflowRuntime) -> tuple[dict[str, dict], dict[str, str], dict[str, str]]:
    """Return (topics, topic_by_channel_id, channel_names)."""
    topics: dict[str, dict] = {}
    topic_by_channel_id: dict[str, str] = {}
    channel_names: dict[str, str] = {}
    for ch in rt.workflow.channels:
        ext = (ch.external_id or "").strip()
        if not ext or ext.startswith("REPLACE_"):
            continue
        agents = list(ch.agents or []) or list(_DEFAULT_TOPIC_AGENTS.get(ch.name, []))
        ticket_roles = list(ch.ticket_create_roles or []) or list(
            _DEFAULT_TICKET_ROLES.get(ch.name, [])
        )
        topics[ch.name] = {
            "channel_id": ext,
            "agents": [a.lower() for a in agents],
            "ticket_create_roles": [a.lower() for a in ticket_roles],
        }
        topic_by_channel_id[ext] = ch.name
        channel_names[ext] = ch.name
    return topics, topic_by_channel_id, channel_names


def message_formats_from_runtime(rt: WorkflowRuntime) -> tuple[str, dict[str, str]]:
    """
    Return (default_format, channel_id → message_format) from chat configs.
    """
    chat_fmt: dict[str, str] = {}
    for chat in rt.workflow.chats:
        cfg = dict(chat.config or {})
        chat_fmt[chat.id] = normalize_message_format(cfg.get("message_format"))

    by_channel: dict[str, str] = {}
    formats_seen: list[str] = []
    for ch in rt.workflow.channels:
        ext = (ch.external_id or "").strip()
        if not ext or ext.startswith("REPLACE_"):
            continue
        fmt = chat_fmt.get(ch.chat_id) or DEFAULT_MESSAGE_FORMAT
        by_channel[ext] = fmt
        formats_seen.append(fmt)

    default = formats_seen[0] if formats_seen else DEFAULT_MESSAGE_FORMAT
    return default, by_channel


def build_agent_router(
    rt: WorkflowRuntime,
    adapter: ChannelAdapter,
    *,
    adapters_by_role: dict[str, ChannelAdapter] | None = None,
) -> AgentRouter:
    """Construct a full AgentRouter for one active workflow."""
    wf = rt.workflow
    load_workflow_secrets_into_environ(wf.id)

    topics, topic_by_channel_id, channel_names = topics_from_runtime(rt)
    agent_prompts: dict[str, str] = {}
    agent_meta: dict[str, dict[str, Any]] = {}
    for ag in wf.agents:
        agent_prompts[ag.role_id.lower()] = _load_prompt(
            rt.agents_dir, ag.role_id.lower(), ag.persona_file
        )
        # Also index by mention so @SA matches
        mention = (ag.mention or ag.role_id).lower()
        agent_prompts.setdefault(mention, agent_prompts[ag.role_id.lower()])
        agent_meta[ag.role_id.lower()] = {
            "id": ag.id,
            "role_id": ag.role_id,
            "hermes_profile": ag.hermes_profile or f"omc-{ag.role_id}",
            "llm_model": ag.llm_model or "",
            "kind": ag.kind,
            "reasoning_engine": ag.reasoning_engine,
            "coding_backend": ag.coding_backend,
        }

    coding_cfg: dict[str, Any] = {
        "default": wf.coding_default or "hermes",
        "workspace": (wf.coding_workspace or os.environ.get("OMC_WORKSPACE") or "").strip(),
        "aliases": {
            "hermes": "hermes",
            "claude": "claude",
            "cursor": "cursor",
            "opencode": "opencode",
            "codex": "codex",
            "coder": None,
        },
    }
    # Prefer per-agent coding_backend overrides via aliases when set
    for ag in wf.agents:
        if ag.kind == "coding" and ag.coding_backend:
            coding_cfg["aliases"][ag.role_id.lower()] = ag.coding_backend

    coding = create_coding_registry(coding_cfg)
    active_trk = next((t for t in (wf.trackings or []) if t.is_active), None)
    track_cfg = build_tracker_config(
        wf.id,
        (active_trk.provider if active_trk else wf.tracking_provider),
        (active_trk.config if active_trk else wf.tracking_config),
        connection_id=(active_trk.id if active_trk else ""),
    )
    ticket_tracker = create_tracker(track_cfg)
    sdlc = SDLCTracker(
        tracker=ticket_tracker,
        status_authority=wf.status_authority or {},
    )
    default_fmt, fmt_by_channel = message_formats_from_runtime(rt)

    return AgentRouter(
        adapter=adapter,
        topics=topics,
        topic_by_channel_id=topic_by_channel_id,
        agent_prompts=agent_prompts,
        agent_routes=wf.routes or {},
        channel_names=channel_names,
        coding=coding,
        sdlc=sdlc,
        task_mgr=rt.tickets,
        ticket_tracker=ticket_tracker,
        ticket_provider=(wf.tracking_provider or "none"),
        memory=rt.memory,
        message_format=default_fmt,
        message_format_by_channel=fmt_by_channel,
        workflow_id=wf.id,
        agent_meta=agent_meta,
        adapters_by_role=adapters_by_role or {},
        runtime=rt,
    )


def restore_default_channel_agents(repo) -> int:
    """Fill empty channel.agents from SDLC defaults. Returns updated count."""
    import json

    updated = 0
    for summary in repo.list_workflows():
        wf = repo.get_workflow(summary["id"])
        if not wf:
            continue
        for ch in wf.channels:
            if ch.agents:
                continue
            defaults = _DEFAULT_TOPIC_AGENTS.get(ch.name)
            if not defaults:
                continue
            ticket_roles = _DEFAULT_TICKET_ROLES.get(ch.name, [])
            with repo.db.connect() as conn:
                conn.execute(
                    "UPDATE channels SET agents_json = ?, ticket_create_roles_json = ? WHERE id = ?",
                    (
                        json.dumps(defaults),
                        json.dumps(ticket_roles),
                        ch.id,
                    ),
                )
            updated += 1
            logger.info(
                "Restored agents on #%s (%s): %s",
                ch.name,
                ch.id,
                ",".join(defaults),
            )
    return updated
