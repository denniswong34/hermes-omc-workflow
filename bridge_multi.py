"""
Multi-workflow bridge entry — ChatAdapterHub + WorkflowRuntimePool + AgentRouter.

Legacy single-config mode remains in bridge.py.
Usage:
    OMC_MULTI_WORKFLOW=1 python bridge_multi.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from adapters.hub import build_multi_bot_hub
from core.cron import get_cron_scheduler
from core.db import get_db
from core.db.seed import seed_database
from core.secrets import load_workflow_secrets_into_environ
from core.workflow import get_pool, reload_pool
from core.workflow.repository import WorkflowRepository
from core.workflow.runtime_router import build_agent_router, restore_default_channel_agents


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(Path(__file__).parent / "bridge.log", mode="a"),
            logging.StreamHandler(),
        ],
    )
    logging.info("OMC multi-workflow bridge starting")

    db = get_db()
    seed_database(db, activate=True)
    repo = WorkflowRepository(db)
    restored = restore_default_channel_agents(repo)
    if restored:
        logging.info("Restored agents on %d channel(s)", restored)

    pool = reload_pool()

    # Load secrets for all active workflows into process env (Discord/Jira/…)
    active = repo.list_active()
    for wf in active:
        load_workflow_secrets_into_environ(wf.id)

    # Build channel maps per platform from active workflows
    maps: dict[str, dict[str, str]] = {}
    for wf in active:
        for ch in wf.channels:
            ext = (ch.external_id or "").strip()
            if not ext or ext.startswith("REPLACE_"):
                continue
            maps.setdefault(ch.platform, {})[ch.name] = ext

    hub = build_multi_bot_hub(active, maps)
    hub.set_ownership(repo.channel_ownership_map())

    # One AgentRouter per (workflow_id, platform)
    routers: dict[tuple[str, str], object] = {}

    def _router_for(workflow_id: str, platform: str):
        key = (workflow_id, platform)
        if key in routers:
            return routers[key]
        rt = pool.get(workflow_id)
        if not rt:
            return None
        adapter = hub.adapters.get(platform)
        if not adapter:
            # Prefer any agent adapter for this platform
            for ad_key, candidate in hub.adapters.items():
                if ad_key == platform or ad_key.startswith(f"{platform}:"):
                    adapter = candidate
                    break
        if not adapter:
            logging.error("No adapter for platform %s", platform)
            return None
        role_adapters = hub.adapters_by_role(platform)
        router = build_agent_router(
            rt, adapter, adapters_by_role=role_adapters
        )
        routers[key] = router
        logging.info(
            "AgentRouter ready for workflow %s (%s) platform=%s topics=%s roles=%s",
            workflow_id,
            rt.workflow.name,
            platform,
            list(router.topics.keys()),
            list(role_adapters.keys()) or ["(legacy)"],
        )
        return router

    def on_msg(msg, platform, workflow_id):
        rt = pool.get(workflow_id)
        if not rt:
            logging.warning("No runtime for workflow %s", workflow_id)
            return
        logging.info(
            "Routed %s:%s → workflow %s (%s) agent=%s role=%s dm=%s content=%s",
            platform,
            msg.channel_id,
            workflow_id,
            rt.workflow.name,
            getattr(msg, "agent_id", "") or "-",
            getattr(msg, "target_role", "") or "-",
            getattr(msg, "is_dm", False),
            (msg.content or "")[:120],
        )

        async def _handle():
            router = _router_for(workflow_id, platform)
            if not router:
                await hub.send(
                    platform,
                    msg.channel_id,
                    f"[{rt.workflow.name}] no router available",
                )
                return
            await router.handle_message(msg)

        asyncio.create_task(_handle())

    hub.on_routed_message(on_msg)

    cron = get_cron_scheduler()

    async def cron_handler(job_meta):
        logging.info("Cron job: %s", job_meta)

    cron.set_handler(cron_handler)
    cron.sync_from_workflows([r.workflow for r in pool.runtimes.values()])
    cron.start()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_event_loop().add_signal_handler(
                sig, lambda: logging.info("Shutdown signal")
            )
        except NotImplementedError:
            pass

    await hub.start_all()
    logging.info(
        "Hub running with %d adapter(s), %d active workflow(s)",
        len(hub.adapters),
        len(pool.runtimes),
    )
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    if os.environ.get("OMC_MULTI_WORKFLOW", "1") == "0":
        logging.error("Use bridge.py for legacy single-config mode")
        sys.exit(1)
    asyncio.run(main())
