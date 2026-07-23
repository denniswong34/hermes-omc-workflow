"""
Task Manager — TASK-NNN ↔ external ticket mapping
===================================================
Persistent JSON store mapping Hermes task IDs to provider-neutral ticket refs.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from core.tickets.status import SdlcStatus, detect_status

logger = logging.getLogger(__name__)


class TaskManager:
    """Manages TASK-NNN ↔ external ticket mapping with persistent JSON storage."""

    def __init__(self, store_path: str = "~/.hermes/omc/task_map.json"):
        self.path = Path(store_path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}
        self._current_num = int(self._data.get("_next_num", 0))
        # Migrate legacy plane_issue_id → external_id
        for key, val in list(self._data.items()):
            if key.startswith("_") or not isinstance(val, dict):
                continue
            if "external_id" not in val and "plane_issue_id" in val:
                val["external_id"] = val["plane_issue_id"]

    def _save(self):
        self._data["_next_num"] = self._current_num
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def next_task_id(self) -> str:
        self._current_num += 1
        self._save()
        return f"TASK-{self._current_num:03d}"

    def next_task_number(self) -> int:
        """Backward-compatible: allocate and return the next numeric id."""
        self._current_num += 1
        self._save()
        return self._current_num

    def set_task(
        self,
        task_id: str,
        external_id: str,
        url: str = "",
        key: str = "",
        name: str = "",
        provider: str = "",
    ):
        self._data[task_id] = {
            "external_id": external_id,
            "url": url,
            "key": key,
            "name": name,
            "provider": provider,
        }
        self._save()

    def task_exists(self, task_id: str) -> bool:
        return task_id in self._data

    def get_task(self, task_id: str) -> Optional[dict]:
        return self._data.get(task_id)

    @staticmethod
    def guess_task_reference(text: str) -> Optional[str]:
        """Extract TASK-NNN from text if present."""
        m = re.search(r"TASK-(\d{3,})", text, re.IGNORECASE)
        if m:
            return f"TASK-{m.group(1)}"
        return None

    @staticmethod
    def find_status_in_text(text: str) -> Optional[str]:
        """Detect SDLC status keyword; returns display form or None."""
        status = detect_status(text)
        return status.display if status else None

    @staticmethod
    def find_sdlc_status(text: str) -> Optional[SdlcStatus]:
        return detect_status(text)
