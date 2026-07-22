"""
Configuration Loader
=====================
Loads agent prompts, channel config, and adapter settings.
Centralised so all adapters share the same config schema.
"""

import os
from pathlib import Path
from typing import Any

import yaml


def load_config(path: str = "~/.hermes/config.yaml") -> dict:
    """Load the Hermes config.yaml and extract Discord/agent settings."""
    config_path = Path(path).expanduser()
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    discord_cfg = raw.get("discord", {})
    channel_prompts = discord_cfg.get("channel_prompts", {})

    # Channel name registry from config or environment
    channel_names = {
        "1528310140564934708": "#pm",
        "1528310312317751376": "#sa",
        "1528310344164835389": "#coder",
        "1528310424536354866": "#qa",
        "1528310499773648968": "#marketing",
        "1528336812177883167": "#summary",
    }
    channel_by_name = {v: k for k, v in channel_names.items()}

    # Agent routes
    agent_routes = {
        "#pm": ["#sa", "#marketing"],
        "#sa": ["#coder", "#qa"],
        "#coder": ["#qa", "#sa"],
        "#qa": ["#sa", "#coder"],
        "#marketing": ["#pm"],
    }

    free_channels_str = discord_cfg.get("free_response_channels", "")
    free_channels = set(c.strip() for c in free_channels_str.split(",") if c.strip())

    adapter = get_adapter_type(raw)

    return {
        "channel_prompts": channel_prompts,
        "channel_names": channel_names,
        "channel_by_name": channel_by_name,
        "agent_routes": agent_routes,
        "free_channels": free_channels,
        "adapter": adapter,
        "raw": raw,
    }


def get_adapter_type(config: dict) -> str:
    """Return the active adapter type: 'discord', 'zulip', or 'slack'."""
    return os.environ.get("OMC_ADAPTER", config.get("omc", {}).get("adapter", "discord"))
