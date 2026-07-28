"""
ChatAdapterHub — fan-in from multiple platforms / per-agent bots;
dispatch by channel → workflow and bot_user_id → agent.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

from adapters.base import ChannelAdapter, Message, MessageHandler

logger = logging.getLogger(__name__)


class ChatAdapterHub:
    """
    Owns platform adapters (legacy one-per-platform and per-agent bots).
    Routes inbound messages using:
      - (platform, channel_id) → workflow_id
      - (platform, bot_user_id) → agent ownership (DMs / bot mentions)
    """

    def __init__(self):
        # adapter_key → adapter  (key is platform or f"{platform}:{agent_id}")
        self.adapters: dict[str, ChannelAdapter] = {}
        self._ownership: dict[tuple[str, str], str] = {}
        # (platform, bot_user_id|agent_id) → {workflow_id, agent_id, role_id}
        self._bot_ownership: dict[tuple[str, str], dict[str, str]] = {}
        self._agent_adapter_keys: dict[tuple[str, str], str] = {}
        self._handler: Optional[Callable[[Message, str, str], None]] = None
        # handler(msg, platform, workflow_id)

    def set_ownership(self, mapping: dict[tuple[str, str], str]) -> None:
        self._ownership = dict(mapping)

    def set_bot_ownership(self, mapping: dict[tuple[str, str], dict[str, str]]) -> None:
        """Map (platform, bot_user_id) → {workflow_id, agent_id, role_id}."""
        self._bot_ownership = dict(mapping)

    def register_bot_owner(
        self,
        platform: str,
        *,
        bot_user_id: str = "",
        agent_id: str = "",
        workflow_id: str = "",
        role_id: str = "",
    ) -> None:
        meta = {
            "workflow_id": workflow_id,
            "agent_id": agent_id,
            "role_id": (role_id or "").lower(),
        }
        if bot_user_id:
            self._bot_ownership[(platform, str(bot_user_id))] = meta
        if agent_id:
            self._bot_ownership[(platform, f"agent:{agent_id}")] = meta

    def on_routed_message(
        self, handler: Callable[[Message, str, str], None]
    ) -> None:
        self._handler = handler

    def register(
        self,
        platform: str,
        adapter: ChannelAdapter,
        *,
        agent_id: str = "",
        workflow_id: str = "",
        role_id: str = "",
    ) -> str:
        key = f"{platform}:{agent_id}" if agent_id else platform
        self.adapters[key] = adapter
        if agent_id:
            self._agent_adapter_keys[(platform, agent_id)] = key
            adapter.agent_id = agent_id
            adapter.role_id = (role_id or "").lower()

        def _wrap(msg: Message, plat: str = platform, ad: ChannelAdapter = adapter):
            # Enrich from adapter identity if missing
            if not msg.platform:
                msg.platform = plat
            if not msg.bot_user_id and getattr(ad, "bot_user_id", ""):
                msg.bot_user_id = str(ad.bot_user_id)
            if not msg.agent_id and getattr(ad, "agent_id", ""):
                msg.agent_id = str(ad.agent_id)
            if not msg.target_role and getattr(ad, "role_id", ""):
                msg.target_role = str(ad.role_id).lower()

            # Refresh bot ownership once bot_user_id is known
            if msg.bot_user_id and msg.agent_id and workflow_id:
                self.register_bot_owner(
                    plat,
                    bot_user_id=msg.bot_user_id,
                    agent_id=msg.agent_id,
                    workflow_id=workflow_id,
                    role_id=msg.target_role or role_id,
                )

            wf_id = self._ownership.get((plat, msg.channel_id))
            if not wf_id and (msg.is_dm or msg.bot_mentioned):
                owner = None
                if msg.bot_user_id:
                    owner = self._bot_ownership.get((plat, msg.bot_user_id))
                if not owner and msg.agent_id:
                    owner = self._bot_ownership.get((plat, f"agent:{msg.agent_id}"))
                if owner:
                    wf_id = owner.get("workflow_id") or ""
                    if owner.get("role_id") and not msg.target_role:
                        msg.target_role = owner["role_id"]
                    if owner.get("agent_id") and not msg.agent_id:
                        msg.agent_id = owner["agent_id"]

            if not wf_id:
                if msg.is_dm or msg.bot_mentioned:
                    logger.warning(
                        "No workflow owner for %s %s bot=%s agent=%s role=%s — ignoring",
                        plat,
                        "DM" if msg.is_dm else "mention",
                        msg.bot_user_id or "-",
                        msg.agent_id or "-",
                        msg.target_role or "-",
                    )
                else:
                    logger.debug(
                        "No active workflow owns %s:%s — ignoring",
                        plat,
                        msg.channel_id,
                    )
                return
            if self._handler:
                self._handler(msg, plat, wf_id)

        adapter.on_message(_wrap)
        if agent_id and workflow_id:
            self.register_bot_owner(
                platform,
                bot_user_id=getattr(adapter, "bot_user_id", "") or "",
                agent_id=agent_id,
                workflow_id=workflow_id,
                role_id=role_id,
            )
        return key

    async def start_all(self) -> None:
        # Start adapters sequentially but DiscordAdapter.start() returns once
        # the gateway is ready (background task keeps the connection alive).
        for name, ad in list(self.adapters.items()):
            logger.info("Starting adapter: %s", name)
            try:
                await ad.start()
                # After start, bot_user_id may be known
                agent_id = getattr(ad, "agent_id", "") or ""
                bot_uid = getattr(ad, "bot_user_id", "") or ""
                if agent_id and bot_uid:
                    platform = name.split(":", 1)[0]
                    owner = self._bot_ownership.get((platform, f"agent:{agent_id}"))
                    if owner:
                        self.register_bot_owner(
                            platform,
                            bot_user_id=bot_uid,
                            agent_id=agent_id,
                            workflow_id=owner.get("workflow_id", ""),
                            role_id=owner.get("role_id", ""),
                        )
            except Exception as e:
                logger.error("Adapter %s failed to start: %s", name, e)
                self.adapters.pop(name, None)

    async def stop_all(self) -> None:
        for name, ad in list(self.adapters.items()):
            logger.info("Stopping adapter: %s", name)
            try:
                await ad.stop()
            except Exception as e:
                logger.warning("Adapter %s stop error: %s", name, e)

    async def send(
        self, platform: str, channel_id: str, content: str
    ) -> Optional[str]:
        ad = self.adapters.get(platform)
        if not ad:
            # Prefer any agent adapter for that platform
            for key, candidate in self.adapters.items():
                if key == platform or key.startswith(f"{platform}:"):
                    ad = candidate
                    break
        if not ad:
            logger.error("No adapter for platform %s", platform)
            return None
        return await ad.send_message(channel_id, content)

    async def send_as(
        self,
        agent_id: str,
        platform: str,
        channel_id: str,
        content: str,
    ) -> Optional[str]:
        """Send as a specific agent's bot; fall back to legacy platform adapter."""
        key = self._agent_adapter_keys.get((platform, agent_id))
        ad = self.adapters.get(key) if key else None
        if not ad:
            ad = self.adapters.get(platform)
        if not ad:
            for k, candidate in self.adapters.items():
                if k.startswith(f"{platform}:"):
                    ad = candidate
                    break
        if not ad:
            logger.error("No adapter for send_as agent=%s platform=%s", agent_id, platform)
            return None
        return await ad.send_message(channel_id, content)

    def adapter_for_agent(self, platform: str, agent_id: str) -> Optional[ChannelAdapter]:
        key = self._agent_adapter_keys.get((platform, agent_id))
        if key:
            return self.adapters.get(key)
        return self.adapters.get(platform)

    def adapters_by_role(self, platform: str) -> dict[str, ChannelAdapter]:
        """role_id → adapter for a platform (agent bots + legacy)."""
        out: dict[str, ChannelAdapter] = {}
        for key, ad in self.adapters.items():
            if key != platform and not key.startswith(f"{platform}:"):
                continue
            role = (getattr(ad, "role_id", "") or "").lower()
            if role:
                out[role] = ad
        return out


