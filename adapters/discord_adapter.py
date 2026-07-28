"""
Discord Channel Adapter
========================
Implements ChannelAdapter using discord.py (REST API + Gateway).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Callable, Optional

import aiohttp
import discord
from discord.ext import commands

from adapters.base import ChannelAdapter, Message, MessageHandler
from adapters.outbound import edit_with_split, send_with_split
from core.chat_messages import is_bot_own_message


DISCORD_API = "https://discord.com/api/v10"
logger = logging.getLogger(__name__)

# Bots cannot list DM channels via GET /users/@me/channels — persist ids we see.
_DM_CHANNELS_PATH = Path(
    os.path.expanduser("~/.hermes/omc/discord_dm_channels.json")
)


def _load_dm_channels() -> dict[str, list[str]]:
    try:
        if _DM_CHANNELS_PATH.exists():
            raw = _DM_CHANNELS_PATH.read_text(encoding="utf-8-sig")
            data = json.loads(raw)
            if isinstance(data, dict):
                return {
                    str(k): [str(x) for x in (v or []) if x]
                    for k, v in data.items()
                    if isinstance(v, list)
                }
    except Exception as e:
        logger.warning("DM channel registry load failed: %s", e)
    return {}


def _remember_dm_channel(agent_key: str, channel_id: str) -> None:
    key = (agent_key or "").strip() or "default"
    cid = str(channel_id or "").strip()
    if not cid:
        return
    try:
        _DM_CHANNELS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = _load_dm_channels()
        existing = data.get(key) or []
        if cid in existing:
            return
        data[key] = (existing + [cid])[-30:]
        _DM_CHANNELS_PATH.write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.debug("DM channel remember failed: %s", e)


def _discord_token() -> str:
    token = (os.environ.get("DISCORD_BOT_TOKEN") or "").strip()
    if token:
        return token
    env_path = Path(os.path.expanduser("~/.hermes/.env"))
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("DISCORD_BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError(
        "DISCORD_BOT_TOKEN not set (workflow secrets or ~/.hermes/.env)"
    )


def _build_intents(*, message_content: bool) -> discord.Intents:
    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.dm_messages = True
    intents.message_content = bool(message_content)
    return intents


class DiscordAdapter(ChannelAdapter):
    """Adapter for Discord using discord.py gateway + REST fallback."""

    max_message_length = 1900
    platform = "discord"

    def __init__(
        self,
        channel_map: dict[str, str] | None = None,
        *,
        bot_token: str | None = None,
        agent_id: str = "",
        role_id: str = "",
    ):
        """
        channel_map: {channel_name: channel_id}
        e.g. {"#pm": "1528310140564934708"}
        """
        self.channel_map = channel_map or {}
        self.name_by_id = {v: k for k, v in self.channel_map.items()}
        self._token = (bot_token or "").strip() or _discord_token()
        self.agent_id = agent_id or ""
        self.role_id = (role_id or "").lower()
        self.bot_user_id = ""
        self._message_content = True

        self._msg_handler: Optional[MessageHandler] = None
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._ready = asyncio.Event()
        self._run_task: Optional[asyncio.Task] = None
        self.bot = self._make_bot(message_content=True)

    def _make_bot(self, *, message_content: bool) -> commands.Bot:
        self._message_content = message_content
        bot = commands.Bot(
            command_prefix="!",
            intents=_build_intents(message_content=message_content),
        )

        @bot.event
        async def on_ready():
            if bot.user:
                self.bot_user_id = str(bot.user.id)
            try:
                await bot.change_presence(
                    status=discord.Status.online,
                    activity=discord.Activity(
                        type=discord.ActivityType.listening,
                        name=f"@{self.role_id or 'agent'} DMs",
                    ),
                )
            except Exception as e:
                logger.debug("Discord presence update failed: %s", e)
            logging.info(
                "[ok] Discord connected as %s (%s) agent=%s role=%s message_content=%s",
                bot.user,
                self.bot_user_id,
                self.agent_id or "-",
                self.role_id or "-",
                self._message_content,
            )
            for g in bot.guilds:
                logging.info("  Guild: %s (%s)", g.name, g.id)
            if not self._ready.is_set():
                self._ready.set()
            # Replay recent unanswered DMs (Discord does not queue while offline).
            asyncio.create_task(
                self._catch_up_dms(),
                name=f"discord-dm-catchup:{self.role_id or self.agent_id or 'bot'}",
            )

        @bot.event
        async def on_message(msg):
            await self._handle_discord_message(msg)

        @bot.event
        async def on_error(event, *args):
            import traceback

            logging.error("Discord event error %s: %s", event, traceback.format_exc())

        return bot

    async def _handle_discord_message(self, msg) -> None:
        if self._msg_handler is None:
            return
        # Ignore our own messages
        if self.bot.user and msg.author.id == self.bot.user.id:
            return

        is_dm = isinstance(msg.channel, discord.DMChannel) or getattr(
            msg.channel, "guild", None
        ) is None
        bot_mentioned = False
        content = msg.content or ""
        if self.bot.user and self.bot.user.mentioned_in(msg):
            bot_mentioned = True
            content = re.sub(
                rf"<@!?{self.bot.user.id}>", "", content
            ).strip()

        if is_dm:
            logging.info(
                "Discord DM received role=%s agent=%s from=%s content=%r",
                self.role_id or "-",
                self.agent_id or "-",
                msg.author,
                (content or "")[:120],
            )
            _remember_dm_channel(
                self.agent_id or self.role_id or self.bot_user_id,
                str(msg.channel.id),
            )

        # Multi-bot: each client sees every guild message. Prefer this bot's
        # @role / @bot / DM. Still forward unknown @roles so a bot with
        # Message Content Intent can cover agents whose gateway failed.
        if (
            not is_dm
            and not bot_mentioned
            and self.role_id
            and not re.search(rf"(?i)@{re.escape(self.role_id)}\b", content or "")
            and not re.search(r"(?i)@[A-Za-z][A-Za-z0-9_-]*\b", content or "")
        ):
            return
        # If message @mentions another role exclusively, skip when we can
        # determine this adapter is not the target (reduces fan-out).
        if (
            not is_dm
            and not bot_mentioned
            and self.role_id
            and re.search(r"(?i)@[A-Za-z][A-Za-z0-9_-]*\b", content or "")
            and not re.search(rf"(?i)@{re.escape(self.role_id)}\b", content or "")
        ):
            # Allow one designated ingress role (pm) to cover missing bots.
            if self.role_id != "pm":
                return

        channel_id = str(msg.channel.id)
        channel_name = self.name_by_id.get(channel_id)
        if is_dm:
            channel_name = channel_name or "dm"

        norm = Message(
            id=str(msg.id),
            channel_id=channel_id,
            author_id=str(msg.author.id),
            author_name=str(msg.author),
            content=content,
            is_bot=msg.author.bot,
            reply_to_id=str(msg.reference.message_id) if msg.reference else None,
            channel_name=channel_name,
            platform="discord",
            bot_user_id=self.bot_user_id or (str(self.bot.user.id) if self.bot.user else ""),
            agent_id=self.agent_id,
            target_role=self.role_id,
            is_dm=is_dm,
            bot_mentioned=bot_mentioned,
        )
        if asyncio.iscoroutinefunction(self._msg_handler):
            await self._msg_handler(norm)
        else:
            self._msg_handler(norm)

    async def _catch_up_dms(self) -> None:
        """
        After reconnect, answer the latest unanswered human DM per channel.

        Discord does not deliver MESSAGE_CREATE events that happened while the
        gateway was down, so offline DMs would otherwise stay silent forever.
        """
        logging.info(
            "Discord DM catch-up scheduled role=%s agent=%s",
            self.role_id or "-",
            self.agent_id or "-",
        )
        await asyncio.sleep(2)
        if self._msg_handler is None or not self._http_session:
            logging.warning(
                "Discord DM catch-up skipped role=%s (handler=%s session=%s)",
                self.role_id or "-",
                bool(self._msg_handler),
                bool(self._http_session),
            )
            return

        channel_ids: list[str] = []
        # Gateway cache (often empty for bots until traffic flows)
        try:
            for ch in list(getattr(self.bot, "private_channels", []) or []):
                cid = str(getattr(ch, "id", "") or "")
                if cid:
                    channel_ids.append(cid)
        except Exception:
            pass
        # Persisted ids — Discord REST does not list bot DM channels.
        agent_key = self.agent_id or self.role_id or self.bot_user_id
        for cid in _load_dm_channels().get(agent_key, []):
            if cid not in channel_ids:
                channel_ids.append(cid)
        # Also try role-keyed entries from older runs
        if self.role_id:
            for cid in _load_dm_channels().get(self.role_id, []):
                if cid not in channel_ids:
                    channel_ids.append(cid)

        if not channel_ids:
            logging.info(
                "Discord DM catch-up: no known DM channels for role=%s",
                self.role_id or "-",
            )
            return

        bot_id = self.bot_user_id or (
            str(self.bot.user.id) if self.bot.user else ""
        )
        for channel_id in channel_ids:
            try:
                msgs = await self._discord_api(
                    "GET", f"/channels/{channel_id}/messages?limit=10"
                )
            except Exception:
                continue
            if not isinstance(msgs, list) or not msgs:
                continue
            # API returns newest-first. Replay newest human DM unless a real
            # agent-formatted reply already followed it.
            pending = None
            for m in msgs:
                author = m.get("author") or {}
                is_self = str(author.get("id") or "") == bot_id or bool(
                    author.get("bot")
                )
                body = m.get("content") or ""
                if is_self:
                    if pending is not None and is_bot_own_message(body):
                        pending = None
                    continue
                text = body.strip()
                if text:
                    pending = m
                    break
            if not pending:
                continue
            author = pending.get("author") or {}
            content = (pending.get("content") or "").strip()
            logging.info(
                "Discord DM catch-up role=%s channel=%s from=%s content=%r",
                self.role_id or "-",
                channel_id,
                author.get("username") or author.get("id"),
                content[:120],
            )
            _remember_dm_channel(agent_key, channel_id)
            norm = Message(
                id=str(pending.get("id") or f"catchup-{channel_id}"),
                channel_id=channel_id,
                author_id=str(author.get("id") or ""),
                author_name=str(author.get("username") or "user"),
                content=content,
                is_bot=False,
                channel_name="dm",
                platform="discord",
                bot_user_id=bot_id,
                agent_id=self.agent_id,
                target_role=self.role_id,
                is_dm=True,
                bot_mentioned=False,
            )
            try:
                if asyncio.iscoroutinefunction(self._msg_handler):
                    await self._msg_handler(norm)
                else:
                    self._msg_handler(norm)
            except Exception:
                logging.exception(
                    "Discord DM catch-up handler failed role=%s channel=%s",
                    self.role_id or "-",
                    channel_id,
                )

    async def _run_gateway(self) -> None:
        """Keep the gateway up; fall back if Message Content Intent is missing."""
        try:
            await self.bot.start(self._token)
            return
        except discord.errors.PrivilegedIntentsRequired:
            if not self._message_content:
                raise
            logging.warning(
                "Discord PrivilegedIntentsRequired for role=%s agent=%s — "
                "retrying without message_content (DMs + @mentions still work). "
                "Enable Message Content Intent for this app in the Discord "
                "Developer Portal for full guild message text.",
                self.role_id or "-",
                self.agent_id or "-",
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception(
                "Discord gateway crashed role=%s agent=%s",
                self.role_id or "-",
                self.agent_id or "-",
            )
            raise

        # Rebuild without privileged message_content and reconnect.
        try:
            if not self.bot.is_closed():
                await self.bot.close()
        except Exception:
            pass
        self.bot = self._make_bot(message_content=False)
        await self.bot.start(self._token)

    async def start(self):
        """Connect the Discord gateway without blocking other adapters."""
        self._http_session = aiohttp.ClientSession()
        self._ready = asyncio.Event()
        self._run_task = asyncio.create_task(
            self._run_gateway(),
            name=f"discord-gateway:{self.role_id or self.agent_id or 'bot'}",
        )

        def _done(task: asyncio.Task) -> None:
            if task.cancelled():
                return
            exc = task.exception()
            if exc:
                logging.error(
                    "Discord gateway task ended role=%s agent=%s: %s",
                    self.role_id or "-",
                    self.agent_id or "-",
                    exc,
                )

        self._run_task.add_done_callback(_done)
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=35)
        except asyncio.TimeoutError as e:
            await self.stop()
            raise RuntimeError(
                f"Discord bot failed to become ready "
                f"(role={self.role_id or '-'} agent={self.agent_id or '-'})"
            ) from e

    async def stop(self):
        if self._http_session:
            try:
                await self._http_session.close()
            except Exception:
                pass
            self._http_session = None
        try:
            if not self.bot.is_closed():
                await self.bot.close()
        except Exception as e:
            logging.warning("Discord bot close error: %s", e)
        if self._run_task is not None and not self._run_task.done():
            try:
                await asyncio.wait_for(self._run_task, timeout=15)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                self._run_task.cancel()
        self._run_task = None

    async def send_message(self, channel_id: str, content: str) -> Optional[str]:
        return await send_with_split(self, channel_id, content)

    async def edit_message(self, channel_id: str, message_id: str, content: str) -> bool:
        return await edit_with_split(self, channel_id, message_id, content)

    async def _deliver_message(self, channel_id: str, content: str) -> Optional[str]:
        payload = {"content": str(content)}
        result = await self._discord_api(
            "POST", f"/channels/{channel_id}/messages", payload
        )
        if result and isinstance(result, dict) and "id" in result:
            return result["id"]
        return None

    async def _deliver_edit(
        self, channel_id: str, message_id: str, content: str
    ) -> bool:
        payload = {"content": str(content)}
        result = await self._discord_api(
            "PATCH",
            f"/channels/{channel_id}/messages/{message_id}",
            payload,
        )
        return result is not None

    async def send_typing(self, channel_id: str):
        await self._discord_api("POST", f"/channels/{channel_id}/typing")

    def on_message(self, handler: MessageHandler):
        self._msg_handler = handler

    def resolve_channel_name(self, channel_id: str) -> Optional[str]:
        return self.name_by_id.get(channel_id)

    async def _discord_api(self, method: str, endpoint: str, payload: dict = None):
        if not self._http_session:
            return None
        url = f"{DISCORD_API}{endpoint}"
        headers = {"Authorization": f"Bot {self._token}"}
        if payload:
            headers["Content-Type"] = "application/json"
        try:
            async with self._http_session.request(
                method, url, headers=headers, json=payload
            ) as r:
                status = r.status
                if status not in (200, 201, 204):
                    err = await r.text()
                    logging.error(
                        "Discord API %s %s: %s %s", method, endpoint, status, err[:200]
                    )
                    return None
                if status == 204:
                    return True
                return await r.json()
        except Exception as e:
            logging.error("Discord API error: %s", e)
            return None
