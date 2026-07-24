"""
Factory for coding backends and mention → backend resolution.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from core.coding.base import CodingBackend
from core.coding.claude import ClaudeBackend
from core.coding.cursor import CursorBackend
from core.coding.hermes import HermesBackend
from core.coding.opencode import OpenCodeBackend

logger = logging.getLogger(__name__)

# Mentions that should use a coding backend (vs Hermes persona chat)
CODING_MENTIONS = frozenset({"coder", "hermes", "claude", "cursor", "opencode"})


def _build_backend(key: str, cfg: dict[str, Any]) -> CodingBackend:
    backends = (cfg.get("backends") or {}) if cfg else {}
    entry = backends.get(key) or {}
    command = entry.get("command")

    if key == "hermes":
        return HermesBackend(
            command=command,
            session_prefix=entry.get("session_prefix", "omc-coder"),
        )
    if key == "claude":
        return ClaudeBackend(command=command)
    if key == "cursor":
        return CursorBackend(command=command)
    if key == "opencode":
        return OpenCodeBackend(command=command)
    raise ValueError(f"Unknown coding backend: {key}")


class CodingRegistry:
    """Resolve @Coder / @Claude / … to a CodingBackend instance."""

    def __init__(self, coding_cfg: dict[str, Any] | None = None):
        self.cfg = coding_cfg or {}
        self.default_key = (self.cfg.get("default") or "hermes").strip().lower()
        self.workspace = (self.cfg.get("workspace") or "").strip()
        aliases = self.cfg.get("aliases") or {
            "hermes": "hermes",
            "claude": "claude",
            "cursor": "cursor",
            "opencode": "opencode",
            "coder": None,
        }
        self.aliases: dict[str, Optional[str]] = {
            str(k).lower(): (None if v is None else str(v).lower())
            for k, v in aliases.items()
        }
        self._cache: dict[str, CodingBackend] = {}

    def is_coding_mention(self, role: str) -> bool:
        return role.lower() in CODING_MENTIONS

    def resolve_backend_key(self, mention: str) -> str:
        m = mention.lower().lstrip("@")
        if m not in self.aliases and m != "coder":
            # Direct backend name
            if m in ("hermes", "claude", "cursor", "opencode"):
                return m
            return self.default_key
        mapped = self.aliases.get(m, None)
        if mapped is None:
            return self.default_key
        return mapped

    def get_backend(self, mention: str) -> CodingBackend:
        key = self.resolve_backend_key(mention)
        if key not in self._cache:
            self._cache[key] = _build_backend(key, self.cfg)
            logger.info(f"Coding backend ready: {key}")
        return self._cache[key]

    def get_hermes(self) -> HermesBackend:
        """Persona agents (PM/SA/…) always use Hermes chat."""
        if "hermes" not in self._cache:
            backends = self.cfg.get("backends") or {}
            entry = backends.get("hermes") or {}
            self._cache["hermes"] = HermesBackend(
                command=entry.get("command"),
                session_prefix=entry.get("session_prefix", "omc"),
            )
        backend = self._cache["hermes"]
        assert isinstance(backend, HermesBackend)
        return backend


def create_coding_registry(coding_cfg: dict[str, Any] | None) -> CodingRegistry:
    return CodingRegistry(coding_cfg)