def build_default_hub(
    channel_maps: dict[str, dict[str, str]] | None = None,
) -> ChatAdapterHub:
    """
    Build hub with Discord/Slack/Zulip/Telegram from env credentials.
    channel_maps: platform -> {topic_name: external_id}
    Only registers adapters that have credentials / channel maps.
    """
    maps = channel_maps or {}
    hub = ChatAdapterHub()

    discord_token = (os.environ.get("DISCORD_BOT_TOKEN") or "").strip()
    if discord_token or maps.get("discord"):
        try:
            from adapters.discord_adapter import DiscordAdapter

            hub.register(
                "discord",
                DiscordAdapter(
                    channel_map=maps.get("discord") or {},
                    bot_token=discord_token or None,
                ),
            )
        except Exception as e:
            logger.warning("Discord adapter unavailable: %s", e)

    slack_bot = (os.environ.get("SLACK_BOT_TOKEN") or "").strip()
    slack_app = (os.environ.get("SLACK_APP_TOKEN") or "").strip()
    if slack_bot and slack_app:
        try:
            from adapters.slack_adapter import SlackAdapter

            hub.register(
                "slack",
                SlackAdapter(
                    bot_token=slack_bot,
                    app_token=slack_app,
                    channel_map=maps.get("slack") or {},
                ),
            )
        except Exception as e:
            logger.warning("Slack adapter unavailable: %s", e)

    zulip_key = (
        (os.environ.get("ZULIP_API_KEY") or "").strip()
        or (os.environ.get("ZULIP_SITE") or "").strip()
        or (os.environ.get("ZULIP_SITE_URL") or "").strip()
    )
    if zulip_key and maps.get("zulip"):
        try:
            from adapters.zulip_adapter import ZulipAdapter

            hub.register(
                "zulip",
                ZulipAdapter(stream_map=maps.get("zulip") or {}),
            )
        except Exception as e:
            logger.warning("Zulip adapter unavailable: %s", e)

    telegram_token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if telegram_token:
        try:
            from adapters.telegram_adapter import TelegramAdapter

            hub.register(
                "telegram",
                TelegramAdapter(
                    bot_token=telegram_token,
                    channel_map=maps.get("telegram") or {},
                ),
            )
        except Exception as e:
            logger.warning("Telegram adapter unavailable: %s", e)

    return hub


