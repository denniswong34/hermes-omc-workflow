"""
Channel Adapter — Abstract Base Class
======================================
Every communication channel (Discord, Zulip, Slack, etc.) implements this
interface so the bridge can switch transports without changing core logic.
"""

from abc import ABC, abstractmethod
from typing import Callable, Optional


class Message:
    """Normalised message from any channel."""

    def __init__(
        self,
        id: str,
        channel_id: str,
        author_id: str,
        author_name: str,
        content: str,
        is_bot: bool = False,
        reply_to_id: Optional[str] = None,
        channel_name: Optional[str] = None,
    ):
        self.id = id
        self.channel_id = channel_id
        self.author_id = author_id
        self.author_name = author_name
        self.content = content
        self.is_bot = is_bot
        self.reply_to_id = reply_to_id
        self.channel_name = channel_name

    def __repr__(self):
        return f"<Message id={self.id} ch={self.channel_id} author={self.author_name}>"


MessageHandler = Callable[[Message], None]


class ChannelAdapter(ABC):
    """Plug-in interface for a chat platform."""

    # ── Lifecycle ────────────────────────────────────────────────────

    @abstractmethod
    async def start(self):
        """Connect to the platform and begin listening for events."""

    @abstractmethod
    async def stop(self):
        """Gracefully disconnect."""

    # ── Message sending ──────────────────────────────────────────────

    @abstractmethod
    async def send_message(self, channel_id: str, content: str) -> Optional[str]:
        """Send a message. Returns the message ID on success."""

    @abstractmethod
    async def edit_message(self, channel_id: str, message_id: str, content: str) -> bool:
        """Edit an existing message. Returns True on success."""

    @abstractmethod
    async def send_typing(self, channel_id: str):
        """Send a typing indicator / ephemeral ack."""

    # ── Event registration ───────────────────────────────────────────

    @abstractmethod
    def on_message(self, handler: MessageHandler):
        """Register a callback for incoming user messages."""

    # ── Channel metadata (optional) ──────────────────────────────────

    def resolve_channel_name(self, channel_id: str) -> Optional[str]:
        """Return a human-friendly name for a channel ID."""
        return None
