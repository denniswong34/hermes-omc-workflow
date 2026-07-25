"""
Map internal SDLC statuses onto provider board statuses (Jira names / Plane state IDs).

Projects rarely have a 1:1 column for every SDLC stage (e.g. only To Do / In Progress /
In Review / Done). These helpers pick the closest available status by name aliases and
category/group fallbacks so workflow → tracker sync still works.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from core.tickets.status import SdlcStatus

# Preferred Jira transition / status names when the project has custom columns.
DEFAULT_JIRA_STATUS_MAP: dict[str, str] = {
    SdlcStatus.BACKLOG.value: "Backlog",
    SdlcStatus.TODO.value: "To Do",
    SdlcStatus.IN_PROGRESS.value: "In Progress",
    SdlcStatus.IN_REVIEW.value: "In Review",
    SdlcStatus.QA_REVIEW.value: "QA Review",
    SdlcStatus.QA_FAILED.value: "QA Failed",
    SdlcStatus.QA_VERIFIED.value: "QA Verified",
    SdlcStatus.READY_TO_DEPLOY.value: "Ready to Deploy",
    SdlcStatus.DEPLOYED.value: "Deployed",
    SdlcStatus.DONE.value: "Done",
    SdlcStatus.CANCELLED.value: "Cancelled",
}

# Name aliases tried in order when resolving against live board statuses.
STATUS_NAME_ALIASES: dict[SdlcStatus, tuple[str, ...]] = {
    SdlcStatus.BACKLOG: ("backlog", "to do", "todo", "open", "new", "selected for development"),
    SdlcStatus.TODO: ("to do", "todo", "open", "selected for development", "backlog"),
    SdlcStatus.IN_PROGRESS: ("in progress", "in development", "doing", "wip", "started"),
    SdlcStatus.IN_REVIEW: ("in review", "code review", "peer review", "review"),
    SdlcStatus.QA_REVIEW: ("qa review", "qa", "testing", "in test", "in qa", "in review"),
    SdlcStatus.QA_FAILED: ("qa failed", "rework", "blocked", "failed", "in progress", "to do"),
    SdlcStatus.QA_VERIFIED: (
        "qa verified",
        "qa passed",
        "verified",
        "ready to deploy",
        "ready for release",
        "in review",
        "done",
    ),
    SdlcStatus.READY_TO_DEPLOY: (
        "ready to deploy",
        "ready for deploy",
        "ready for release",
        "ready",
        "done",
        "in review",
    ),
    SdlcStatus.DEPLOYED: ("deployed", "released", "shipped", "done", "closed"),
    SdlcStatus.DONE: ("done", "closed", "complete", "completed", "resolved"),
    SdlcStatus.CANCELLED: ("cancelled", "canceled", "won't do", "wontfix", "rejected", "done"),
}

# Jira statusCategory.key fallback when no name alias matches.
JIRA_CATEGORY_FALLBACK: dict[SdlcStatus, str] = {
    SdlcStatus.BACKLOG: "new",
    SdlcStatus.TODO: "new",
    SdlcStatus.IN_PROGRESS: "indeterminate",
    SdlcStatus.IN_REVIEW: "indeterminate",
    SdlcStatus.QA_REVIEW: "indeterminate",
    SdlcStatus.QA_FAILED: "indeterminate",
    SdlcStatus.QA_VERIFIED: "indeterminate",
    SdlcStatus.READY_TO_DEPLOY: "done",
    SdlcStatus.DEPLOYED: "done",
    SdlcStatus.DONE: "done",
    SdlcStatus.CANCELLED: "done",
}

# Plane state.group fallback when no name alias matches.
PLANE_GROUP_FALLBACK: dict[SdlcStatus, str] = {
    SdlcStatus.BACKLOG: "backlog",
    SdlcStatus.TODO: "unstarted",
    SdlcStatus.IN_PROGRESS: "started",
    SdlcStatus.IN_REVIEW: "started",
    SdlcStatus.QA_REVIEW: "started",
    SdlcStatus.QA_FAILED: "started",
    SdlcStatus.QA_VERIFIED: "started",
    SdlcStatus.READY_TO_DEPLOY: "started",
    SdlcStatus.DEPLOYED: "completed",
    SdlcStatus.DONE: "completed",
    SdlcStatus.CANCELLED: "cancelled",
}


def normalize_status_name(name: str) -> str:
    return " ".join((name or "").strip().lower().replace("_", " ").replace("-", " ").split())


def nonempty_status_map(raw: dict[str, Any] | None) -> dict[str, str]:
    return {str(k): str(v) for k, v in (raw or {}).items() if str(v or "").strip()}


def merge_status_maps(*maps: dict[str, str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in maps:
        for k, v in nonempty_status_map(m).items():
            out[k] = v
    return out


def default_jira_status_map() -> dict[str, str]:
    return dict(DEFAULT_JIRA_STATUS_MAP)


def _index_by_name(names: Iterable[str]) -> dict[str, str]:
    """normalized → original display name (first wins)."""
    out: dict[str, str] = {}
    for name in names:
        n = normalize_status_name(name)
        if n and n not in out:
            out[n] = name
    return out


def resolve_status_name(
    status: SdlcStatus,
    available_names: Iterable[str],
    *,
    preferred: str | None = None,
    categories: dict[str, str] | None = None,
) -> Optional[str]:
    """
    Pick the best available board status name for an SDLC status.

    `categories` maps original status name → jira statusCategory.key (optional).
    """
    by_norm = _index_by_name(available_names)
    if not by_norm:
        return preferred or None

    candidates: list[str] = []
    if preferred:
        candidates.append(preferred)
    candidates.extend(STATUS_NAME_ALIASES.get(status, ()))

    for cand in candidates:
        hit = by_norm.get(normalize_status_name(cand))
        if hit:
            return hit

    # Category fallback (Jira)
    if categories:
        want = JIRA_CATEGORY_FALLBACK.get(status)
        if want:
            for original, cat in categories.items():
                if (cat or "").lower() == want and normalize_status_name(original) in by_norm:
                    return original
            for original, cat in categories.items():
                if (cat or "").lower() == want:
                    return original

    return None


def build_status_map_from_names(
    available_names: Iterable[str],
    *,
    preferred_map: dict[str, str] | None = None,
    categories: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build sdlc_value → provider status name for every SdlcStatus."""
    names = list(available_names)
    preferred = nonempty_status_map(preferred_map) or default_jira_status_map()
    out: dict[str, str] = {}
    for status in SdlcStatus:
        picked = resolve_status_name(
            status,
            names,
            preferred=preferred.get(status.value),
            categories=categories,
        )
        if picked:
            out[status.value] = picked
    return out