def build_multi_bot_hub(
    active_workflows: list[Any],
    channel_maps: dict[str, dict[str, str]] | None = None,
) -> ChatAdapterHub:
    """
    Build hub from per-agent gateway credentials of active workflows,
    with legacy env/chat-connection bots as fallback.
    """
    from core.secrets import (
        agent_has_gateway_credentials,
        resolve_agent_gateway_credentials,
    )

    maps = channel_maps or {}

    # Collect agent gateway specs first so we can skip legacy platforms that
    # would collide on the same bot token.
    agent_specs: list[dict[str, Any]] = []
    agent_platforms: set[str] = set()
    for wf in active_workflows:
        wf_id = getattr(wf, "id", None) or (wf.get("id") if isinstance(wf, dict) else None)
        agents = getattr(wf, "agents", None) or (wf.get("agents") if isinstance(wf, dict) else None) or []
        for ag in agents:
            if isinstance(ag, dict):
                agent_id = ag.get("id")
                role_id = (ag.get("role_id") or "").lower()
                identity = ag.get("platform_identity") or {}
            else:
                agent_id = getattr(ag, "id", None)
                role_id = (getattr(ag, "role_id", None) or "").lower()
                identity = getattr(ag, "platform_identity", None) or {}
            for platform in ("discord", "telegram", "slack", "zulip"):
                if not agent_has_gateway_credentials(
                    wf_id, agent_id, platform, identity
                ):
                    continue
                creds = resolve_agent_gateway_credentials(
                    wf_id, agent_id, platform, identity
                )
                if not any(str(v or "").strip() for v in creds.values()):
                    continue
                agent_platforms.add(platform)
                agent_specs.append(
                    {
                        "platform": platform,
                        "creds": creds,
                        "agent_id": agent_id,
                        "workflow_id": wf_id,
                        "role_id": role_id,
                        "identity": identity.get(platform) or {},
                    }
                )

    # Legacy env bots only for platforms with no per-agent gateway yet
    saved_env: dict[str, str] = {}
    env_keys = {
        "discord": ["DISCORD_BOT_TOKEN"],
        "telegram": ["TELEGRAM_BOT_TOKEN"],
        "slack": ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"],
        "zulip": ["ZULIP_API_KEY", "ZULIP_SITE", "ZULIP_SITE_URL", "ZULIP_EMAIL", "ZULIP_BOT_EMAIL"],
    }
    for platform, keys in env_keys.items():
        if platform not in agent_platforms:
            continue
        for k in keys:
            if k in os.environ:
                saved_env[k] = os.environ.pop(k)

    try:
        hub = build_default_hub(maps)
    finally:
        os.environ.update(saved_env)

    seen_tokens: set[str] = set()
    for spec in agent_specs:
        creds = spec["creds"]
        token_fp = "|".join(f"{k}={creds.get(k, '')}" for k in sorted(creds))
        if token_fp in seen_tokens:
            continue
        seen_tokens.add(token_fp)
        try:
            _register_agent_adapter(
                hub,
                platform=spec["platform"],
                creds=creds,
                channel_map=maps.get(spec["platform"]) or {},
                agent_id=spec["agent_id"],
                workflow_id=spec["workflow_id"],
                role_id=spec["role_id"],
                identity=spec["identity"],
            )
        except Exception as e:
            logger.warning(
                "Agent gateway %s/%s unavailable: %s",
                spec["platform"],
                spec["role_id"],
                e,
            )
    return hub


