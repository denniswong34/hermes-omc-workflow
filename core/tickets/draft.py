"""
Draft professional ticket title + description from a chat request.

Never paste the raw chat line as both summary and body. Rewrite into a concise
title and a structured description (requirements or repro steps).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Avoid importing agent_router (circular). Duplicate light mention strip.
_MENTION_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_-]*)\b:?\s*", re.IGNORECASE)
_THEN_HANDOFF_RE = re.compile(
    r"(?:^|[.!\s])then\s+@[A-Za-z][A-Za-z0-9_-]*\b.*$",
    re.IGNORECASE | re.DOTALL,
)
_TRAILING_THEN_RE = re.compile(r"\bthen\b[.!]*\s*$", re.IGNORECASE)
_RUN_TAG_RE = re.compile(r"\bSDLC-E2E-[\w-]+\b", re.IGNORECASE)
_META_PREFIX_RE = re.compile(
    r"^\s*(create(?:\s*/\s*track)?|track|open|file|log|raise)\s+"
    r"(a\s+|an\s+)?(jira\s+|plane\s+)?(task|ticket|issue)\s+(for\s+)?",
    re.IGNORECASE,
)
_META_INLINE_RE = re.compile(
    r"\b(?:create(?:\s*/\s*track)?|track)\s+(?:a\s+|an\s+)?(?:jira\s+|plane\s+)?"
    r"(?:task|ticket|issue)\s+(?:for\s+)?",
    re.IGNORECASE,
)
_ONE_LINE_PREFIX_RE = re.compile(
    r"^\s*(?:one[- ]line\s+)?(?:scope|priority|design note|deploy note|launch blurb)\s+(?:for\s+)?",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s<>\]\)]+", re.IGNORECASE)

_BUG_HINTS = (
    "bug",
    "error",
    "fail",
    "broken",
    "cannot",
    "can't",
    "unable",
    "crash",
    "exception",
    "repro",
    "reproduce",
    "triage",
    "not working",
    "doesn't work",
    "does not work",
    "never received",
    "missing",
)
_FEATURE_HINTS = (
    "implement",
    "add",
    "build",
    "create",
    "scope",
    "feature",
    "support",
    "enable",
    "design",
    "priority",
    "login",
    "auth",
    "magic-link",
    "magic link",
    "passwordless",
)


@dataclass(frozen=True)
class TicketDraft:
    title: str
    description: str
    kind: str  # feature | bug | task


def _clean_request(text: str) -> str:
    raw = (text or "").strip()
    # Drop display prefixes already stripped by router, but be safe
    lines = raw.splitlines()
    if lines and lines[0].startswith("**[") and lines[0].endswith("**"):
        raw = "\n".join(lines[1:]).strip()

    cleaned = _THEN_HANDOFF_RE.sub("", raw)
    cleaned = _MENTION_RE.sub("", cleaned)
    cleaned = _TRAILING_THEN_RE.sub("", cleaned)
    cleaned = _RUN_TAG_RE.sub("", cleaned)
    cleaned = _META_PREFIX_RE.sub("", cleaned)
    cleaned = _META_INLINE_RE.sub("", cleaned)
    cleaned = _ONE_LINE_PREFIX_RE.sub("", cleaned)
    cleaned = re.sub(r"^\s*[:\-–—]+\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -\n\t.:;")
    return cleaned


def _detect_kind(text: str) -> str:
    lower = text.lower()
    bug_score = sum(1 for h in _BUG_HINTS if h in lower)
    feat_score = sum(1 for h in _FEATURE_HINTS if h in lower)
    if bug_score > feat_score and bug_score > 0:
        return "bug"
    if feat_score > 0:
        return "feature"
    return "task"


def _title_case_sentence(s: str) -> str:
    s = s.strip()
    if not s:
        return "New work item"
    # Keep short technical tokens
    if s[0].islower():
        s = s[0].upper() + s[1:]
    if len(s) > 100:
        s = s[:97].rstrip() + "…"
    return s


def _rewrite_title(cleaned: str, kind: str) -> str:
    lower = cleaned.lower()

    # Drop leftover smoke/test labels from e2e chatter
    body = re.sub(r"^\s*smoke\s*:\s*", "", cleaned, flags=re.I).strip()

    # Common chat phrasings → crisp titles
    patterns: list[tuple[re.Pattern[str], str]] = [
        (
            re.compile(
                r"^(?:one[- ]line\s+)?(?:scope|priority|design note)\s+(?:for\s+)?(.+)$",
                re.I,
            ),
            r"\1",
        ),
        (
            re.compile(r"^triage[:\s]+(.+)$", re.I),
            r"\1",
        ),
        (
            re.compile(
                r"^(?:reply with|list|write)\s+(?:a\s+|an\s+)?(?:.+?)\s+for\s+(.+)$",
                re.I,
            ),
            r"\1",
        ),
    ]
    for pat, repl in patterns:
        m = pat.match(body)
        if m:
            body = m.expand(repl).strip(" .:")
            break

    body = re.sub(
        r"^(please\s+)?(can you\s+|could you\s+)?",
        "",
        body,
        flags=re.I,
    ).strip()

    # Imperative framing
    if kind == "bug":
        if not re.match(r"^(fix|investigate|resolve|debug)\b", body, re.I):
            if re.search(r"\b(cannot|can't|unable|fail|error|broken)\b", body, re.I):
                title = body
            else:
                title = f"Investigate: {body}"
        else:
            title = body
    elif kind == "feature":
        if not re.match(
            r"^(implement|add|build|enable|support|design|create)\b", body, re.I
        ):
            title = f"Implement {body}"
        else:
            title = body
    else:
        title = body

    title = re.sub(r"\s+", " ", title).strip(" .:")
    return _title_case_sentence(title)


def _bulletize_requirements(cleaned: str, kind: str) -> list[str]:
    """Derive concrete requirement / repro bullets from the request."""
    bullets: list[str] = []
    lower = cleaned.lower()

    if kind == "bug":
        bullets.append(f"Reported problem: {cleaned}")
        if "email" in lower and ("magic" in lower or "link" in lower or "reset" in lower):
            bullets.extend(
                [
                    "Steps: request the email/link from the product UI or API.",
                    "Steps: wait for delivery and check inbox + spam.",
                    "Steps: confirm provider logs (SES/SendGrid/etc.) for the recipient domain.",
                ]
            )
        else:
            bullets.extend(
                [
                    "Steps: reproduce using the same account/environment described by the reporter.",
                    "Steps: capture exact error text, HTTP status, and timestamps.",
                    "Steps: note browser/app version and whether it is consistent.",
                ]
            )
        bullets.append("Expected: the flow completes successfully without errors.")
        bullets.append("Actual: behavior matches the reported failure until fixed.")
    else:
        # Feature / task — expand into requirements without repeating the title
        bullets.append(f"Goal: deliver {cleaned}.")
        if "login" in lower or "auth" in lower or "magic-link" in lower or "magic link" in lower:
            bullets.extend(
                [
                    "Users can request a one-time login link by email.",
                    "Link/token expires and cannot be reused after success.",
                    "Failed or expired attempts return a safe, non-enumerating error.",
                    "Successful verify establishes an authenticated session.",
                ]
            )
        elif "api" in lower:
            bullets.extend(
                [
                    "Define request/response contract and error cases.",
                    "Document auth, rate limits, and idempotency where relevant.",
                    "Add minimal automated coverage for the happy path + one failure path.",
                ]
            )
        else:
            bullets.extend(
                [
                    "Clarify actors, inputs, and outputs with the requester if ambiguous.",
                    "Implement the smallest slice that satisfies the stated goal.",
                    "Include verification notes so QA can validate the change.",
                ]
            )
        bullets.append(
            "Out of scope unless requested: unrelated refactors, new infra, or marketing copy."
        )
    return bullets


def _acceptance_criteria(kind: str, cleaned: str) -> list[str]:
    lower = cleaned.lower()
    if kind == "bug":
        return [
            "Issue is reproducible before the fix and not after.",
            "No new regressions in the related auth/email path.",
            "Notes or logs confirming root cause are attached in comments.",
        ]
    criteria = [
        "Behavior matches the requirements above in a reviewable environment.",
        "Automated or manual checks cover the primary success path.",
    ]
    if "login" in lower or "auth" in lower:
        criteria.append("Invalid/expired tokens are rejected safely.")
    return criteria


def draft_ticket(
    content: str,
    *,
    topic: str = "",
    role: str = "",
    author: str = "",
) -> TicketDraft:
    """Build a title + structured description from a chat work request."""
    cleaned = _clean_request(content)
    if not cleaned:
        cleaned = "Follow up on the latest chat request"
    kind = _detect_kind(cleaned)
    title = _rewrite_title(cleaned, kind)

    urls = _URL_RE.findall(content or "")
    req_bullets = _bulletize_requirements(cleaned, kind)
    acceptance = _acceptance_criteria(kind, cleaned)

    lines: list[str] = []
    if kind == "bug":
        lines.append("## Problem")
        lines.append(
            "A defect was reported in chat. Capture root cause, fix, and verification on this ticket."
        )
        lines.append("")
        lines.append("## Steps to reproduce")
    else:
        lines.append("## Overview")
        lines.append(
            "Work requested via the agent workflow. Implement and verify against the requirements below."
        )
        lines.append("")
        lines.append("## Requirements")

    for b in req_bullets:
        lines.append(f"- {b}")

    lines.append("")
    lines.append("## Acceptance criteria")
    for b in acceptance:
        lines.append(f"- {b}")

    lines.append("")
    lines.append("## Evidence / attachments")
    if urls:
        lines.append("Links shared in the request:")
        for u in urls[:10]:
            lines.append(f"- {u}")
        lines.append("If screenshots were mentioned but not linked, ask the reporter to attach them here.")
    else:
        lines.append(
            "No screenshot or log URLs were included in the chat request. "
            "Attach screen dumps, HAR/logs, or API payloads when available."
        )

    lines.append("")
    lines.append("## Context")
    if topic:
        lines.append(f"- Channel topic: #{topic}")
    if role:
        lines.append(f"- Created via @{role}")
    if author:
        lines.append(f"- Requested by: {author}")
    lines.append("- Source request (verbatim, for traceability):")
    lines.append(f"> {(content or '').strip()[:1500]}")

    description = "\n".join(lines).strip()
    # Guard: description must not be identical to title
    if description.strip().lower() == title.strip().lower():
        description = (
            f"## Overview\nExpand and deliver: {title}\n\n"
            f"## Context\n> {(content or '').strip()[:1500]}"
        )
    return TicketDraft(title=title, description=description, kind=kind)


def format_agent_comment(
    *,
    role: str,
    topic: str,
    body: str,
    status: Optional[str] = None,
    task_id: str = "",
) -> str:
    """Plain-text comment body for Jira/Plane from an agent turn."""
    parts = [f"[{role.upper()} · #{topic}]"]
    if task_id:
        parts[0] += f" · {task_id}"
    if status:
        parts.append(f"Status → {status}")
    parts.append("")
    parts.append((body or "").strip()[:3500])
    return "\n".join(parts).strip()
