"""
SDLC Tracker — status detection + authority checks + ticket updates.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.tickets.base import TicketTracker
from core.tickets.status import SdlcStatus, detect_status

logger = logging.getLogger(__name__)


class SDLCTracker:
    """Applies detected status keywords to the configured ticket backend."""

    def __init__(
        self,
        tracker: Optional[TicketTracker] = None,
        status_authority: Optional[dict[str, list[str]]] = None,
    ):
        self.tracker = tracker
        self.status_authority = status_authority or {}

    def detect_status(self, text: str) -> Optional[SdlcStatus]:
        return detect_status(text)

    def allowed_for_role(self, role: str, status: SdlcStatus) -> bool:
        """Return True if this agent role may update the board to `status`."""
        key = (role or "").strip().lstrip("#@").lower()
        allowed = self.status_authority.get(key)
        if allowed is None:
            # Legacy: also try #role
            allowed = self.status_authority.get(f"#{key}")
        if allowed is None:
            return True  # no policy configured → allow
        display = status.display
        return display in allowed or status.value in allowed

    def allowed_for_channel(self, channel_name: str, status: SdlcStatus) -> bool:
        """Backward-compatible alias — prefer allowed_for_role."""
        return self.allowed_for_role(channel_name, status)

    async def update_status(self, external_id: str, status: SdlcStatus) -> bool:
        if self.tracker is None:
            logger.warning(f"SDLC: Would update {external_id} → {status.display} (no tracker)")
            return False
        try:
            return await self.tracker.update_status(external_id, status)
        except Exception as e:
            logger.error(f"SDLC update failed: {e}")
            return False
