"""
Provider-agnostic SDLC status enum and keyword detection.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class SdlcStatus(str, Enum):
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    QA_REVIEW = "qa_review"
    QA_FAILED = "qa_failed"
    QA_VERIFIED = "qa_verified"
    READY_TO_DEPLOY = "ready_to_deploy"
    DEPLOYED = "deployed"
    DONE = "done"
    CANCELLED = "cancelled"

    @property
    def display(self) -> str:
        """Human / chat keyword form (spaces instead of underscores)."""
        return self.value.replace("_", " ")


# Longer phrases first so "qa failed" wins over "failed", etc.
KEYWORD_TO_STATUS: list[tuple[str, SdlcStatus]] = [
    ("ready to deploy", SdlcStatus.READY_TO_DEPLOY),
    ("ready for deploy", SdlcStatus.READY_TO_DEPLOY),
    ("ready for production", SdlcStatus.READY_TO_DEPLOY),
    ("qa verified", SdlcStatus.QA_VERIFIED),
    ("qa passed", SdlcStatus.QA_VERIFIED),
    ("passed qa", SdlcStatus.QA_VERIFIED),
    ("qa approved", SdlcStatus.QA_VERIFIED),
    ("qa failed", SdlcStatus.QA_FAILED),
    ("failed qa", SdlcStatus.QA_FAILED),
    ("qa rejected", SdlcStatus.QA_FAILED),
    ("needs rework", SdlcStatus.QA_FAILED),
    ("qa review", SdlcStatus.QA_REVIEW),
    ("in review", SdlcStatus.IN_REVIEW),
    ("in progress", SdlcStatus.IN_PROGRESS),
    ("to do", SdlcStatus.TODO),
    ("todo", SdlcStatus.TODO),
    ("backlog", SdlcStatus.BACKLOG),
    ("deployed", SdlcStatus.DEPLOYED),
    ("released", SdlcStatus.DEPLOYED),
    ("cancelled", SdlcStatus.CANCELLED),
    ("canceled", SdlcStatus.CANCELLED),
    ("wontfix", SdlcStatus.CANCELLED),
    ("done", SdlcStatus.DONE),
    ("completed", SdlcStatus.DONE),
    ("rework", SdlcStatus.QA_FAILED),
    ("wip", SdlcStatus.IN_PROGRESS),
]


def detect_status(text: str) -> Optional[SdlcStatus]:
    """Scan text for the first matching SDLC status keyword."""
    lower = text.lower()
    for keyword, status in KEYWORD_TO_STATUS:
        if keyword in lower:
            return status
    return None


def status_from_display(keyword: str) -> Optional[SdlcStatus]:
    """Map a display keyword (e.g. 'in progress') to SdlcStatus."""
    normalized = keyword.strip().lower().replace("-", " ")
    for kw, status in KEYWORD_TO_STATUS:
        if kw == normalized:
            return status
    # try underscore form
    try:
        return SdlcStatus(normalized.replace(" ", "_"))
    except ValueError:
        return None
