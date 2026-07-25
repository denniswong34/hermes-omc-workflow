"""
Obsidian vault memory — shared TASK context across coding backends.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_note(text: str) -> tuple[dict[str, Any], str]:
    m = FRONTMATTER_RE.match(text.strip())
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
        if not isinstance(meta, dict):
            meta = {}
    except Exception:
        meta = {}
    return meta, m.group(2)


def _dump_note(meta: dict[str, Any], body: str) -> str:
    fm = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
    body = body.lstrip("\n")
    return f"---\n{fm}\n---\n\n{body.rstrip()}\n"


class ObsidianMemoryStore:
    """Markdown task notes in an Obsidian vault folder."""

    def __init__(self, vault_path: str, root_folder: str = "OMC"):
        self.vault_path = Path(vault_path).expanduser()
        self.root_folder = root_folder.strip() or "OMC"
        self.root = self.vault_path / self.root_folder

    @property
    def tasks_dir(self) -> Path:
        return self.root / "tasks"

    @property
    def handoffs_dir(self) -> Path:
        return self.root / "handoffs"

    @property
    def agents_dir(self) -> Path:
        return self.root / "agents"

    @property
    def decisions_dir(self) -> Path:
        return self.root / "decisions"

    @property
    def daily_dir(self) -> Path:
        return self.root / "daily"

    def ensure_vault(self) -> None:
        if not str(self.vault_path).strip():
            raise ValueError("Obsidian vault_path is empty")
        self.vault_path.mkdir(parents=True, exist_ok=True)
        for d in (
            self.tasks_dir,
            self.handoffs_dir,
            self.agents_dir,
            self.decisions_dir,
            self.daily_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)
        index = self.root / "_index.md"
        if not index.exists():
            index.write_text(
                "# OMC Memory\n\n"
                "- [[tasks/]] — TASK notes (shared across coding agents)\n"
                "- [[handoffs/]] — latest handoff packets\n"
                "- [[decisions/]] — ADRs\n"
                "- [[daily/]] — standup digests\n",
                encoding="utf-8",
            )
        logger.info(f"Obsidian vault ready: {self.root}")

    def health(self) -> dict[str, Any]:
        ok = self.vault_path.exists() and self.root.exists()
        return {
            "ok": ok,
            "vault_path": str(self.vault_path),
            "root": str(self.root),
            "tasks": len(list(self.tasks_dir.glob("TASK-*.md")))
            if self.tasks_dir.exists()
            else 0,
        }

    def task_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id.upper()}.md"

    def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        path = self.task_path(task_id)
        if not path.exists():
            return None
        meta, body = _parse_note(path.read_text(encoding="utf-8"))
        return {"meta": meta, "body": body, "path": str(path)}

    def list_tasks(self) -> list[dict[str, Any]]:
        if not self.tasks_dir.exists():
            return []
        out = []
        for path in sorted(self.tasks_dir.glob("TASK-*.md")):
            meta, body = _parse_note(path.read_text(encoding="utf-8"))
            title = ""
            for line in body.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            out.append(
                {
                    "task_id": meta.get("task_id") or path.stem,
                    "status": meta.get("status", "backlog"),
                    "topic": meta.get("topic", ""),
                    "assignee": meta.get("assignee", ""),
                    "backend": meta.get("backend", ""),
                    "ticket_url": meta.get("ticket_url", ""),
                    "updated": meta.get("updated", ""),
                    "title": title,
                    "path": str(path),
                }
            )
        return out

    def upsert_task(
        self,
        task_id: str,
        *,
        title: str = "",
        status: str = "",
        topic: str = "",
        assignee: str = "",
        backend: str = "",
        ticket_url: str = "",
        goal: str = "",
        merge_body: bool = True,
    ) -> Path:
        self.ensure_vault()
        path = self.task_path(task_id)
        meta: dict[str, Any] = {}
        body = ""
        if path.exists() and merge_body:
            meta, body = _parse_note(path.read_text(encoding="utf-8"))

        meta["task_id"] = task_id.upper()
        if status:
            meta["status"] = status
        if topic:
            meta["topic"] = topic
        if assignee:
            meta["assignee"] = assignee
        if backend:
            meta["backend"] = backend
        if ticket_url:
            meta["ticket_url"] = ticket_url
        meta["updated"] = _now_iso()

        if not body.strip():
            heading = title or task_id.upper()
            body = (
                f"# {heading}\n\n"
                f"## Goal\n{goal or '_TBD_'}\n\n"
                "## Spec\n\n"
                "## Acceptance criteria\n\n"
                "## Implementation notes\n\n"
                "## Handoff log\n"
            )
        elif goal and "## Goal" in body and "_TBD_" in body:
            body = body.replace("_TBD_", goal[:500], 1)

        path.write_text(_dump_note(meta, body), encoding="utf-8")
        return path

    def append_agent_note(
        self, task_id: str, role: str, backend: str, text: str
    ) -> None:
        self.ensure_vault()
        path = self.task_path(task_id)
        if not path.exists():
            self.upsert_task(task_id, assignee=role, backend=backend)
        meta, body = _parse_note(path.read_text(encoding="utf-8"))
        stamp = _now_iso()
        snippet = (text or "").strip()[:1500]
        block = f"\n### {stamp} — @{role}" + (f" ({backend})" if backend else "") + f"\n{snippet}\n"
        marker = "## Implementation notes"
        if marker in body:
            parts = body.split(marker, 1)
            rest = parts[1]
            # insert after heading line
            if rest.startswith("\n"):
                body = parts[0] + marker + "\n" + block + rest.lstrip("\n")
            else:
                body = parts[0] + marker + block + rest
        else:
            body = body.rstrip() + f"\n\n{marker}\n{block}"
        meta["updated"] = stamp
        if role:
            meta["assignee"] = role
        if backend:
            meta["backend"] = backend
        path.write_text(_dump_note(meta, body), encoding="utf-8")

    def append_handoff(
        self, task_id: str, from_role: str, to_role: str, message: str
    ) -> None:
        self.ensure_vault()
        path = self.task_path(task_id)
        if not path.exists():
            self.upsert_task(task_id, assignee=to_role)
        meta, body = _parse_note(path.read_text(encoding="utf-8"))
        stamp = _now_iso()
        line = f"- {stamp} @{from_role} → @{to_role}: {(message or '')[:300]}"
        marker = "## Handoff log"
        if marker in body:
            body = body.rstrip() + f"\n{line}\n"
        else:
            body = body.rstrip() + f"\n\n{marker}\n{line}\n"
        meta["updated"] = stamp
        meta["assignee"] = to_role
        path.write_text(_dump_note(meta, body), encoding="utf-8")

        # Latest handoff packet
        packet = self.handoffs_dir / f"{task_id.upper()}-latest.md"
        packet.write_text(
            f"# Handoff {task_id.upper()}\n\n"
            f"**From:** @{from_role}  \n**To:** @{to_role}  \n**At:** {stamp}\n\n"
            f"{message}\n",
            encoding="utf-8",
        )

    def build_context_prompt(self, task_id: str, max_chars: int = 3500) -> str:
        note = self.get_task(task_id)
        if not note:
            return ""
        meta = note["meta"]
        body = note["body"]
        header = (
            f"task_id={meta.get('task_id', task_id)} "
            f"status={meta.get('status', '')} "
            f"assignee={meta.get('assignee', '')} "
            f"backend={meta.get('backend', '')}"
        )
        text = f"{header}\n\n{body}".strip()
        if len(text) > max_chars:
            text = text[: max_chars - 20] + "\n…(truncated)"
        return text


def create_memory_store(memory_cfg: dict[str, Any] | None) -> Optional[ObsidianMemoryStore]:
    """Build store from config `memory:` block, or None."""
    cfg = memory_cfg or {}
    provider = (cfg.get("provider") or "none").strip().lower()
    if provider in ("none", "off", ""):
        return None
    if provider != "obsidian":
        logger.warning(f"Unknown memory provider '{provider}' — disabled")
        return None
    obs = cfg.get("obsidian") or {}
    vault = (obs.get("vault_path") or "").strip()
    if not vault:
        logger.warning("memory.obsidian.vault_path empty — memory disabled")
        return None
    store = ObsidianMemoryStore(
        vault_path=vault,
        root_folder=obs.get("root_folder") or "OMC",
    )
    try:
        store.ensure_vault()
    except Exception as e:
        logger.error(f"Failed to init Obsidian vault: {e}")
        return None
    return store
