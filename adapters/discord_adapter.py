"""
Discord Channel Adapter
========================
Implements ChannelAdapter using discord.py (REST API + Gateway).
"""

import asyncio
import logging
import os
from typing import Callable, Optional

import aiohttp
import discord
from discord.ext import commands

from adapters.base import ChannelAdapter, Message, MessageHandler


DISCORD_TOKEN = open(os.path.expanduser("~/.hermes/.env")).read() \
    .split("DISCORD_BOT_TOKEN=")[1].split("\n")[0].strip()
DISCORD_API = "https://discord.com/api/v10"


class DiscordAdapter(ChannelAdapter):
    """Adapter for Discord using discord.py gateway + REST fallback."""

    def __init__(self, channel_map: dict[str, str]):
        """
        channel_map: {channel_name: channel_id}
        e.g. {"#pm": "1528310140564934708"}
        """
        self.channel_map = channel_map
        self.name_by_id = {v: k for k, v in channel_map.items()}

        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True

        self.bot = commands.Bot(command_prefix="!", intents=intents)
        self._msg_handler: Optional[MessageHandler] = None
        self._http_session: Optional[aiohttp.ClientSession] = None

        # Wire up events
        @self.bot.event
        async def on_ready():
            logging.info(f"✓ Discord connected as {self.bot.user} ({self.bot.user.id})")
            for g in self.bot.guilds:
                logging.info(f"  Guild: {g.name} ({g.id})")

        @self.bot.event
        async def on_message(msg):
            if self._msg_handler is None:
                return
            channel_name = self.name_by_id.get(str(msg.channel.id))
            norm = Message(
                id=str(msg.id),
                channel_id=str(msg.channel.id),
                author_id=str(msg.author.id),
                author_name=str(msg.author),
                content=msg.content,
                is_bot=msg.author.bot,
                reply_to_id=str(msg.reference.message_id) if msg.reference else None,
                channel_name=channel_name,
            )
            # Handler may be sync or async
            if asyncio.iscoroutinefunction(self._msg_handler):
                await self._msg_handler(norm)
            else:
                self._msg_handler(norm)

        @self.bot.event
        async def on_error(event, *args):
            import traceback
            logging.error(f"Discord event error {event}: {traceback.format_exc()}")

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self):
        self._http_session = aiohttp.ClientSession()
        await self.bot.start(DISCORD_TOKEN)

    async def stop(self):
        if self._http_session:
            await self._http_session.close()
        await self.bot.close()

    # ── Sending ──────────────────────────────────────────────────────

    async def send_message(self, channel_id: str, content: str) -> Optional[str]:
        payload = {"content": str(content)[:1900]}
        result = await self._discord_api("POST", f"/channels/{channel_id}/messages", payload)
        if result and isinstance(result, dict) and "id" in result:
            return result["id"]
        return None

    async def edit_message(self, channel_id: str, message_id: str, content: str) -> bool:
        payload = {"content": str(content)[:1900]}
        result = await self._discord_api("PATCH", f"/channels/{channel_id}/messages/{message_id}", payload)
        return result is not None

    async def send_typing(self, channel_id: str):
        await self._discord_api("POST", f"/channels/{channel_id}/typing")

    # ── Events ───────────────────────────────────────────────────────

    def on_message(self, handler: MessageHandler):
        self._msg_handler = handler

    # ── Channel metadata ─────────────────────────────────────────────

    def resolve_channel_name(self, channel_id: str) -> Optional[str]:
        return self.name_by_id.get(channel_id)

    # ── Internal ─────────────────────────────────────────────────────

    async def _discord_api(self, method: str, endpoint: str, payload: dict = None):
        if not self._http_session:
            return None
        url = f"{DISCORD_API}{endpoint}"
        headers = {"Authorization": f"Bot {DISCORD_TOKEN}"}
        if payload:
            headers["Content-Type"] = "application/json"
        try:
            async with self._http_session.request(method, url, headers=headers, json=payload) as r:
                status = r.status
                if status not in (200, 201, 204):
                    err = await r.text()
                    logging.error(f"Discord API {method} {endpoint}: {status} {err[:200]}")
                    return None
                if status == 204:
                    return True
                return await r.json()
        except Exception as e:
            logging.error(f"Discord API error: {e}")
            return None
