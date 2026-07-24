"""
Shared CLI runner helpers for coding backends.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Optional, Sequence

logger = logging.getLogger(__name__)


def which(binary: str) -> Optional[str]:
    return shutil.which(binary)


async def run_command(
    command: Sequence[str],
    *,
    prompt: str,
    cwd: Optional[str] = None,
    timeout: float = 600,
    pass_prompt_as_arg: bool = True,
) -> str:
    """
    Spawn a subprocess. If pass_prompt_as_arg, append prompt as the last argv
    entry; otherwise write prompt to stdin.
    """
    if not command:
        raise RuntimeError("Empty command")

    cmd = list(command)
    stdin = None
    if pass_prompt_as_arg:
        cmd = cmd + [prompt]
    else:
        stdin = asyncio.subprocess.PIPE

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd or None,
            stdin=stdin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"CLI not found: {cmd[0]}") from e

    try:
        if stdin is not None:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")),
                timeout=timeout,
            )
        else:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as e:
        proc.kill()
        raise RuntimeError(f"Command timed out after {timeout}s: {cmd[0]}") from e

    out = (stdout or b"").decode("utf-8", errors="replace").strip()
    err = (stderr or b"").decode("utf-8", errors="replace").strip()
    if proc.returncode not in (0, None) and not out:
        raise RuntimeError(err or f"{cmd[0]} exited with {proc.returncode}")
    if err:
        logger.debug(f"{cmd[0]} stderr: {err[:300]}")
    return out or err
