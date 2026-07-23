"""
Null ticket tracker — local TASK-NNN only, no external API.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import uuid4

from core.tickets.base import TicketRef, TicketTracker
from core.tickets.status import SdlcStatus

logger = logging.getLogger(__name__)


class NullTracker(TicketTracker):
    """No-op external tracker; returns synthetic ids for local mapping."""

    async def create_issue(
        self,
        name: str,
        description: str = "",
        status: SdlcStatus = SdlcStatus.BACKLOG,
    ) -> Optional[TicketRef]:
        external_id = str(uuid4())
        logger.info(f"NullTracker: created local ticket {name!r} ({status.display})")
        return TicketRef(
            external_id=external_id,
            url="",
            key="",
            name=name,
        )

    async def update_status(self, external_id: str, status: SdlcStatus) -> bool:
        logger.info(f"NullTracker: would update {external_id[:8]} → {status.display}")
        return True
