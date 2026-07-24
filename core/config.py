"""
Configuration Loader
=====================
Loads SaaS topic rooms, agent personas, routes, coding backends, and tickets.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_AGENT_ROUTES = {
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
}

DEFAULT_STATUS_AUTHORITY = {
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
}

# Persona markdown files (coding aliases reuse coder.md when needed)
ROLE_FILES = {
    "pm": "pm.md",
    "sa": "sa.md",
    "coder": "coder.md",
    "qa": "qa.md",
    "devops": "devops.md",
    "marketing": "marketing.md",
    "standup": "standup.md",
    "hermes": "coder.md",
    "claude": "coder.md",
    "cursor": "coder.md",
    "opencode": "coder.md",
}

CODING_ALIASES = {"coder", "hermes", "claude", "cursor", "opencode"}

_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _expand_env(value: Any) -> Any:
    """Recursively expand ${VAR} placeholders from the environment."""
    if isinstance(value, str):
        def repl(m: re.Match) -> str:
            return os.environ.get(m.group(1), "")

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def _resolve_config_path(path: str | None = None) -> Path:
    if path:
        return Path(path).expanduser()
    env_path = os.environ.get("OMC_CONFIG")
    if env_path:
        return Path(env_path).expanduser()
    return REPO_ROOT / "config" / "omc.yaml"


def _read_markdown(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Agent persona not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def load_agent_prompt(agents_dir: Path, role: str) -> str:
    """Concatenate shared SDLC/handoff rules with the role persona."""
    shared_dir = agents_dir / "_shared"
    parts: list[str] = []
    for name in ("sdlc.md", "handoff.md"):
        shared = shared_dir / name
        if shared.exists():
            parts.append(_read_markdown(shared))
    role_file = ROLE_FILES.get(role)
    if not role_file:
        raise ValueError(f"Unknown agent role: {role}")
    parts.append(_read_markdown(agents_dir / role_file))
    return "\n\n---\n\n".join(parts)


def _normalize_role(name: str) -> str:
    return name.strip().lstrip("#@").lower()


def _normalize_routes(raw_routes: dict | None) -> dict[str, list[str]]:
    if not raw_routes:
        return {k: list(v) for k, v in DEFAULT_AGENT_ROUTES.items()}
    out: dict[str, list[str]] = {}
    for src, targets in raw_routes.items():
        key = _normalize_role(str(src))
        out[key] = [_normalize_role(str(t)) for t in (targets or [])]
    return out


def _normalize_status_authority(raw: dict | None) -> dict[str, list[str]]:
    if not raw:
        return {k: list(v) for k, v in DEFAULT_STATUS_AUTHORITY.items()}
    out: dict[str, list[str]] = {}
    for role, statuses in raw.items():
        key = _normalize_role(str(role))
        out[key] = [str(s).strip().lower() for s in (statuses or [])]
    return out


def load_config(path: str | None = None) -> dict:
    """Load OMC topic config and build agent prompt map."""
    config_path = _resolve_config_path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    raw = _expand_env(raw)
    omc = raw.get("omc", {})
    topics_raw = raw.get("topics") or {}
    if not topics_raw:
        raise ValueError("config.topics is required (topic → channel_id + agents)")

    agents_dir_cfg = omc.get("agents_dir", "agents")
    agents_dir = Path(agents_dir_cfg)
    if not agents_dir.is_absolute():
        agents_dir = (REPO_ROOT / agents_dir).resolve()

    topics: dict[str, dict] = {}
    topic_by_channel_id: dict[str, str] = {}
    channel_names: dict[str, str] = {}  # id → #topic
    channel_by_name: dict[str, str] = {}  # #topic → id
    all_roles: set[str] = set()

    for topic_key, tcfg in topics_raw.items():
        key = str(topic_key).strip().lower()
        if not isinstance(tcfg, dict):
            continue
        cid = str(tcfg.get("channel_id") or "").strip()
        if not cid or cid.startswith("REPLACE_"):
            # Skip unconfigured topics so the bridge can start partially
            continue
        agents = [_normalize_role(a) for a in (tcfg.get("agents") or [])]
        ticket_roles = [
            _normalize_role(a) for a in (tcfg.get("ticket_create_roles") or [])
        ]
        topics[key] = {
            "key": key,
            "channel_id": cid,
            "agents": agents,
            "ticket_create_roles": ticket_roles,
            "default_agent": tcfg.get("default_agent"),
        }
        topic_by_channel_id[cid] = key
        channel_names[cid] = f"#{key}"
        channel_by_name[f"#{key}"] = cid
        all_roles.update(agents)

    if not topics:
        raise ValueError(
            "No topics have a real channel_id yet. "
            "Edit config/omc.yaml and replace REPLACE_*_CHANNEL_ID values."
        )

    agent_prompts: dict[str, str] = {}
    for role in sorted(all_roles):
        if role in ROLE_FILES:
            agent_prompts[role] = load_agent_prompt(agents_dir, role)

    agent_routes = _normalize_routes(raw.get("agent_routes") or raw.get("routes"))
    status_authority = _normalize_status_authority(raw.get("status_authority"))

    coding = raw.get("coding") or {}
    if not coding.get("workspace"):
        coding = {**coding, "workspace": os.environ.get("OMC_WORKSPACE", "")}

    adapter = get_adapter_type(raw)

    return {
        "topics": topics,
        "topic_by_channel_id": topic_by_channel_id,
        "agent_prompts": agent_prompts,
        "agent_routes": agent_routes,
        "status_authority": status_authority,
        "channel_names": channel_names,
        "channel_by_name": channel_by_name,
        "free_channels": set(channel_names.keys()),
        "coding": coding,
        "coding_aliases": set(CODING_ALIASES),
        "adapter": adapter,
        "tickets": raw.get("tickets", {"provider": "none"}),
        "agents_dir": str(agents_dir),
        "config_path": str(config_path),
        "raw": raw,
    }


def get_adapter_type(config: dict) -> str:
    """Return the active adapter type: 'discord', 'zulip', or 'slack'."""
    return os.environ.get(
        "OMC_ADAPTER",
        config.get("omc", {}).get("adapter", "discord"),
    )
