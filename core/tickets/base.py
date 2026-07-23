"""
TicketTracker — abstract interface for project-management backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from core.tickets.status import SdlcStatus, detect_status


@dataclass
class TicketRef:
    """Provider-neutral ticket reference."""

    external_id: str
    url: str
    key: str = ""
    name: str = ""


class TicketTracker(ABC):
    """Create issues and update SDLC status in an external PM tool."""

    @abstractmethod
    async def create_issue(
        self,
        name: str,
        description: str = "",
        status: SdlcStatus = SdlcStatus.BACKLOG,
    ) -> Optional[TicketRef]:
        ...

    @abstractmethod
    async def update_status(self, external_id: str, status: SdlcStatus) -> bool:
        ...

    def detect_status(self, text: str) -> Optional[SdlcStatus]:
        return detect_status(text)

    def get_url(self, external_id: str) -> str:
        """Optional helper; providers may override."""
        return ""
