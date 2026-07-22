"""
SDLC Tracker — Plane.so State Machine Integration
===================================================
Detects status keywords in agent text and updates Plane.so issue states.
"""

import logging
from typing import Optional


# Map of status keywords → Plane.so state identifiers
STATUS_KEYWORDS = {
    # Workflow start
    "todo": "bca3dcca-3f5a-4cca-89a9-96a70f701368",
    "backlog": "bdb9eea6-3f5a-4cca-89a9-96a70f701368",
    "in progress": "42be09bb-3f5a-4cca-89a9-96a70f701368",
    "in review": "1fee841b-3f5a-4cca-89a9-96a70f701368",
    # QA states
    "qa review": "1fee841b-3f5a-4cca-89a9-96a70f701368",
    "qa failed": "d30da6bc-3f5a-4cca-89a9-96a70f701368",
    "rework": "d30da6bc-3f5a-4cca-89a9-96a70f701368",
    "qa verified": "fe3d8d0a-3f5a-4cca-89a9-96a70f701368",
    "qa passed": "fe3d8d0a-3f5a-4cca-89a9-96a70f701368",
    # Done
    "done": "e10793e2-3f5a-4cca-89a9-96a70f701368",
    "completed": "e10793e2-3f5a-4cca-89a9-96a70f701368",
}


class SDLCTracker:
    """Tracks issue states via Plane.so API."""

    def __init__(self, plane_api=None):
        self.plane_api = plane_api

    def detect_status(self, text: str) -> Optional[str]:
        """Scan text for status keywords. Returns state_id or None."""
        lower = text.lower()
        for keyword, state_id in STATUS_KEYWORDS.items():
            if keyword in lower:
                return state_id
        return None

    async def update_status(self, issue_id: str, state_id: str) -> bool:
        """Update the state of a Plane.so issue."""
        if self.plane_api is None:
            logging.warning(f"SDLC: Would update {issue_id} → {state_id} (no Plane API)")
            return False
        try:
            result = await self.plane_api.update_issue_state(issue_id, state_id)
            logging.info(f"SDLC: Updated {issue_id} → {state_id}")
            return result
        except Exception as e:
            logging.error(f"SDLC update failed: {e}")
            return False
