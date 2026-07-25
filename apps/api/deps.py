"""Shared paths and helpers for the Agentic OS API."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def config_path() -> Path:
    env = os.environ.get("OMC_CONFIG")
    if env:
        return Path(env).expanduser()
    return REPO_ROOT / "config" / "omc.yaml"


def agents_dir() -> Path:
    return REPO_ROOT / "agents"


def secrets_env_path() -> Path:
    return Path(os.environ.get("OMC_SECRETS_ENV", "~/.hermes/omc/secrets.env")).expanduser()


def task_map_path(store: str | None = None) -> Path:
    raw = store or "~/.hermes/omc/task_map.json"
    return Path(raw).expanduser()
