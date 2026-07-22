#!/usr/bin/env python3
"""
Hermes OMC Workflow Bridge
===========================
Multi-channel adapter for Hermes Agent SDLC workflow.
Switchable between Discord, Zulip, Slack, etc.

Usage:
    OMC_ADAPTER=discord python3 bridge.py    # Discord (default)
    OMC_ADAPTER=zulip   python3 bridge.py    # Zulip (when implemented)
    OMC_ADAPTER=slack   python3 bridge.py    # Slack (when implemented)
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent))

from core.config import load_config
from core.agent_router import AgentRouter
from core.task_manager import TaskManager

# ── Adapter factory ──────────────────────────────────────────────────

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
    channel_names = cfg["channel_names"]
    channel_by_name = cfg["channel_by_name"]

    if adapter_type == "discord":
        return DiscordAdapter(channel_map=channel_by_name)
    elif adapter_type == "zulip":
        zuliprc = os.environ.get("ZULIPRC", "~/.zuliprc")
        return ZulipAdapter(zuliprc_path=zuliprc, stream_map=channel_by_name)
    elif adapter_type == "slack":
        bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
        app_token = os.environ.get("SLACK_APP_TOKEN", "")
        return SlackAdapter(bot_token=bot_token, app_token=app_token, channel_map=channel_by_name)
    else:
        raise ValueError(f"Unknown adapter: {adapter_type}. Available: {list(ADAPTER_REGISTRY.keys())}")


# ── Main ─────────────────────────────────────────────────────────────

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
    logging.info("HERMES OMC WORKFLOW BRIDGE")
    logging.info("=" * 50)

    # Load config
    cfg = load_config()
    adapter_type = cfg["adapter"]
    logging.info(f"Adapter: {adapter_type}")

    # Create adapter
    adapter = create_adapter(adapter_type, cfg)
    channel_names = cfg["channel_names"]
    channel_by_name = cfg["channel_by_name"]

    # Create core services
    task_mgr = TaskManager()

    router = AgentRouter(
        adapter=adapter,
        channel_prompts=cfg["channel_prompts"],
        agent_routes=cfg["agent_routes"],
        channel_names=channel_names,
        channel_by_name=channel_by_name,
        free_channels=cfg["free_channels"],
        task_mgr=task_mgr,
    )

    # Wire message handler (async wrapper)
    async def _on_msg(msg):
        logging.info(f"⚡ Message received: ch={msg.channel_name} author={msg.author_name} is_bot={msg.is_bot}")
        await router.handle_message(msg)

    adapter.on_message(_on_msg)

    # Log loaded config
    logging.info(f"Loaded {len(cfg['channel_prompts'])} agent prompts")
    for cid, prompt in cfg["channel_prompts"].items():
        name = channel_names.get(cid, cid)
        logging.info(f"  {name:30s} → {prompt.strip().split(chr(10))[0][:60]}")
    logging.info(f"\nRoutes:")
    for src, targets in cfg["agent_routes"].items():
        logging.info(f"  {src} → {', '.join(targets)}")

    # Handle shutdown
    shutdown_event = asyncio.Event()

    def _signal_handler():
        logging.info("Shutdown signal received.")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass  # Windows

    try:
        await adapter.start()
    except Exception as e:
        logging.error(f"Adapter failed to start: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
