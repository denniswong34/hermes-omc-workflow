"""Pluggable reasoning engines — shared by persona roles and coding backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional, Sequence

from core.coding.base import CodingBackend
from core.coding.claude import ClaudeBackend
from core.coding.codex import CodexBackend
from core.coding.cursor import CursorBackend
from core.coding.hermes import HermesBackend
from core.coding.opencode import OpenCodeBackend

ENGINE_IDS = ("hermes", "claude", "cursor", "opencode", "codex")


class ReasoningEngine(ABC):
    """Execute one agent turn (persona or coding)."""

    id: str = "base"

    @abstractmethod
    async def run(
        self,
        prompt: str,
        *,
        workspace: str = "",
        session_key: str = "",
        mcp_configs: Optional[list[dict[str, Any]]] = None,
    ) -> str:
        ...

    def available(self) -> bool:
        return True


class CodingEngineAdapter(ReasoningEngine):
    """Wrap an existing CodingBackend as a ReasoningEngine."""

    def __init__(self, backend: CodingBackend, engine_id: str | None = None):
        self.backend = backend
        self.id = engine_id or backend.name

    def available(self) -> bool:
        return self.backend.available()

    async def run(
        self,
        prompt: str,
        *,
        workspace: str = "",
        session_key: str = "",
        mcp_configs: Optional[list[dict[str, Any]]] = None,
    ) -> str:
        # MCP: prefer tool-proxy injection into prompt when configs present
        final_prompt = prompt
        if mcp_configs:
            from core.mcp.proxy import inject_mcp_tool_hints

            final_prompt = inject_mcp_tool_hints(prompt, mcp_configs)
        return await self.backend.run(
            final_prompt, workspace=workspace, session_key=session_key
        )


def _build_backend(engine_id: str, command: Optional[Sequence[str]] = None) -> CodingBackend:
    if engine_id == "hermes":
        return HermesBackend(command=command)
    if engine_id == "claude":
        return ClaudeBackend(command=command)
    if engine_id == "cursor":
        return CursorBackend(command=command)
    if engine_id == "opencode":
        return OpenCodeBackend(command=command)
    if engine_id == "codex":
        return CodexBackend(command=command)
    raise ValueError(f"Unknown engine: {engine_id}")


_cache: dict[str, ReasoningEngine] = {}


def get_engine(engine_id: str, command: Optional[Sequence[str]] = None) -> ReasoningEngine:
    key = (engine_id or "hermes").strip().lower()
    if key not in ENGINE_IDS:
        key = "hermes"
    if key not in _cache or command is not None:
        _cache[key] = CodingEngineAdapter(_build_backend(key, command), key)
    return _cache[key]


def list_engines() -> list[dict[str, Any]]:
    out = []
    for eid in ENGINE_IDS:
        eng = get_engine(eid)
        out.append({"id": eid, "available": eng.available()})
    return out
