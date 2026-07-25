"""
Agent chat message layouts + outbound splitting.

Formats (per chat connection `message_format`):
  block    — A: ━━ header/footer bars
  card     — B: box header + handoff rule (default)
  quote    — C: speaker quote + thin rule
  sections — D: RESPONSE / HANDOFF sections
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Iterable, Optional

MESSAGE_FORMATS = ("block", "card", "quote", "sections")
DEFAULT_MESSAGE_FORMAT = "card"

PLATFORM_MAX_LENGTH: dict[str, int] = {
    "discord": 1900,
    "telegram": 4000,
    "slack": 3900,
    "zulip": 10000,
}

# Markers used for bot-loop / prefix stripping (new + legacy)
_BOT_OWN_MARKERS = (
    "**[@",
    "Processing...",
    "working…",
    "working...",
    "AGENT  ",
    "RESPONSE ·",
    "╔══",
    "━━━━━━━━",
)


class MessageKind(str, Enum):
    PROCESSING = "processing"
    REPLY = "reply"
    ERROR = "error"
    HANDOFF = "handoff"


def normalize_message_format(value: str | None) -> str:
    v = (value or "").strip().lower()
    if v in MESSAGE_FORMATS:
        return v
    return DEFAULT_MESSAGE_FORMAT


def is_bot_own_message(content: str) -> bool:
    raw = content or ""
    return any(m in raw for m in _BOT_OWN_MARKERS)


def strip_display_prefix(content: str) -> str:
    """Remove formatter / legacy headers so @mentions remain parseable."""
    text = content or ""
    lines = text.split("\n")
    if not lines:
        return text

    first = lines[0].strip()
    # Legacy: **[@PM]** or **[@PM → @SA]** (depth:N)
    if first.startswith("**[@") and first.endswith("**"):
        return "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    if first.startswith("**[↪"):
        return "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

    # New layouts: drop decorative header block until blank line after opener
    if first.startswith("━━") or first.startswith("╔") or first.startswith("==="):
        # Find first blank line after header, or line starting with body markers
        body_start = 0
        for i, line in enumerate(lines):
            s = line.strip()
            if i == 0:
                continue
            if not s:
                body_start = i + 1
                break
            if s.startswith("🗣️") or s.startswith(">") or s.startswith("RESPONSE"):
                body_start = i
                break
        rest = "\n".join(lines[body_start:]).strip()
        # Quote format: drop leading "ROLE said:" / blockquote markers for mention parse
        rest = re.sub(r"^🗣️\s*\*\*[^*]+\*\*\s*said:\s*", "", rest)
        rest = re.sub(r"^>\s?", "", rest, flags=re.M)
        # Strip trailing handoff footer
        rest = re.split(r"\n(?:━━+|──+|===+|📬 Asking|HANDOFF)", rest, maxsplit=1)[0]
        return rest.strip()

    # Card / sections mid-header lines
    if "AGENT" in first and "·" in first:
        return "\n".join(lines[1:]).lstrip("\n").strip()

    return text


def format_processing(role: str, fmt: str = DEFAULT_MESSAGE_FORMAT) -> str:
    role_u = (role or "?").upper()
    fmt = normalize_message_format(fmt)
    if fmt == "block":
        return (
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"AGENT  {role_u} · working…\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
    if fmt == "quote":
        return f"🗣️ **{role_u}** working…"
    if fmt == "sections":
        return (
            "==============================\n"
            f"RESPONSE · {role_u}\n"
            "STATUS   working…\n"
            "=============================="
        )
    # card (default)
    return (
        "╔══════════════════════════════════\n"
        f"║  {role_u}  ·  working…\n"
        "╚══════════════════════════════════"
    )


def format_error(role: str, error: str, fmt: str = DEFAULT_MESSAGE_FORMAT) -> str:
    role_u = (role or "?").upper()
    fmt = normalize_message_format(fmt)
    err = (error or "Error").strip()
    if fmt == "block":
        return (
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"AGENT  {role_u} · error\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{err}"
        )
    if fmt == "quote":
        return f"🗣️ **{role_u}** error:\n> {err}"
    if fmt == "sections":
        return (
            "==============================\n"
            f"RESPONSE · {role_u}\n"
            "STATUS   error\n"
            "==============================\n\n"
            f"{err}"
        )
    return (
        "╔══════════════════════════════════\n"
        f"║  {role_u}  ·  error\n"
        "╚══════════════════════════════════\n"
        f"{err}"
    )


def format_reply(
    role: str,
    body: str,
    *,
    fmt: str = DEFAULT_MESSAGE_FORMAT,
    topic: str = "",
    task_id: str = "",
    ticket_url: str = "",
    status: str = "",
    handoffs: Optional[Iterable[str]] = None,
) -> str:
    role_u = (role or "?").upper()
    fmt = normalize_message_format(fmt)
    body = (body or "").strip()
    handoff_names = [h for h in (handoffs or []) if h]
    meta_bits = []
    if task_id:
        meta_bits.append(task_id)
    if ticket_url:
        # keep short — full URL still in body footer for card/block
        pass
    meta = " · ".join(meta_bits)

    if fmt == "block":
        header = (
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"AGENT  {role_u}\n"
        )
        if meta or topic:
            line = " · ".join(x for x in [meta, f"#{topic}" if topic else ""] if x)
            if line:
                header += f"{line}\n"
        header += "━━━━━━━━━━━━━━━━━━━━\n\n"
        out = header + body
        if ticket_url:
            out += f"\n\nTicket: {ticket_url}"
        if status:
            out += f"\nStatus: {status}"
        if handoff_names:
            names = ", ".join(f"@{n}" for n in handoff_names)
            out += (
                "\n\n━━━━━━━━━━━━━━━━━━━━\n"
                f"next: {names}\n"
                "━━━━━━━━━━━━━━━━━━━━"
            )
        return out

    if fmt == "quote":
        quoted = "\n".join(f"> {ln}" if ln.strip() else ">" for ln in body.splitlines())
        out = f"🗣️ **{role_u}** said:\n{quoted}"
        foot = []
        if task_id or ticket_url:
            foot.append(
                "🎫 "
                + " · ".join(x for x in [task_id, ticket_url] if x)
            )
        if status:
            foot.append(f"Status: {status}")
        if foot:
            out += "\n" + "\n".join(foot)
        out += "\n────────────────────"
        if handoff_names:
            names = ", ".join(f"**@{n}**" for n in handoff_names)
            out += f"\n📬 Asking {names} next"
        return out

    if fmt == "sections":
        out = (
            "==============================\n"
            f"RESPONSE · {role_u}\n"
        )
        if status:
            out += f"STATUS   {status}\n"
        if task_id or ticket_url:
            out += f"TICKET   {' / '.join(x for x in [task_id, ticket_url] if x)}\n"
        if topic:
            out += f"TOPIC    #{topic}\n"
        out += "==============================\n\n"
        out += body
        if handoff_names:
            names = ", ".join(f"@{n}" for n in handoff_names)
            out += (
                "\n\n==============================\n"
                f"HANDOFF → {names}\n"
                "=============================="
            )
        return out

    # card (default)
    title = f"{role_u}  ·  reply"
    if task_id:
        title += f"  ·  {task_id}"
    out = (
        "╔══════════════════════════════════\n"
        f"║  {title}\n"
        "╚══════════════════════════════════\n"
        f"{body}"
    )
    if ticket_url:
        out += f"\n\nTicket: {ticket_url}"
    if status:
        out += f"\nStatus: {status}"
    if handoff_names:
        names = ", ".join(f"@{n}" for n in handoff_names)
        out += (
            "\n\n── handoff ───────────────────────\n"
            f"→ {names}"
        )
    return out


def format_handoff(
    from_role: str,
    to_role: str,
    body: str,
    *,
    depth: int = 1,
    fmt: str = DEFAULT_MESSAGE_FORMAT,
) -> str:
    fr = (from_role or "?").upper()
    to = (to_role or "?").upper()
    fmt = normalize_message_format(fmt)
    body = (body or "").strip()

    if fmt == "block":
        return (
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"AGENT  {fr} → {to}  (depth:{depth})\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{body}"
        )
    if fmt == "quote":
        return (
            f"🔁 **{fr} → {to}**\n"
            "────────────────────\n"
            f"{body}"
        )
    if fmt == "sections":
        return (
            "==============================\n"
            f"HANDOFF · {fr} → {to}\n"
            f"DEPTH    {depth}\n"
            "==============================\n\n"
            f"{body}"
        )
    # card
    return (
        "╔══════════════════════════════════\n"
        f"║  {fr} → {to}  ·  handoff  ·  d{depth}\n"
        "╚══════════════════════════════════\n"
        f"{body}"
    )


def split_outbound(
    content: str,
    max_len: int,
    *,
    role: str = "",
) -> list[str]:
    """
    Split content into chunks <= max_len at natural boundaries.
    Chunks 2+ get a short continuation prefix.
    """
    text = content or ""
    if max_len <= 0:
        return [text] if text else [""]
    if len(text) <= max_len:
        return [text]

    # Reserve room for continuation prefix on later chunks
    role_u = (role or "").upper()
    prefix_budget = len(f"(cont. 99/99) · {role_u}\n") + 8
    body_max = max(64, max_len - prefix_budget)

    raw_chunks: list[str] = []
    remaining = text
    first = True
    while remaining:
        limit = max_len if first else body_max
        if len(remaining) <= limit:
            raw_chunks.append(remaining)
            break
        split_at = _find_split(remaining, limit)
        raw_chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
        first = False

    total = len(raw_chunks)
    if total == 1:
        return raw_chunks

    out: list[str] = []
    for i, chunk in enumerate(raw_chunks):
        if i == 0:
            out.append(chunk)
            continue
        prefix = f"(cont. {i + 1}/{total})"
        if role_u:
            prefix += f" · {role_u}"
        piece = f"{prefix}\n{chunk}"
        if len(piece) > max_len:
            piece = piece[:max_len]
        out.append(piece)
    return out


def _find_split(content: str, max_len: int) -> int:
    """Prefer paragraph / line / space; avoid splitting inside ``` fences when possible."""
    if len(content) <= max_len:
        return len(content)

    window = content[:max_len]
    # If odd number of ``` in window, try to split before last fence open
    if window.count("```") % 2 == 1:
        fence = window.rfind("```")
        if fence > max_len // 3:
            return fence

    para = window.rfind("\n\n")
    if para > max_len // 2:
        return para + 2
    nl = window.rfind("\n")
    if nl > max_len // 2:
        return nl + 1
    sp = window.rfind(" ")
    if sp > max_len // 2:
        return sp + 1
    return max_len


def platform_max_length(platform: str, adapter_max: int | None = None) -> int:
    if adapter_max and adapter_max > 0:
        return adapter_max
    return PLATFORM_MAX_LENGTH.get((platform or "").lower(), 1900)
