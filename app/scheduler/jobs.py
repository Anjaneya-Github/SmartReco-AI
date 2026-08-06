"""
app/scheduler/jobs.py
----------------------
APScheduler job definitions for SmartReco AI.

All jobs are designed to be:
- Idempotent — safe to run multiple times
- Self-contained — each creates its own DB session
- Logged — structured log entries with timing and outcomes
- Exception-safe — never crash the scheduler process

Jobs
----
daily_recommendation_refresh  — 08:00 UTC daily
cache_cleanup                 — hourly
event_cleanup                 — 02:00 UTC daily

Each job updates the shared ``_job_stats`` dict so the scheduler
status endpoint can surface last-run metadata.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# ------------------------------------------------------------------ #
# Shared job stats registry                                           #
# ------------------------------------------------------------------ #
# Written by each job at completion; read by the /scheduler/status
# endpoint.  Simple dict — no locking needed (APScheduler jobs run
# sequentially in background threads by default).

_job_stats: dict[str, dict[str, Any]] = {
    "daily_reco_refresh": {"last_run": None, "last_status": "never", "last_duration_s": None, "recommendations_generated": 0},
    "cache_cleanup":       {"last_run": None, "last_status": "never", "last_duration_s": None, "keys_found": 0},
    "event_cleanup":       {"last_run": None, "last_status": "never", "last_duration_s": None, "events_archived": 0},
}


def get_job_stats() -> dict[str, dict[str, Any]]:
    """Return a copy of the current job stats registry."""
    return {k: dict(v) for k, v in _job_stats.items()}


# ------------------------------------------------------------------ #
# Job 1 — Daily recommendation refresh                               #
# ------------------------------------------------------------------ #

def daily_recommendation_refresh() -> None:
    """
    Generate fresh recommendations for every active user that hasn't
    had one in the past 23 hours.

    Reuses the existing ``RecommendationService`` and its LangGraph
    workflow — no recommendation logic is duplicated here.
    """
    from app.database.session import SessionLocal
    from app.models.user import User
    from app.repositories.recommendation_repository import RecommendationRepository
    from app.services.recommendation_service import RecommendationService
    from sqlalchemy import select

    logger.info("scheduler:daily_reco_refresh starting")
    t0 = time.perf_counter()
    refreshed = 0
    skipped = 0
    errors = 0

    db = SessionLocal()
    try:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=23)
        rec_repo = RecommendationRepository(db)
        users = db.execute(select(User).where(User.is_active == True)).scalars().all()

        logger.info("scheduler:daily_reco_refresh active_users=%d", len(users))

        for user in users:
            try:
                latest = rec_repo.get_latest_for_user(user.id)
                if latest:
                    ts = latest.generated_at
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts > cutoff:
                        skipped += 1
                        continue

                svc = RecommendationService(db)
                svc.generate(user.id)
                refreshed += 1
                logger.debug("scheduler:reco_generated user_id=%s", user.id)

                # Invalidate dashboard cache for this user
                try:
                    from app.cache.redis_client import CacheClient
                    from app.cache.keys import dashboard_key, behavior_key
                    cache = CacheClient()
                    cache.delete(dashboard_key(str(user.id)))
                    cache.delete(behavior_key(str(user.id)))
                except Exception:
                    pass

            except Exception as exc:
                errors += 1
                logger.warning(
                    "scheduler:reco_failed user_id=%s error=%s", user.id, exc
                )

        elapsed = round(time.perf_counter() - t0, 2)
        logger.info(
            "scheduler:daily_reco_refresh done. refreshed=%d skipped=%d errors=%d duration=%.2fs",
            refreshed, skipped, errors, elapsed,
        )
        _job_stats["daily_reco_refresh"].update({
            "last_run": datetime.now(tz=timezone.utc).isoformat(),
            "last_status": "error" if errors and not refreshed else "success",
            "last_duration_s": elapsed,
            "recommendations_generated": refreshed,
        })

    except Exception as exc:
        elapsed = round(time.perf_counter() - t0, 2)
        logger.error("scheduler:daily_reco_refresh fatal error. error=%s", exc)
        _job_stats["daily_reco_refresh"].update({
            "last_run": datetime.now(tz=timezone.utc).isoformat(),
            "last_status": "fatal_error",
            "last_duration_s": elapsed,
        })
    finally:
        db.close()


# ------------------------------------------------------------------ #
# Job 2 — Hourly cache cleanup                                       #
# ------------------------------------------------------------------ #

def cache_cleanup() -> None:
    """
    Log Redis memory stats and key count.

    Redis manages TTL expiry natively — this job surfaces observability
    data (key count, memory usage) in the application logs and updates
    the scheduler status endpoint.
    """
    logger.info("scheduler:cache_cleanup starting")
    t0 = time.perf_counter()
    keys = 0

    try:
        from app.cache.redis_client import _get_redis_or_none
        r = _get_redis_or_none()
        if r is None:
            logger.info("scheduler:cache_cleanup Redis unavailable — skipping")
            _job_stats["cache_cleanup"].update({
                "last_run": datetime.now(tz=timezone.utc).isoformat(),
                "last_status": "skipped_no_redis",
                "last_duration_s": round(time.perf_counter() - t0, 2),
                "keys_found": 0,
            })
            return

        info = r.info("memory")
        used_mb = info.get("used_memory_human", "n/a")
        keys = r.dbsize()
        elapsed = round(time.perf_counter() - t0, 2)

        logger.info(
            "scheduler:cache_cleanup done. keys=%d memory=%s duration=%.2fs",
            keys, used_mb, elapsed,
        )
        _job_stats["cache_cleanup"].update({
            "last_run": datetime.now(tz=timezone.utc).isoformat(),
            "last_status": "success",
            "last_duration_s": elapsed,
            "keys_found": keys,
        })

    except Exception as exc:
        elapsed = round(time.perf_counter() - t0, 2)
        logger.warning("scheduler:cache_cleanup error. error=%s", exc)
        _job_stats["cache_cleanup"].update({
            "last_run": datetime.now(tz=timezone.utc).isoformat(),
            "last_status": "error",
            "last_duration_s": elapsed,
            "keys_found": keys,
        })


# ------------------------------------------------------------------ #
# Job 3 — Daily event cleanup                                        #
# ------------------------------------------------------------------ #

def event_cleanup() -> None:
    """
    Delete UserEvent records older than 90 days.

    Keeps the events table lean.  A structured log entry records the
    count so the DBA can monitor growth before the delete runs.
    """
    from app.database.session import SessionLocal
    from app.models.event import UserEvent
    from sqlalchemy import delete, func, select

    logger.info("scheduler:event_cleanup starting")
    t0 = time.perf_counter()
    archived = 0

    db = SessionLocal()
    try:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=90)

        # Count first for visibility
        archived = db.execute(
            select(func.count(UserEvent.id)).where(UserEvent.created_at < cutoff)
        ).scalar_one()

        if archived > 0:
            db.execute(delete(UserEvent).where(UserEvent.created_at < cutoff))
            db.commit()
            logger.info(
                "scheduler:event_cleanup deleted %d events older than 90 days", archived
            )
        else:
            logger.info("scheduler:event_cleanup no old events to delete")

        elapsed = round(time.perf_counter() - t0, 2)
        _job_stats["event_cleanup"].update({
            "last_run": datetime.now(tz=timezone.utc).isoformat(),
            "last_status": "success",
            "last_duration_s": elapsed,
            "events_archived": archived,
        })

    except Exception as exc:
        elapsed = round(time.perf_counter() - t0, 2)
        logger.error("scheduler:event_cleanup error. error=%s", exc)
        db.rollback()
        _job_stats["event_cleanup"].update({
            "last_run": datetime.now(tz=timezone.utc).isoformat(),
            "last_status": "error",
            "last_duration_s": elapsed,
            "events_archived": 0,
        })
    finally:
        db.close()
