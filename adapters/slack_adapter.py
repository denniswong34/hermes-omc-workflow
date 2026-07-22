"""
Slack Channel Adapter — Placeholder
=====================================
Implements ChannelAdapter for Slack via Bolt SDK + Socket Mode.
"""

import logging
from typing import Callable, Optional

from adapters.base import ChannelAdapter, Message, MessageHandler


class SlackAdapter(ChannelAdapter):
    """Adapter for Slack using Bolt SDK."""

    def __init__(self, bot_token: str, app_token: str, channel_map: dict[str, str]):
        """
        channel_map: {agent_name: channel_id}
        e.g. {"#pm": "C01..."}
        """
        self.channel_map = channel_map
        self._msg_handler: Optional[MessageHandler] = None
        # TODO: self.app = App(token=bot_token)

    async def start(self):
        logging.warning("SlackAdapter not yet implemented")

    async def stop(self):
        pass

    async def send_message(self, channel_id: str, content: str) -> Optional[str]:
        logging.info(f"[Slack] Would send to {channel_id}: {content[:60]}")
        return None

    async def edit_message(self, channel_id: str, message_id: str, content: str) -> bool:
        logging.info(f"[Slack] Would edit {message_id}")
        return True

    async def send_typing(self, channel_id: str):
        pass

    def on_message(self, handler: MessageHandler):
        self._msg_handler = handler
