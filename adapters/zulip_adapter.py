"""
Zulip Channel Adapter
=====================
Connects to any Zulip server (cloud or self-hosted) via the official
``zulip`` Python package. Uses long-polling event queue for real-time
message delivery and the REST API for sending.

Authentication uses bot email + API key + server URL (no OAuth tokens).

Inspired by the official Hermes Agent Zulip plugin (PR #3335).

Environment variables:
    ZULIP_SITE_URL      Server URL (e.g. https://your-org.zulipchat.com)
    ZULIP_BOT_EMAIL     Bot's email address
    ZULIP_API_KEY       Bot's API key (from Zulip bot settings)
    ZULIP_ALLOWED_USERS Comma-separated email addresses of allowed users
    ZULIP_HOME_STREAM   Default stream for cron/notification delivery

Agent-to-stream mapping (in config.yaml):
    zulip:
      stream_map:
        pm: "pm"
        sa: "sa"
        coder: "coder"
        qa: "qa"
        marketing: "marketing"
        summary: "general"
      topic_prefix: "omc-"  # optional prefix for topics
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Callable, Optional

from adapters.base import ChannelAdapter, Message, MessageHandler

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 10_000

_DM_PREFIX = "dm:"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_stream_chat_id(stream_id: int, topic: str) -> str:
    return f"{stream_id}:{topic}"


def _parse_stream_chat_id(chat_id: str) -> Optional[tuple[int, str]]:
    colon = chat_id.find(":")
    if colon < 1:
        return None
    stream_part = chat_id[:colon]
    if not stream_part.isdigit():
        return None
    topic = chat_id[colon + 1:] or "(no topic)"
    return (int(stream_part), topic)


def _build_dm_chat_id(sender_email: str) -> str:
    if sender_email.startswith(_DM_PREFIX):
        sender_email = sender_email[len(_DM_PREFIX):]
    return f"{_DM_PREFIX}{sender_email}"


def _parse_dm_chat_id(chat_id: str) -> Optional[str]:
    if chat_id.startswith(_DM_PREFIX) and "@" in chat_id:
        return chat_id[len(_DM_PREFIX):]
    return None


def _is_retryable_error(exc: Exception) -> bool:
    """Determine if a Zulip API error is worth retrying."""
    exc_name = type(exc).__name__
    if any(k in exc_name for k in ("ConnectionError", "Timeout", "SSLError")):
        return True
    if hasattr(exc, "http_status"):
        status = getattr(exc, "http_status", 0)
        if status in (401, 403):
            return False
        if 400 <= status < 500:
            return False
    return True


def _strip_bot_mention(content: str, bot_email: str) -> str:
    """Strip @mention of bot from message content."""
    # Zulip renders @**Bot Name** and @bot_email@example.com
    cleaned = re.sub(re.escape(bot_email), "", content, flags=re.IGNORECASE)
    # Also strip @**Name** patterns where name contains bot-related words
    cleaned = re.sub(r"@\*\*[^*]*" + re.escape(bot_email.split("@")[0]) + r"[^*]*\*\*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class ZulipAdapter(ChannelAdapter):
    """Adapter for Zulip using the official ``zulip`` Python package.

    Maps agent channel names (#pm, #sa, etc.) to Zulip stream names.
    Each agent conversation becomes a topic under that stream.
    """

    def __init__(
        self,
        stream_map: dict[str, str],
        topic_prefix: str = "omc-",
        allowed_users: list[str] | None = None,
    ):
        self.stream_map = stream_map
        self.topic_prefix = topic_prefix
        self.allowed_users = allowed_users or []
        self._msg_handler: Optional[MessageHandler] = None
        self._client: Any = None
        self._running = False
        self._queue_id: Optional[str] = None
        self._event_loop_task: Optional[asyncio.Task] = None
        self._bot_email: str = ""
        self._bot_id: int = 0
        self._stream_name_cache: dict[int, str] = {}
        self._stream_id_cache: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls, stream_map: dict[str, str] | None = None) -> "ZulipAdapter":
        """Create adapter from environment variables."""
        allowed_raw = os.getenv("ZULIP_ALLOWED_USERS", "")
        allowed = [u.strip() for u in allowed_raw.split(",") if u.strip()]
        topic_prefix = os.getenv("ZULIP_TOPIC_PREFIX", "omc-")
        return cls(
            stream_map=stream_map or {},
            topic_prefix=topic_prefix,
            allowed_users=allowed,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Connect to Zulip and start the event queue loop."""
        import zulip

        site = os.getenv("ZULIP_SITE_URL", "")
        email = os.getenv("ZULIP_BOT_EMAIL", "")
        api_key = os.getenv("ZULIP_API_KEY", "")

        if not all([site, email, api_key]):
            raise ValueError(
                "ZulipAdapter requires ZULIP_SITE_URL, ZULIP_BOT_EMAIL, "
                "and ZULIP_API_KEY environment variables"
            )

        client_kwargs = {
            "email": email,
            "api_key": api_key,
            "site": site,
        }

        # Optional TLS
        cert_bundle = os.getenv("ZULIP_CERT_BUNDLE", "")
        if cert_bundle:
            client_kwargs["cert_bundle"] = cert_bundle

        allow_insecure = os.getenv("ZULIP_ALLOW_INSECURE", "").lower() in ("true", "1")
        if allow_insecure:
            client_kwargs["insecure"] = "true"  # zulip.Client expects string

        self._client = zulip.Client(**client_kwargs)

        # Verify connection
        profile = self._client.get_profile()
        if not profile.get("result") == "success":
            raise ConnectionError(f"Zulip auth failed: {profile.get('msg', 'unknown error')}")

        self._bot_email = profile.get("email", email)
        self._bot_id = profile.get("user_id", 0)
        logger.info(
            "✓ Zulip connected as %s (user_id=%s) on %s",
            self._bot_email, self._bot_id, site,
        )

        # Resolve stream IDs from names
        await self._resolve_streams()

        # Register event queue
        self._running = True
        self._queue_id = None
        self._event_loop_task = asyncio.create_task(self._event_loop())

        logger.info("  Stream map: %s", self.stream_map)
        logger.info("  Allowed users: %s", self.allowed_users or "ALL (no restriction)")

    async def stop(self):
        """Stop the event queue and deregister."""
        self._running = False
        if self._queue_id and self._client:
            try:
                self._client.deregister(self._queue_id)
            except Exception:
                pass
            self._queue_id = None
        if self._event_loop_task:
            self._event_loop_task.cancel()
            self._event_loop_task = None
        logger.info("Zulip adapter stopped")

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def send_message(self, channel_id: str, content: str) -> Optional[str]:
        """Send a message to a Zulip stream or DM.

        ``channel_id`` can be:
        - ``stream_name`` (e.g. "pm") → sent to stream + default topic
        - ``stream_name:topic`` → sent to stream + specific topic
        - ``dm:email@example.com`` → sent as DM
        """
        if not self._client:
            logger.error("Zulip client not connected")
            return None

        channel_id = channel_id.lstrip("#")

        # DM?
        dm_email = _parse_dm_chat_id(channel_id)
        if dm_email:
            return await self._send_dm(dm_email, content)

        # Stream:topic
        topic = self.topic_prefix + channel_id
        stream_name = self.stream_map.get(channel_id, channel_id)

        return await self._send_stream(stream_name, topic, content)

    async def edit_message(self, channel_id: str, message_id: str, content: str) -> bool:
        """Edit a previously sent message (used for streaming updates)."""
        if not self._client:
            return False
        try:
            result = await asyncio.to_thread(
                self._client.update_message,
                {
                    "message_id": int(message_id),
                    "content": content,
                },
            )
            return result.get("result") == "success"
        except Exception as e:
            logger.error("Failed to edit Zulip message %s: %s", message_id, e)
            return False

    async def send_typing(self, channel_id: str):
        """Send typing indicator (stream typing for modern Zulip)."""
        # Zulip typing API requires stream_id + topic
        channel_id = channel_id.lstrip("#")
        stream_name = self.stream_map.get(channel_id, channel_id)
        stream_id = self._stream_id_cache.get(stream_name)
        if stream_id is None:
            return
        topic = self.topic_prefix + channel_id
        try:
            await asyncio.to_thread(
                self._client.set_typing_status,
                {
                    "stream_id": stream_id,
                    "topic": topic,
                    "type": "stream",
                    "op": "start",
                },
            )
        except Exception:
            pass  # typing is best-effort

    def on_message(self, handler: MessageHandler):
        self._msg_handler = handler

    # ------------------------------------------------------------------
    # Internal: send helpers
    # ------------------------------------------------------------------

    async def _send_stream(self, stream_name: str, topic: str, content: str) -> Optional[str]:
        """Send a message to a Zulip stream+topic."""
        chunks = self._split_content(content, MAX_MESSAGE_LENGTH)
        last_id = None
        for chunk in chunks:
            result = await asyncio.to_thread(
                self._client.send_message,
                {
                    "type": "stream",
                    "to": stream_name,
                    "topic": topic,
                    "content": chunk,
                },
            )
            if result.get("result") == "success":
                last_id = str(result.get("id", ""))
            else:
                logger.error("Zulip send error: %s", result.get("msg", ""))
        return last_id

    async def _send_dm(self, email: str, content: str) -> Optional[str]:
        """Send a direct message to a user."""
        chunks = self._split_content(content, MAX_MESSAGE_LENGTH)
        last_id = None
        for chunk in chunks:
            result = await asyncio.to_thread(
                self._client.send_message,
                {
                    "type": "private",
                    "to": [email],
                    "content": chunk,
                },
            )
            if result.get("result") == "success":
                last_id = str(result.get("id", ""))
        return last_id

    # ------------------------------------------------------------------
    # Internal: event loop
    # ------------------------------------------------------------------

    async def _event_loop(self):
        """Long-polling event queue loop (reconnects with backoff)."""
        delay = 2.0
        last_event_id = -1
        while self._running:
            try:
                if self._queue_id is None:
                    # Register a new event queue
                    result = await asyncio.to_thread(
                        self._client.register,
                        {
                            "event_types": ["message"],
                            "narrow": [],  # all streams
                            "all_public_streams": True,
                        },
                    )
                    if result.get("result") != "success":
                        logger.error("Zulip queue registration failed: %s", result.get("msg", ""))
                        await asyncio.sleep(10)
                        continue
                    self._queue_id = result.get("queue_id")
                    last_event_id = result.get("last_event_id", -1)
                    logger.info("Zulip event queue registered: %s", self._queue_id)
                    delay = 2.0  # reset backoff

                # Fetch events via long-poll
                response = await asyncio.to_thread(
                    self._client.get_events,
                    {
                        "queue_id": self._queue_id,
                        "last_event_id": last_event_id,
                        "dont_block": False,
                    },
                )

                if response.get("result") != "success":
                    msg = response.get("msg", "")
                    logger.warning("Zulip get_events error: %s", msg)
                    if "queue_id" in msg or "does not exist" in msg:
                        self._queue_id = None  # re-register
                    await asyncio.sleep(delay)
                    delay = min(delay * 1.5, 60)
                    continue

                events = response.get("events", [])
                for event in events:
                    last_event_id = event.get("id", last_event_id)
                    await self._handle_event(event)

                delay = 2.0  # reset on success

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Zulip event loop error: %s", e)
                if _is_retryable_error(e):
                    await asyncio.sleep(delay)
                    delay = min(delay * 1.5, 60)
                    if self._queue_id:
                        self._queue_id = None  # force re-register
                else:
                    logger.error("Non-retryable error, stopping event loop")
                    break

    async def _handle_event(self, event: dict):
        """Process an incoming Zulip event."""
        if event.get("type") != "message":
            return

        msg = event.get("message", {})
        sender_id = msg.get("sender_id", 0)
        sender_email = msg.get("sender_email", "")

        # Ignore bot's own messages
        if sender_id == self._bot_id or sender_email == self._bot_email:
            return

        # Check allowed users
        if self.allowed_users and sender_email not in self.allowed_users:
            logger.debug("Ignoring message from non-allowed user: %s", sender_email)
            return

        content = msg.get("content", "")
        if not content.strip():
            return

        # Strip bot mention
        content = _strip_bot_mention(content, self._bot_email)

        message_type = msg.get("type", "stream")

        if message_type == "stream":
            stream_id = msg.get("stream_id", 0)
            topic = msg.get("subject", msg.get("topic", "(no topic)"))
            chat_id = _build_stream_chat_id(stream_id, topic)

            # Map stream to agent channel
            stream_name = self._resolve_stream_name(msg, stream_id)
            agent_channel = self._map_stream_to_channel(stream_name)

            message = Message(
                id=str(msg.get("id", "")),
                channel_id=chat_id,
                author_id=str(sender_id),
                author_name=sender_email,
                content=content,
                is_bot=False,
                channel_name=agent_channel,
            )
        else:
            # DM
            chat_id = _build_dm_chat_id(sender_email)
            message = Message(
                id=str(msg.get("id", "")),
                channel_id=chat_id,
                author_id=str(sender_id),
                author_name=sender_email,
                content=content,
                is_bot=False,
                channel_name=chat_id,  # DM goes directly to first available agent
            )

        if self._msg_handler:
            await self._msg_handler(message)

    # ------------------------------------------------------------------
    # Internal: helpers
    # ------------------------------------------------------------------

    async def _resolve_streams(self):
        """Resolve stream names to IDs."""
        if not self._client:
            return
        try:
            result = self._client.get_streams()
            if result.get("result") == "success":
                streams = result.get("streams", [])
                for s in streams:
                    self._stream_id_cache[s["name"]] = s["stream_id"]
                    self._stream_name_cache[s["stream_id"]] = s["name"]
        except Exception as e:
            logger.warning("Could not resolve stream IDs: %s", e)

    def _resolve_stream_name(self, message: dict, stream_id: int) -> str:
        """Get stream name from cache or message payload."""
        if stream_id in self._stream_name_cache:
            return self._stream_name_cache[stream_id]
        dr = message.get("display_recipient")
        if isinstance(dr, str) and dr:
            return dr
        if isinstance(dr, dict):
            name = dr.get("name", "")
            if name:
                return name
        return str(stream_id)

    def _map_stream_to_channel(self, stream_name: str) -> str:
        """Reverse-map a Zulip stream name to an agent channel."""
        for channel, sname in self.stream_map.items():
            if sname == stream_name:
                return channel
        return stream_name  # fallback

    @staticmethod
    def _split_content(content: str, max_len: int) -> list[str]:
        """Split long content at natural boundaries."""
        if len(content) <= max_len:
            return [content]

        chunks = []
        while content:
            if len(content) <= max_len:
                chunks.append(content)
                break

            # Try to split at a natural boundary
            split_at = max_len
            # Look for double newline first (paragraph boundary)
            para = content.rfind("\n\n", 0, max_len)
            if para > max_len // 2:
                split_at = para + 2  # include the blank line
            else:
                # Look for single newline
                nl = content.rfind("\n", 0, max_len)
                if nl > max_len // 2:
                    split_at = nl + 1
                else:
                    # Look for space
                    sp = content.rfind(" ", 0, max_len)
                    if sp > max_len // 2:
                        split_at = sp + 1

            chunks.append(content[:split_at])
            content = content[split_at:]
        return chunks
