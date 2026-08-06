"""app/scheduler/scheduler.py — APScheduler setup and registration."""
from __future__ import annotations
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.core.logging import get_logger
from app.scheduler.jobs import cache_cleanup, daily_recommendation_refresh, event_cleanup

logger = get_logger(__name__)

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="UTC")
    return _scheduler


def start_scheduler() -> None:
    sched = get_scheduler()
    if sched.running:
        return

    # 1. Daily recommendation refresh — 6 AM UTC
    sched.add_job(
        daily_recommendation_refresh,
        CronTrigger(hour=6, minute=0),
        id="daily_reco_refresh",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # 2. Cache cleanup — every hour
    sched.add_job(
        cache_cleanup,
        IntervalTrigger(hours=1),
        id="cache_cleanup",
        replace_existing=True,
    )

    # 3. Event cleanup — daily at 3 AM UTC
    sched.add_job(
        event_cleanup,
        CronTrigger(hour=3, minute=0),
        id="event_cleanup",
        replace_existing=True,
        misfire_grace_time=600,
    )

    sched.start()
    logger.info("APScheduler started with %d jobs.", len(sched.get_jobs()))


def stop_scheduler() -> None:
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)
        logger.info("APScheduler stopped.")
