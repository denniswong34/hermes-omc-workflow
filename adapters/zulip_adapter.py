"""
Zulip Channel Adapter — Placeholder
=====================================
Implements ChannelAdapter for Zulip via its REST API + Events queue.
"""

import logging
from typing import Callable, Optional

from adapters.base import ChannelAdapter, Message, MessageHandler


class ZulipAdapter(ChannelAdapter):
    """Adapter for Zulip.  Uses the `zulip` PyPI package."""

    def __init__(self, zuliprc_path: str, stream_map: dict[str, str]):
        """
        stream_map: {agent_name: stream_name}
        e.g. {"#pm": "pm", "#sa": "sa"}
        """
        self.stream_map = stream_map
        self._msg_handler: Optional[MessageHandler] = None
        # TODO: self.client = zulip.Client(config_file=zuliprc_path)

    async def start(self):
        # TODO: Connect to Zulip, start event queue loop
        logging.warning("ZulipAdapter not yet implemented")

    async def stop(self):
        pass

    async def send_message(self, channel_id: str, content: str) -> Optional[str]:
        # stream_name = self.stream_map.get(channel_id, channel_id)
        # TODO: self.client.send_message(...)
        logging.info(f"[Zulip] Would send to {channel_id}: {content[:60]}")
        return None

    async def edit_message(self, channel_id: str, message_id: str, content: str) -> bool:
        logging.info(f"[Zulip] Would edit {message_id}: {content[:60]}")
        return True

    async def send_typing(self, channel_id: str):
        pass  # Zulip has no typing indicator API

    def on_message(self, handler: MessageHandler):
        self._msg_handler = handler
