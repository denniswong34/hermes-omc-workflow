"""OpenAI Codex CLI coding backend."""

from __future__ import annotations

from typing import Optional, Sequence

from core.coding.base import CodingBackend
from core.coding.cli_runner import run_command, which


class CodexBackend(CodingBackend):
    """Invoke OpenAI Codex CLI (`codex exec` by default)."""

    name = "codex"

    def __init__(self, command: Optional[Sequence[str]] = None, timeout: float = 600):
        self.command = list(command or ["codex", "exec"])
        self.timeout = timeout

    def available(self) -> bool:
        return which(self.command[0]) is not None

    async def run(
        self,
        prompt: str,
        *,
        workspace: str = "",
        session_key: str = "",
        profile: str = "",
        model: str = "",
    ) -> str:
        if not self.available():
            raise RuntimeError(
                "Codex CLI not found on PATH. Install `codex` "
                "or update coding.backends.codex.command."
            )
        return await run_command(
            self.command,
            prompt=prompt,
            cwd=workspace or None,
            timeout=self.timeout,
            pass_prompt_as_arg=True,
        )
