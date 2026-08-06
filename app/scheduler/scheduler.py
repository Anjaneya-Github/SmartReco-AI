"""
app/scheduler/scheduler.py
----------------------------
APScheduler setup, registration, and runtime control.

Public API
----------
start_scheduler()          — start the background scheduler (called at lifespan startup)
stop_scheduler()           — graceful shutdown (called at lifespan shutdown)
get_scheduler()            — returns the singleton BackgroundScheduler instance
run_job_now(job_id)        — immediately execute a registered job
get_status()               — return SchedulerStatus for the /scheduler/status endpoint
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.logging import get_logger
from app.scheduler.jobs import (
    cache_cleanup,
    daily_recommendation_refresh,
    event_cleanup,
    get_job_stats,
)

logger = get_logger(__name__)

# ------------------------------------------------------------------ #
# Singleton scheduler instance                                        #
# ------------------------------------------------------------------ #

_scheduler: BackgroundScheduler | None = None

# Job registry: id → (function, trigger kwargs, display name)
_JOB_REGISTRY: dict[str, tuple] = {
    "daily_reco_refresh": (
        daily_recommendation_refresh,
        {"trigger": CronTrigger(hour=8, minute=0), "misfire_grace_time": 600},
        "Daily Recommendation Refresh",
    ),
    "cache_cleanup": (
        cache_cleanup,
        {"trigger": IntervalTrigger(hours=1)},
        "Hourly Cache Cleanup",
    ),
    "event_cleanup": (
        event_cleanup,
        {"trigger": CronTrigger(hour=2, minute=0), "misfire_grace_time": 600},
        "Daily Event Cleanup",
    ),
}


def get_scheduler() -> BackgroundScheduler:
    """Return the singleton BackgroundScheduler, creating it if needed."""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="UTC")
    return _scheduler


def start_scheduler() -> None:
    """Register all jobs and start the scheduler. Safe to call multiple times."""
    sched = get_scheduler()
    if sched.running:
        logger.debug("Scheduler already running — skipping start.")
        return

    for job_id, (fn, kwargs, _name) in _JOB_REGISTRY.items():
        sched.add_job(
            fn,
            id=job_id,
            replace_existing=True,
            **kwargs,
        )
        logger.debug("Scheduled job registered. id=%s", job_id)

    sched.start()
    logger.info(
        "APScheduler started. timezone=UTC jobs=%d", len(sched.get_jobs())
    )


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)
        logger.info("APScheduler stopped.")


def run_job_now(job_id: str) -> dict[str, Any]:
    """
    Immediately execute a registered job in the calling thread.

    Args:
        job_id: One of ``daily_reco_refresh``, ``cache_cleanup``, ``event_cleanup``.

    Returns:
        Dict with ``job_id``, ``triggered_at``, ``status``.

    Raises:
        ValueError: If job_id is not registered.
    """
    if job_id not in _JOB_REGISTRY:
        raise ValueError(
            f"Unknown job '{job_id}'. Valid IDs: {list(_JOB_REGISTRY)}"
        )

    fn, _, name = _JOB_REGISTRY[job_id]
    triggered_at = datetime.now(tz=timezone.utc).isoformat()
    logger.info("scheduler:run_now job_id=%s triggered_at=%s", job_id, triggered_at)

    try:
        fn()
        status = "triggered"
    except Exception as exc:
        logger.error("scheduler:run_now failed. job_id=%s error=%s", job_id, exc)
        status = f"error: {exc}"

    return {"job_id": job_id, "name": name, "triggered_at": triggered_at, "status": status}


def get_status() -> dict[str, Any]:
    """
    Return current scheduler status and per-job metadata.

    Used by ``GET /api/v1/admin/scheduler/status``.
    """
    sched = get_scheduler()
    job_stats = get_job_stats()
    jobs_detail = []

    for job_id, (_, _, display_name) in _JOB_REGISTRY.items():
        job = sched.get_job(job_id) if sched.running else None
        stats = job_stats.get(job_id, {})
        jobs_detail.append({
            "id": job_id,
            "name": display_name,
            "next_run_time": job.next_run_time.isoformat() if job and job.next_run_time else None,
            "last_run": stats.get("last_run"),
            "last_status": stats.get("last_status", "never"),
            "last_duration_s": stats.get("last_duration_s"),
            "recommendations_generated": stats.get("recommendations_generated"),
            "events_archived": stats.get("events_archived"),
            "keys_found": stats.get("keys_found"),
        })

    return {
        "scheduler_running": sched.running,
        "registered_jobs": len(_JOB_REGISTRY),
        "jobs": jobs_detail,
    }
