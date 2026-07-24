#!/usr/bin/env python3
"""
Hermes OMC Workflow Bridge
===========================
Topic-channel multi-agent SDLC bridge for Discord / Zulip / Slack.

Boss @mentions agents in shared topic rooms (product, engineering, …).
Handoffs stay in-channel. Tickets sync to Plane / Jira / none.

Usage:
    OMC_ADAPTER=discord python bridge.py
    OMC_CONFIG=config/omc.yaml OMC_WORKSPACE=/path/to/repo python bridge.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.agent_router import AgentRouter
from core.coding import create_coding_registry
from core.config import load_config
from core.sdlc_tracker import SDLCTracker
from core.task_manager import TaskManager
from core.tickets import create_tracker

ADAPTER_REGISTRY = {}

try:
    from adapters.discord_adapter import DiscordAdapter

    ADAPTER_REGISTRY["discord"] = DiscordAdapter
except ImportError:
    pass

try:
    from adapters.zulip_adapter import ZulipAdapter

    ADAPTER_REGISTRY["zulip"] = ZulipAdapter
except ImportError:
    pass

try:
    from adapters.slack_adapter import SlackAdapter

    ADAPTER_REGISTRY["slack"] = SlackAdapter
except ImportError:
    pass


def create_adapter(adapter_type: str, cfg: dict):
    """Instantiate the selected channel adapter."""
    channel_by_name = cfg["channel_by_name"]

    if adapter_type == "discord":
        return DiscordAdapter(channel_map=channel_by_name)
    if adapter_type == "zulip":
        zuliprc = os.environ.get("ZULIPRC", "~/.zuliprc")
        return ZulipAdapter(zuliprc_path=zuliprc, stream_map=channel_by_name)
    if adapter_type == "slack":
        bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
        app_token = os.environ.get("SLACK_APP_TOKEN", "")
        return SlackAdapter(
            bot_token=bot_token, app_token=app_token, channel_map=channel_by_name
        )
    raise ValueError(
        f"Unknown adapter: {adapter_type}. Available: {list(ADAPTER_REGISTRY.keys())}"
    )


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(Path(__file__).parent / "bridge.log", mode="a"),
            logging.StreamHandler(),
        ],
    )

    logging.info("=" * 50)
    logging.info("HERMES OMC WORKFLOW BRIDGE (topic mode)")
    logging.info("=" * 50)

    cfg = load_config()
    adapter_type = cfg["adapter"]
    logging.info(f"Config: {cfg.get('config_path')}")
    logging.info(f"Adapter: {adapter_type}")
    logging.info(f"Agents dir: {cfg.get('agents_dir')}")

    adapter = create_adapter(adapter_type, cfg)

    tickets_cfg = cfg.get("tickets") or {}
    provider = (tickets_cfg.get("provider") or "none").strip().lower()
    store_path = tickets_cfg.get("store_path", "~/.hermes/omc/task_map.json")

    ticket_tracker = create_tracker(tickets_cfg)
    task_mgr = TaskManager(store_path=store_path)
    sdlc = SDLCTracker(
        tracker=ticket_tracker,
        status_authority=cfg.get("status_authority") or {},
    )
    coding = create_coding_registry(cfg.get("coding"))

    router = AgentRouter(
        adapter=adapter,
        topics=cfg["topics"],
        topic_by_channel_id=cfg["topic_by_channel_id"],
        agent_prompts=cfg["agent_prompts"],
        agent_routes=cfg["agent_routes"],
        channel_names=cfg["channel_names"],
        coding=coding,
        sdlc=sdlc,
        task_mgr=task_mgr,
        ticket_tracker=ticket_tracker,
        ticket_provider=provider,
    )

    async def _on_msg(msg):
        logging.info(
            f"⚡ Message: ch={msg.channel_name} author={msg.author_name} "
            f"is_bot={msg.is_bot}"
        )
        await router.handle_message(msg)

    adapter.on_message(_on_msg)

    logging.info(f"Ticket provider: {provider}")
    logging.info(f"Coding default: {coding.default_key} workspace={coding.workspace or '(none)'}")
    logging.info(f"Topics ({len(cfg['topics'])}):")
    for key, t in cfg["topics"].items():
        agents = ", ".join(t["agents"])
        logging.info(f"  #{key:12s} id={t['channel_id']} agents=[{agents}]")
    logging.info("Agent routes:")
    for src, targets in cfg["agent_routes"].items():
        if targets:
            logging.info(f"  @{src} → {', '.join('@' + x for x in targets)}")

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_event_loop().add_signal_handler(
                sig, lambda: logging.info("Shutdown signal received.")
            )
        except NotImplementedError:
            pass

    try:
        await adapter.start()
    except Exception as e:
        logging.error(f"Adapter failed to start: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
