"""Ticket tracking package — pluggable Plane / Jira / none backends."""

from core.tickets.base import TicketRef, TicketTracker
from core.tickets.factory import create_tracker
from core.tickets.status import SdlcStatus, detect_status

__all__ = [
    "TicketRef",
    "TicketTracker",
    "SdlcStatus",
    "detect_status",
    "create_tracker",
]
