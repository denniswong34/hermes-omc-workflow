"""
CodingBackend — abstract interface for implementation agents.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class CodingBackend(ABC):
    """Run a coding agent against a workspace and return text output."""

    name: str = "base"

    @abstractmethod
    async def run(
        self,
        prompt: str,
        *,
        workspace: str = "",
        session_key: str = "",
    ) -> str:
        """Execute the coding agent. Raises RuntimeError on hard failure."""
        ...

    def available(self) -> bool:
        """Return True if the CLI/binary appears runnable."""
        return True
