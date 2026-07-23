"""
Factory for TicketTracker implementations.
"""

from __future__ import annotations

import logging
from typing import Any

from core.tickets.base import TicketTracker
from core.tickets.jira import JiraTracker
from core.tickets.null import NullTracker
from core.tickets.plane import PlaneTracker

logger = logging.getLogger(__name__)


def create_tracker(tickets_cfg: dict[str, Any] | None) -> TicketTracker:
    """Build a TicketTracker from the `tickets:` config block."""
    cfg = tickets_cfg or {}
    provider = (cfg.get("provider") or "none").strip().lower()

    if provider in ("none", "null", "off", ""):
        logger.info("Ticket tracker: none (local TASK ids only)")
        return NullTracker()

    if provider == "plane":
        plane = cfg.get("plane") or {}
        base_url = (plane.get("base_url") or "").strip()
        workspace = (plane.get("workspace") or "").strip()
        project_id = (plane.get("project_id") or "").strip()
        api_key = (plane.get("api_key") or plane.get("api_key_or_session") or "").strip()
        if not base_url or not workspace or not project_id:
            logger.warning("Plane config incomplete — falling back to NullTracker")
            return NullTracker()
        logger.info(f"Ticket tracker: plane ({workspace}/{project_id})")
        return PlaneTracker(
            base_url=base_url,
            workspace=workspace,
            project_id=project_id,
            api_key=api_key,
            status_map=plane.get("status_map") or {},
        )

    if provider == "jira":
        jira = cfg.get("jira") or {}
        base_url = (jira.get("base_url") or "").strip()
        email = (jira.get("email") or "").strip()
        api_token = (jira.get("api_token") or "").strip()
        project_key = (jira.get("project_key") or "").strip()
        if not base_url or not email or not api_token or not project_key:
            logger.warning("Jira config incomplete — falling back to NullTracker")
            return NullTracker()
        logger.info(f"Ticket tracker: jira ({project_key})")
        return JiraTracker(
            base_url=base_url,
            email=email,
            api_token=api_token,
            project_key=project_key,
            status_map=jira.get("status_map") or {},
        )

    logger.warning(f"Unknown ticket provider '{provider}' — using NullTracker")
    return NullTracker()
