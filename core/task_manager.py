"""
Task Manager — TASK-NNN ↔ Plane.so Issue Mapping
==================================================
Persistent JSON store that maps Hermes task IDs to Plane.so issue IDs.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional


class TaskManager:
    """Manages TASK-NNN ↔ Plane issue mapping with persistent JSON storage."""

    def __init__(self, store_path: str = "~/.hermes/discord-bridge/task_map.json"):
        self.path = Path(store_path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except Exception:
                self._data = {}
        self._current_num = self._data.get("_next_num", 0)

    def _save(self):
        self._data["_next_num"] = self._current_num
        self.path.write_text(json.dumps(self._data, indent=2))

    def next_task_number(self) -> int:
        self._current_num += 1
        return self._current_num

    def set_task(self, task_id: str, plane_issue_id: str, seq_id: str, url: str, name: str = ""):
        self._data[task_id] = {
            "plane_issue_id": plane_issue_id,
            "seq_id": seq_id,
            "url": url,
            "name": name,
        }
        self._save()

    def task_exists(self, task_id: str) -> bool:
        return task_id in self._data

    def get_task(self, task_id: str) -> Optional[dict]:
        return self._data.get(task_id)

    @staticmethod
    def guess_task_reference(text: str) -> Optional[str]:
        """Extract TASK-NNN from text if present."""
        m = re.search(r"TASK-(\d{3})", text, re.IGNORECASE)
        if m:
            return f"TASK-{m.group(1)}"
        return None

    @staticmethod
    def find_status_in_text(text: str) -> Optional[str]:
        """Detect SDLC status keyword in text."""
        for kw in ["todo", "in progress", "in review", "qa verified",
                   "qa failed", "done", "backlog", "qa review"]:
            if kw in text.lower():
                return kw
        return None
