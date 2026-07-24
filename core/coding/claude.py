"""Claude Code CLI backend."""

from __future__ import annotations

from typing import Optional, Sequence

from core.coding.base import CodingBackend
from core.coding.cli_runner import run_command, which


class ClaudeBackend(CodingBackend):
    name = "claude"

    def __init__(self, command: Optional[Sequence[str]] = None, timeout: float = 600):
        self.command = list(command or ["claude", "-p", "--output-format", "text"])
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
                "Claude Code CLI not found on PATH. Install `claude` or update coding.backends.claude.command."
            )
        return await run_command(
            self.command,
            prompt=prompt,
            cwd=workspace or None,
            timeout=self.timeout,
            pass_prompt_as_arg=True,
        )
