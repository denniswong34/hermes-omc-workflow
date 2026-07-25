"""
ChatAdapterHub — fan-in from multiple platforms; dispatch by channel → workflow.
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Optional

from adapters.base import ChannelAdapter, Message, MessageHandler

logger = logging.getLogger(__name__)


class ChatAdapterHub:
    """
    Owns platform adapters and routes inbound messages using
    (platform, channel_id) → workflow_id ownership map.
    """

    def __init__(self):
        self.adapters: dict[str, ChannelAdapter] = {}
        self._ownership: dict[tuple[str, str], str] = {}
        self._handler: Optional[Callable[[Message, str, str], None]] = None
        # handler(msg, platform, workflow_id)

    def set_ownership(self, mapping: dict[tuple[str, str], str]) -> None:
        self._ownership = dict(mapping)

    def on_routed_message(
        self, handler: Callable[[Message, str, str], None]
    ) -> None:
        self._handler = handler

    def register(self, platform: str, adapter: ChannelAdapter) -> None:
        self.adapters[platform] = adapter

        def _wrap(msg: Message, plat: str = platform):
            wf_id = self._ownership.get((plat, msg.channel_id))
            if not wf_id:
                logger.debug(
                    "No active workflow owns %s:%s — ignoring",
                    plat,
                    msg.channel_id,
                )
                return
            if self._handler:
                self._handler(msg, plat, wf_id)

        adapter.on_message(_wrap)

    async def start_all(self) -> None:
        for name, ad in self.adapters.items():
            logger.info("Starting adapter: %s", name)
            await ad.start()

    async def stop_all(self) -> None:
        for name, ad in self.adapters.items():
            logger.info("Stopping adapter: %s", name)
            await ad.stop()

    async def send(
        self, platform: str, channel_id: str, content: str
    ) -> Optional[str]:
        ad = self.adapters.get(platform)
        if not ad:
            logger.error("No adapter for platform %s", platform)
            return None
        return await ad.send_message(channel_id, content)


def build_default_hub(
    channel_maps: dict[str, dict[str, str]] | None = None,
) -> ChatAdapterHub:
    """
    Build hub with Discord/Slack/Zulip/Telegram from env credentials.
    channel_maps: platform -> {topic_name: external_id}
    """
    maps = channel_maps or {}
    hub = ChatAdapterHub()

    try:
        from adapters.discord_adapter import DiscordAdapter

        hub.register("discord", DiscordAdapter(channel_map=maps.get("discord") or {}))
    except Exception as e:
        logger.warning("Discord adapter unavailable: %s", e)

    try:
        from adapters.slack_adapter import SlackAdapter

        hub.register(
            "slack",
            SlackAdapter(
                bot_token=os.environ.get("SLACK_BOT_TOKEN", ""),
                app_token=os.environ.get("SLACK_APP_TOKEN", ""),
                channel_map=maps.get("slack") or {},
            ),
        )
    except Exception as e:
        logger.warning("Slack adapter unavailable: %s", e)

    try:
        from adapters.zulip_adapter import ZulipAdapter

        hub.register(
            "zulip",
            ZulipAdapter(stream_map=maps.get("zulip") or {}),
        )
    except Exception as e:
        logger.warning("Zulip adapter unavailable: %s", e)

    try:
        from adapters.telegram_adapter import TelegramAdapter

        hub.register(
            "telegram",
            TelegramAdapter(
                bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
                channel_map=maps.get("telegram") or {},
            ),
        )
    except Exception as e:
        logger.warning("Telegram adapter unavailable: %s", e)

    return hub
