"""Cursor agent CLI backend."""

from __future__ import annotations

from typing import Optional, Sequence

from core.coding.base import CodingBackend
from core.coding.cli_runner import run_command, which


class CursorBackend(CodingBackend):
    name = "cursor"

    def __init__(self, command: Optional[Sequence[str]] = None, timeout: float = 600):
        # Cursor Agent CLI is commonly `agent`; override in config if needed
        self.command = list(command or ["agent"])
        self.timeout = timeout

    def available(self) -> bool:
        return which(self.command[0]) is not None

    async def run(
        self,
        prompt: str,
        *,
        workspace: str = "",
        session_key: str = "",
    ) -> str:
        if not self.available():
            raise RuntimeError(
                "Cursor agent CLI not found on PATH. Install Cursor CLI (`agent`) "
                "or update coding.backends.cursor.command."
            )
        return await run_command(
            self.command,
            prompt=prompt,
            cwd=workspace or None,
            timeout=self.timeout,
            pass_prompt_as_arg=True,
        )
