"""Hermes CLI coding / persona backend."""

from __future__ import annotations

import os
import re
from typing import Optional, Sequence

from core.coding.base import CodingBackend
from core.coding.cli_runner import which


class HermesBackend(CodingBackend):
    """Invoke `hermes -z` with optional --resume session."""

    name = "hermes"

    def __init__(
        self,
        command: Optional[Sequence[str]] = None,
        session_prefix: str = "omc",
        timeout: float = 600,
    ):
        self.command = list(command or ["hermes", "-z"])
        self.session_prefix = session_prefix
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
                "Hermes CLI not found on PATH. Install hermes or fix coding.backends.hermes.command."
            )
        session = session_key or profile or f"{self.session_prefix}-default"
        # Prefer explicit -p so the CLI uses the synced OMC profile (SOUL.md / .env).
        full_cmd = [self.command[0]]
        if profile:
            full_cmd.extend(["-p", profile])
        full_cmd.extend(["-z", prompt, "--resume", session, "--safe-mode", "--yolo"])

        env = os.environ.copy()
        if profile:
            env["HERMES_PROFILE"] = profile
        if model:
            env["HERMES_MODEL"] = model

        import asyncio

        try:
            proc = await asyncio.create_subprocess_exec(
                *full_cmd,
                cwd=workspace or None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError as e:
            raise RuntimeError("Hermes CLI not found on PATH.") from e

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError as e:
            proc.kill()
            raise RuntimeError("Hermes timed out") from e

        response = (stdout or b"").decode("utf-8", errors="replace").strip()
        return self._clean_response(response)

    @staticmethod
    def _clean_response(response: str) -> str:
        lines = response.split("\n")
        clean = []
        for l in lines:
            s = l.strip()
            if not s:
                clean.append("")
            elif any(
                s.startswith(c)
                for c in (
                    "╭", "╰", "│", "─", "⚠", "✦", "●", "┃", "┣", "┗",
                    "┏", "┓", "┛", "┳", "┻", "┫", "━",
                )
            ):
                continue
            elif re.match(r"^[\d:.,\s\-]+$", s):
                continue
            else:
                clean.append(s)
        result = "\n".join(clean).strip()
        if not result or len(result) < 5:
            meaningful = [
                l
                for l in lines
                if len(l.strip()) > 10 and not l.strip().startswith("Hermes")
            ]
            result = meaningful[-1].strip() if meaningful else response[:1900]
        return result
