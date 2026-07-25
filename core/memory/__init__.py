"""MemoryStore protocol and providers (hermes | obsidian | none)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from core.memory.obsidian import ObsidianMemoryStore, create_memory_store

logger = logging.getLogger(__name__)


@runtime_checkable
class MemoryStore(Protocol):
    def ensure_vault(self) -> None: ...

    def health(self) -> dict[str, Any]: ...

    def list_tasks(self) -> list[dict[str, Any]]: ...

    def get_task(self, task_id: str) -> Optional[dict[str, Any]]: ...

    def upsert_task(self, task_id: str, **kwargs: Any) -> Path: ...

    def append_agent_note(
        self, task_id: str, role: str, backend: str, text: str
    ) -> None: ...

    def append_handoff(
        self, task_id: str, from_role: str, to_role: str, message: str
    ) -> None: ...

    def build_context_prompt(self, task_id: str, max_chars: int = 3500) -> str: ...


class HermesMemoryStore(ObsidianMemoryStore):
    """
    Hermes-local markdown memory — same note format as Obsidian,
    stored under ~/.hermes/omc/memory (or configured path).
    """

    def __init__(self, path: str, root_folder: str = "OMC"):
        super().__init__(vault_path=path, root_folder=root_folder)

    def health(self) -> dict[str, Any]:
        base = super().health()
        base["provider"] = "hermes"
        return base


def build_memory_store(
    provider: str, config: dict[str, Any] | None = None
) -> Optional[MemoryStore]:
    cfg = config or {}
    p = (provider or "none").strip().lower()
    if p in ("none", "off", ""):
        return None
    if p == "hermes":
        path = (cfg.get("path") or str(Path.home() / ".hermes" / "omc" / "memory")).strip()
        store = HermesMemoryStore(
            path=path,
            root_folder=cfg.get("root_folder") or "OMC",
        )
        try:
            store.ensure_vault()
        except Exception as e:
            logger.error("Failed to init Hermes memory: %s", e)
            return None
        return store
    if p == "obsidian":
        vault = (cfg.get("vault_path") or "").strip()
        if not vault:
            logger.warning("obsidian vault_path empty — memory disabled")
            return None
        store = ObsidianMemoryStore(
            vault_path=vault,
            root_folder=cfg.get("root_folder") or "OMC",
        )
        try:
            store.ensure_vault()
        except Exception as e:
            logger.error("Failed to init Obsidian memory: %s", e)
            return None
        h = store.health()
        h["provider"] = "obsidian"
        return store
    logger.warning("Unknown memory provider '%s'", p)
    return None


__all__ = [
    "MemoryStore",
    "HermesMemoryStore",
    "ObsidianMemoryStore",
    "build_memory_store",
    "create_memory_store",
]
