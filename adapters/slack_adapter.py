"""
Slack Channel Adapter — Bolt SDK + Socket Mode when available.
Falls back to logging stub if slack_bolt is not installed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from adapters.base import ChannelAdapter, Message, MessageHandler
from adapters.outbound import edit_with_split, send_with_split

logger = logging.getLogger(__name__)


class SlackAdapter(ChannelAdapter):
    """Adapter for Slack using Bolt SDK Socket Mode."""

    platform = "slack"
    max_message_length = 3900

    def __init__(
        self,
        bot_token: str,
        app_token: str,
        channel_map: dict[str, str] | None = None,
        *,
        agent_id: str = "",
        role_id: str = "",
    ):
        self.bot_token = bot_token
        self.app_token = app_token
        self.channel_map = channel_map or {}
        self.agent_id = agent_id or ""
        self.role_id = (role_id or "").lower()
        self.bot_user_id = ""
        self._msg_handler: Optional[MessageHandler] = None
        self._app = None
        self._handler = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def start(self):
        if not self.bot_token or not self.app_token:
            logger.warning("SlackAdapter: SLACK_BOT_TOKEN / SLACK_APP_TOKEN missing")
            return
        try:
            from slack_bolt.async_app import AsyncApp
            from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
        except ImportError:
            logger.warning(
                "slack_bolt not installed — SlackAdapter running in stub mode. "
                "pip install slack-bolt"
            )
            return

        self._loop = asyncio.get_running_loop()
        app = AsyncApp(token=self.bot_token)
        self._app = app

        try:
            auth = await app.client.auth_test()
            self.bot_user_id = str(auth.get("user_id") or "")
        except Exception as e:
            logger.warning("Slack auth_test failed: %s", e)

        @app.event("message")
        async def on_message(event, say):  # noqa: ARG001
            if event.get("subtype") or event.get("bot_id"):
                return
            if not self._msg_handler:
                return
            text = event.get("text") or ""
            channel_type = (event.get("channel_type") or "").lower()
            is_dm = channel_type in ("im", "mpim") or str(event.get("channel", "")).startswith("D")
            bot_mentioned = bool(self.bot_user_id and f"<@{self.bot_user_id}>" in text)
            if bot_mentioned and self.bot_user_id:
                text = text.replace(f"<@{self.bot_user_id}>", "").strip()
            msg = Message(
                id=event.get("ts", ""),
                channel_id=event.get("channel", ""),
                author_id=event.get("user", ""),
                author_name=event.get("user", "user"),
                content=text,
                is_bot=False,
                reply_to_id=event.get("thread_ts"),
                platform="slack",
                bot_user_id=self.bot_user_id,
                agent_id=self.agent_id,
                target_role=self.role_id,
                is_dm=is_dm,
                bot_mentioned=bot_mentioned or is_dm,
            )
            self._msg_handler(msg)

        self._handler = AsyncSocketModeHandler(app, self.app_token)
        logger.info(
            "SlackAdapter starting Socket Mode… agent=%s role=%s bot=%s",
            self.agent_id or "-",
            self.role_id or "-",
            self.bot_user_id or "-",
        )
        asyncio.create_task(self._handler.start_async())

    async def stop(self):
        if self._handler:
            try:
                await self._handler.close_async()
            except Exception:
                pass

    async def send_message(self, channel_id: str, content: str) -> Optional[str]:
        return await send_with_split(self, channel_id, content)

    async def edit_message(self, channel_id: str, message_id: str, content: str) -> bool:
        return await edit_with_split(self, channel_id, message_id, content)

    async def _deliver_message(self, channel_id: str, content: str) -> Optional[str]:
        if not self._app:
            logger.info("[Slack stub] send %s: %s", channel_id, content[:80])
            return None
        resp = await self._app.client.chat_postMessage(channel=channel_id, text=content)
        return resp.get("ts")

    async def _deliver_edit(
        self, channel_id: str, message_id: str, content: str
    ) -> bool:
        if not self._app:
            return True
        await self._app.client.chat_update(
            channel=channel_id, ts=message_id, text=content
        )
        return True

    async def send_typing(self, channel_id: str):
        pass

    def on_message(self, handler: MessageHandler):
        self._msg_handler = handler

    def resolve_channel_name(self, channel_id: str) -> Optional[str]:
        for name, cid in self.channel_map.items():
            if cid == channel_id:
                return name
        return None
