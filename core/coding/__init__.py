"""Pluggable coding agent backends (Hermes, Claude Code, Cursor, OpenCode)."""

from core.coding.base import CodingBackend
from core.coding.factory import CODING_MENTIONS, CodingRegistry, create_coding_registry

__all__ = [
    "CodingBackend",
    "CodingRegistry",
    "CODING_MENTIONS",
    "create_coding_registry",
]
