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
        *,
        platform: str = "",
        bot_user_id: str = "",
        agent_id: str = "",
        target_role: str = "",
        is_dm: bool = False,
        bot_mentioned: bool = False,
    ):
        self.id = id
        self.channel_id = channel_id
        self.author_id = author_id
        self.author_name = author_name
        self.content = content
        self.is_bot = is_bot
        self.reply_to_id = reply_to_id
        self.channel_name = channel_name
        self.platform = platform
        self.bot_user_id = bot_user_id
        self.agent_id = agent_id
        self.target_role = target_role
        self.is_dm = is_dm
        self.bot_mentioned = bot_mentioned

    def __repr__(self):
        return f"<Message id={self.id} ch={self.channel_id} author={self.author_name}>"


MessageHandler = Callable[[Message], None]


class ChannelAdapter(ABC):
    """Plug-in interface for a chat platform."""

    #: Soft max characters per outbound message (adapters may split longer text).
    max_message_length: int = 1900

    # Optional identity metadata (set by multi-bot hub)
    agent_id: str = ""
    role_id: str = ""
    bot_user_id: str = ""

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
        """Send a message (may split). Returns the first message ID on success."""

    @abstractmethod
    async def edit_message(self, channel_id: str, message_id: str, content: str) -> bool:
        """Edit an existing message; overflow chunks are sent as new messages."""

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
