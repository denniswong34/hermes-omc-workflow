"""Shared send/edit helpers that split long messages instead of truncating."""

from __future__ import annotations

from typing import Optional, Protocol

from core.chat_messages import split_outbound


class _SupportsSend(Protocol):
    max_message_length: int

    async def _deliver_message(self, channel_id: str, content: str) -> Optional[str]:
        ...

    async def _deliver_edit(
        self, channel_id: str, message_id: str, content: str
    ) -> bool:
        ...


async def send_with_split(
    adapter: _SupportsSend,
    channel_id: str,
    content: str,
    *,
    role: str = "",
) -> Optional[str]:
    """Send content, splitting into multiple messages when over the limit."""
    chunks = split_outbound(
        content,
        getattr(adapter, "max_message_length", 1900),
        role=role,
    )
    first_id: Optional[str] = None
    for i, chunk in enumerate(chunks):
        mid = await adapter._deliver_message(channel_id, chunk)
        if i == 0:
            first_id = mid
    return first_id


async def edit_with_split(
    adapter: _SupportsSend,
    channel_id: str,
    message_id: str,
    content: str,
    *,
    role: str = "",
) -> bool:
    """
    Edit the target message with chunk 1; post remaining chunks as new messages.
    """
    chunks = split_outbound(
        content,
        getattr(adapter, "max_message_length", 1900),
        role=role,
    )
    if not chunks:
        return await adapter._deliver_edit(channel_id, message_id, "")
    ok = await adapter._deliver_edit(channel_id, message_id, chunks[0])
    for chunk in chunks[1:]:
        await adapter._deliver_message(channel_id, chunk)
    return ok
