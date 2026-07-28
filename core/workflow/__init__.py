"""Multi-active WorkflowRuntime pool."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from core.db import REPO_ROOT, get_db
from core.engines import get_engine
from core.memory import build_memory_store
from core.secrets import build_tracker_config
from core.task_manager import TaskManager
from core.tickets.factory import create_tracker
from core.workflow.repository import WorkflowRecord, WorkflowRepository

logger = logging.getLogger(__name__)


@dataclass
class WorkflowRuntime:
    workflow: WorkflowRecord
    memory: Any
    tickets: TaskManager
    agents_dir: Path

    def engine_for_agent(self, role_id: str):
        agent = next((a for a in self.workflow.agents if a.role_id == role_id), None)
        if agent and agent.kind == "coding":
            backend = agent.coding_backend or self.workflow.coding_default
            return get_engine(backend)
        engine_id = (
            (agent.reasoning_engine if agent and agent.reasoning_engine else None)
            or self.workflow.reasoning_engine
            or "hermes"
        )
        return get_engine(engine_id)

    def mention_map(self) -> dict[str, str]:
        return {a.mention.lower(): a.role_id for a in self.workflow.agents}

    def session_key(self, engine_id: str, channel: str, role: str) -> str:
        agent = next((a for a in self.workflow.agents if a.role_id == role), None)
        if agent and (agent.hermes_profile or "").strip():
            return agent.hermes_profile.strip()
        return f"{engine_id}-{self.workflow.id}-{channel}-{role}"


@dataclass
class WorkflowRuntimePool:
    repo: WorkflowRepository
    runtimes: dict[str, WorkflowRuntime] = field(default_factory=dict)
    channel_index: dict[tuple[str, str], str] = field(default_factory=dict)

    def reload(self) -> None:
        self.runtimes.clear()
        self.channel_index.clear()
        agents_dir = Path(
            self.repo.db.get_setting("agents_dir", str(REPO_ROOT / "agents"))
        )
        for wf in self.repo.list_active():
            mem_cfg = dict(wf.memory_config or {})
            # Namespace memory per workflow
            root = mem_cfg.get("root_folder") or "OMC"
            mem_cfg["root_folder"] = f"{root}/{wf.id}"
            if wf.memory_provider == "hermes" and not mem_cfg.get("path"):
                mem_cfg["path"] = str(Path.home() / ".hermes" / "omc" / "memory")
            if wf.memory_provider == "obsidian" and not mem_cfg.get("vault_path"):
                mem_cfg["vault_path"] = os.environ.get("OMC_OBSIDIAN_VAULT", "")

            memory = build_memory_store(wf.memory_provider, mem_cfg)
            if memory and hasattr(memory, "ensure_vault"):
                try:
                    memory.ensure_vault()
                except Exception as e:
                    logger.warning("Memory ensure failed for %s: %s", wf.id, e)

            active_trk = next((t for t in (wf.trackings or []) if t.is_active), None)
            track_cfg = build_tracker_config(
                wf.id,
                (active_trk.provider if active_trk else wf.tracking_provider),
                (active_trk.config if active_trk else wf.tracking_config),
                connection_id=(active_trk.id if active_trk else ""),
            )
            map_path = Path.home() / ".hermes" / "omc" / f"task_map_{wf.id}.json"
            # Tracker is available on runtime via create_tracker; TaskManager is local map
            _ = create_tracker(track_cfg)
            tickets = TaskManager(store_path=str(map_path))

            rt = WorkflowRuntime(
                workflow=wf,
                memory=memory,
                tickets=tickets,
                agents_dir=agents_dir,
            )
            self.runtimes[wf.id] = rt
            for ch in wf.channels:
                ext = (ch.external_id or "").strip()
                if ext and not ext.startswith("REPLACE_"):
                    key = (ch.platform, ext)
                    if key in self.channel_index and self.channel_index[key] != wf.id:
                        logger.error(
                            "Channel conflict at runtime: %s owned by %s and %s",
                            key,
                            self.channel_index[key],
                            wf.id,
                        )
                    self.channel_index[key] = wf.id

        logger.info(
            "WorkflowRuntimePool loaded %d active workflow(s)", len(self.runtimes)
        )

    def resolve(self, platform: str, channel_id: str) -> Optional[WorkflowRuntime]:
        wf_id = self.channel_index.get((platform, channel_id))
        if not wf_id:
            return None
        return self.runtimes.get(wf_id)

    def get(self, workflow_id: str) -> Optional[WorkflowRuntime]:
        return self.runtimes.get(workflow_id)


_pool: Optional[WorkflowRuntimePool] = None


def get_pool(db_path: Optional[str] = None) -> WorkflowRuntimePool:
    global _pool
    if _pool is None:
        db = get_db(db_path)
        repo = WorkflowRepository(db)
        repo.ensure_seeded()
        _pool = WorkflowRuntimePool(repo=repo)
        _pool.reload()
    return _pool


def reload_pool() -> WorkflowRuntimePool:
    pool = get_pool()
    pool.reload()
    return pool
