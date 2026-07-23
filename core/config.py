"""
Configuration Loader
=====================
Loads OMC channels, agent personas from agents/, routes, and ticket settings.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_ROUTES = {
    "#pm": ["#sa", "#devops", "#marketing"],
    "#sa": ["#pm", "#coder", "#qa"],
    "#coder": ["#sa", "#qa", "#devops"],
    "#qa": ["#sa", "#coder", "#devops"],
    "#devops": ["#pm", "#coder", "#qa"],
    "#marketing": ["#pm"],
}

DEFAULT_STATUS_AUTHORITY = {
    "#pm": ["backlog", "todo", "done", "cancelled"],
    "#sa": ["todo", "in progress"],
    "#coder": ["in progress", "in review"],
    "#qa": ["qa review", "qa failed", "qa verified", "ready to deploy"],
    "#devops": ["ready to deploy", "deployed"],
    "#marketing": [],
}

ROLE_FILES = {
    "pm": "pm.md",
    "sa": "sa.md",
    "coder": "coder.md",
    "qa": "qa.md",
    "devops": "devops.md",
    "marketing": "marketing.md",
}

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


def load_config(path: str | None = None) -> dict:
    """Load OMC config and build channel prompts from agents/."""
    config_path = _resolve_config_path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    raw = _expand_env(raw)
    omc = raw.get("omc", {})
    channels = raw.get("channels", {})
    if not channels:
        raise ValueError("config.channels is required (role → channel id map)")

    agents_dir_cfg = omc.get("agents_dir", "agents")
    agents_dir = Path(agents_dir_cfg)
    if not agents_dir.is_absolute():
        agents_dir = (REPO_ROOT / agents_dir).resolve()

    channel_names: dict[str, str] = {}
    channel_prompts: dict[str, str] = {}
    for role, channel_id in channels.items():
        cid = str(channel_id).strip()
        if not cid or cid.startswith("REPLACE_"):
            # Allow missing devops id during setup; skip prompt until configured
            if role == "devops":
                continue
            raise ValueError(f"Invalid channel id for role '{role}': {channel_id}")
        name = f"#{role}"
        channel_names[cid] = name
        channel_prompts[cid] = load_agent_prompt(agents_dir, role)

    channel_by_name = {v: k for k, v in channel_names.items()}
    agent_routes = raw.get("routes") or DEFAULT_ROUTES
    # Drop routes to channels that are not configured
    filtered_routes: dict[str, list[str]] = {}
    for src, targets in agent_routes.items():
        if src not in channel_by_name:
            continue
        filtered_routes[src] = [t for t in targets if t in channel_by_name]

    status_authority = raw.get("status_authority") or DEFAULT_STATUS_AUTHORITY
    free_channels = set(channel_names.keys())

    adapter = get_adapter_type(raw)

    return {
        "channel_prompts": channel_prompts,
        "channel_names": channel_names,
        "channel_by_name": channel_by_name,
        "agent_routes": filtered_routes,
        "status_authority": status_authority,
        "free_channels": free_channels,
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
