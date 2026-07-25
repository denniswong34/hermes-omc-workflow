"""Per-active-workflow cron scheduler (APScheduler)."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class CronScheduler:
    """
    Schedule cron jobs for active workflows.
    Uses APScheduler when installed; otherwise keeps an in-memory job list for API.
    """

    def __init__(self):
        self._jobs: dict[str, dict[str, Any]] = {}
        self._scheduler = None
        self._handler: Optional[Callable[..., Any]] = None
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger

            self._scheduler = AsyncIOScheduler()
            self._CronTrigger = CronTrigger
        except ImportError:
            logger.warning("APScheduler not installed — cron list-only mode")

    def set_handler(self, handler: Callable[..., Any]) -> None:
        self._handler = handler

    def start(self) -> None:
        if self._scheduler and not self._scheduler.running:
            self._scheduler.start()
            logger.info("CronScheduler started")

    def stop(self) -> None:
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def sync_from_workflows(self, workflows: list[Any]) -> None:
        """Reload jobs from active WorkflowRecord list."""
        # Clear existing
        if self._scheduler:
            self._scheduler.remove_all_jobs()
        self._jobs.clear()

        for wf in workflows:
            for job in getattr(wf, "cron_jobs", []) or []:
                if not job.enabled:
                    continue
                job_id = f"{wf.id}:{job.id}"
                meta = {
                    "id": job_id,
                    "workflow_id": wf.id,
                    "workflow_name": wf.name,
                    "name": job.name,
                    "cron_expr": job.cron_expr,
                    "agent_role": job.agent_role,
                    "channel_name": job.channel_name,
                    "prompt": job.prompt,
                }
                self._jobs[job_id] = meta
                if self._scheduler:
                    try:
                        trigger = self._CronTrigger.from_crontab(job.cron_expr)
                        self._scheduler.add_job(
                            self._fire,
                            trigger=trigger,
                            id=job_id,
                            replace_existing=True,
                            kwargs={"job_meta": meta},
                        )
                    except Exception as e:
                        logger.error("Invalid cron %s: %s", job.cron_expr, e)

        logger.info("CronScheduler synced %d job(s)", len(self._jobs))

    async def _fire(self, job_meta: dict[str, Any]) -> None:
        logger.info("Cron fire: %s", job_meta.get("name"))
        if self._handler:
            await self._handler(job_meta)

    def list_jobs(self) -> list[dict[str, Any]]:
        return list(self._jobs.values())


_scheduler: Optional[CronScheduler] = None


def get_cron_scheduler() -> CronScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = CronScheduler()
    return _scheduler