def resolve_plane_state_id(
    status: SdlcStatus,
    states: list[dict[str, Any]],
    *,
    preferred_id: str | None = None,
) -> Optional[str]:
    """Pick Plane state UUID for an SDLC status from project states list."""
    if preferred_id:
        for s in states:
            if str(s.get("id") or "") == preferred_id:
                return preferred_id

    by_name: dict[str, str] = {}
    by_group: dict[str, list[str]] = {}
    for s in states:
        sid = str(s.get("id") or "").strip()
        if not sid:
            continue
        name = normalize_status_name(str(s.get("name") or ""))
        if name and name not in by_name:
            by_name[name] = sid
        group = normalize_status_name(str(s.get("group") or ""))
        if group:
            by_group.setdefault(group, []).append(sid)

    for cand in STATUS_NAME_ALIASES.get(status, ()):
        hit = by_name.get(normalize_status_name(cand))
        if hit:
            return hit

    want_group = PLANE_GROUP_FALLBACK.get(status)
    if want_group and by_group.get(want_group):
        return by_group[want_group][0]

    # Last resort: first state
    if states:
        sid = str(states[0].get("id") or "").strip()
        return sid or None
    return None


def build_plane_status_map(
    states: list[dict[str, Any]],
    *,
    preferred_map: dict[str, str] | None = None,
) -> dict[str, str]:
    preferred = nonempty_status_map(preferred_map)
    out: dict[str, str] = {}
    for status in SdlcStatus:
        picked = resolve_plane_state_id(
            status,
            states,
            preferred_id=preferred.get(status.value),
        )
        if picked:
            out[status.value] = picked
    return out


def pick_jira_transition(
    transitions: list[dict[str, Any]],
    status: SdlcStatus,
    *,
    preferred_target: str | None = None,
) -> Optional[dict[str, Any]]:
    """
    Choose a Jira transition that lands on the best available status for `status`.
    Matches transition name or destination status name.
    """
    if not transitions:
        return None

    dest_names: list[str] = []
    categories: dict[str, str] = {}
    for t in transitions:
        to = t.get("to") or {}
        name = to.get("name") or t.get("name") or ""
        if name:
            dest_names.append(name)
            cat = ((to.get("statusCategory") or {}).get("key")) or ""
            if cat:
                categories[name] = cat
        # also allow matching on transition name itself
        if t.get("name"):
            dest_names.append(t["name"])

    target = resolve_status_name(
        status,
        dest_names,
        preferred=preferred_target,
        categories=categories,
    )
    if not target:
        return None

    target_n = normalize_status_name(target)
    for t in transitions:
        name_n = normalize_status_name(t.get("name") or "")
        to_n = normalize_status_name(((t.get("to") or {}).get("name")) or "")
        if name_n == target_n or to_n == target_n:
            return t
    return None
