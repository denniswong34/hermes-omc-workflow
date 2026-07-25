"""
Telegram Channel Adapter — long-polling via Bot API (aiohttp).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

from adapters.base import ChannelAdapter, Message, MessageHandler
from adapters.outbound import edit_with_split, send_with_split

logger = logging.getLogger(__name__)


class TelegramAdapter(ChannelAdapter):
    platform = "telegram"
    max_message_length = 4000

    def __init__(
        self,
        bot_token: str,
        channel_map: dict[str, str] | None = None,
    ):
        self.bot_token = bot_token
        self.channel_map = channel_map or {}
        self._msg_handler: Optional[MessageHandler] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._offset = 0
        self._base = f"https://api.telegram.org/bot{bot_token}"

    async def start(self):
        if not self.bot_token:
            logger.warning("TelegramAdapter: TELEGRAM_BOT_TOKEN missing")
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("TelegramAdapter polling started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self):
        async with aiohttp.ClientSession() as session:
            while self._running:
                try:
                    async with session.get(
                        f"{self._base}/getUpdates",
                        params={"offset": self._offset, "timeout": 30},
                        timeout=aiohttp.ClientTimeout(total=35),
                    ) as resp:
                        data = await resp.json()
                    if not data.get("ok"):
                        await asyncio.sleep(2)
                        continue
                    for upd in data.get("result") or []:
                        self._offset = max(self._offset, upd["update_id"] + 1)
                        msg = upd.get("message") or upd.get("edited_message")
                        if not msg or not self._msg_handler:
                            continue
                        chat = msg.get("chat") or {}
                        user = msg.get("from") or {}
                        if user.get("is_bot"):
                            continue
                        m = Message(
                            id=str(msg.get("message_id", "")),
                            channel_id=str(chat.get("id", "")),
                            author_id=str(user.get("id", "")),
                            author_name=user.get("username")
                            or user.get("first_name")
                            or "user",
                            content=msg.get("text") or "",
                            is_bot=False,
                            reply_to_id=str(
                                (msg.get("reply_to_message") or {}).get("message_id") or ""
                            )
                            or None,
                            channel_name=chat.get("title") or chat.get("username"),
                        )
                        self._msg_handler(m)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("Telegram poll error: %s", e)
                    await asyncio.sleep(3)

    async def send_message(self, channel_id: str, content: str) -> Optional[str]:
        return await send_with_split(self, channel_id, content)

    async def edit_message(self, channel_id: str, message_id: str, content: str) -> bool:
        return await edit_with_split(self, channel_id, message_id, content)

    async def _deliver_message(self, channel_id: str, content: str) -> Optional[str]:
        if not self.bot_token:
            logger.info("[Telegram stub] %s: %s", channel_id, content[:80])
            return None
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._base}/sendMessage",
                json={"chat_id": channel_id, "text": content},
            ) as resp:
                data = await resp.json()
        if data.get("ok"):
            return str(data["result"]["message_id"])
        logger.error("Telegram send failed: %s", data)
        return None

    async def _deliver_edit(
        self, channel_id: str, message_id: str, content: str
    ) -> bool:
        if not self.bot_token:
            return True
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self._base}/editMessageText",
                json={
                    "chat_id": channel_id,
                    "message_id": int(message_id),
                    "text": content,
                },
            ) as resp:
                data = await resp.json()
        return bool(data.get("ok"))

    async def send_typing(self, channel_id: str):
        if not self.bot_token:
            return
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"{self._base}/sendChatAction",
                    json={"chat_id": channel_id, "action": "typing"},
                )
        except Exception:
            pass

    def on_message(self, handler: MessageHandler):
        self._msg_handler = handler

    def resolve_channel_name(self, channel_id: str) -> Optional[str]:
        for name, cid in self.channel_map.items():
            if str(cid) == str(channel_id):
                return name
        return None