def _register_agent_adapter(
    hub: ChatAdapterHub,
    *,
    platform: str,
    creds: dict[str, str],
    channel_map: dict[str, str],
    agent_id: str,
    workflow_id: str,
    role_id: str,
    identity: dict[str, Any],
) -> None:
    bot_user_id = str(identity.get("bot_user_id") or "")
    if platform == "discord":
        from adapters.discord_adapter import DiscordAdapter

        token = (creds.get("DISCORD_BOT_TOKEN") or "").strip()
        if not token:
            return
        hub.register(
            "discord",
            DiscordAdapter(
                channel_map=channel_map,
                bot_token=token,
                agent_id=agent_id,
                role_id=role_id,
            ),
            agent_id=agent_id,
            workflow_id=workflow_id,
            role_id=role_id,
        )
    elif platform == "telegram":
        from adapters.telegram_adapter import TelegramAdapter

        token = (creds.get("TELEGRAM_BOT_TOKEN") or "").strip()
        if not token:
            return
        hub.register(
            "telegram",
            TelegramAdapter(
                bot_token=token,
                channel_map=channel_map,
                agent_id=agent_id,
                role_id=role_id,
            ),
            agent_id=agent_id,
            workflow_id=workflow_id,
            role_id=role_id,
        )
    elif platform == "slack":
        from adapters.slack_adapter import SlackAdapter

        bot = (creds.get("SLACK_BOT_TOKEN") or "").strip()
        app = (creds.get("SLACK_APP_TOKEN") or "").strip()
        if not (bot and app):
            return
        hub.register(
            "slack",
            SlackAdapter(
                bot_token=bot,
                app_token=app,
                channel_map=channel_map,
                agent_id=agent_id,
                role_id=role_id,
            ),
            agent_id=agent_id,
            workflow_id=workflow_id,
            role_id=role_id,
        )
    elif platform == "zulip":
        from adapters.zulip_adapter import ZulipAdapter

        site = (creds.get("ZULIP_SITE") or "").strip()
        email = (creds.get("ZULIP_EMAIL") or "").strip()
        key = (creds.get("ZULIP_API_KEY") or "").strip()
        if not (site and email and key):
            return
        hub.register(
            "zulip",
            ZulipAdapter(
                stream_map=channel_map,
                site=site,
                email=email,
                api_key=key,
                agent_id=agent_id,
                role_id=role_id,
            ),
            agent_id=agent_id,
            workflow_id=workflow_id,
            role_id=role_id,
        )
    if bot_user_id:
        hub.register_bot_owner(
            platform,
            bot_user_id=bot_user_id,
            agent_id=agent_id,
            workflow_id=workflow_id,
            role_id=role_id,
        )
