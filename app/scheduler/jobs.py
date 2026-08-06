"""app/scheduler/jobs.py — APScheduler job definitions."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from app.core.logging import get_logger

logger = get_logger(__name__)


def daily_recommendation_refresh() -> None:
    """Generate recommendations for active users who haven't had one today."""
    from app.database.session import SessionLocal
    from app.repositories.user_repository import UserRepository
    from app.repositories.recommendation_repository import RecommendationRepository
    from app.services.recommendation_service import RecommendationService

    db = SessionLocal()
    try:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=23)
        user_repo = UserRepository(db)
        rec_repo = RecommendationRepository(db)

        from sqlalchemy import select
        from app.models.user import User
        users = db.execute(
            select(User).where(User.is_active == True)
        ).scalars().all()

        refreshed = 0
        for user in users:
            latest = rec_repo.get_latest_for_user(user.id)
            if latest and latest.generated_at.replace(tzinfo=timezone.utc) > cutoff:
                continue
            try:
                svc = RecommendationService(db)
                svc.generate(user.id)
                refreshed += 1
            except Exception as exc:
                logger.warning("daily_refresh failed for user %s: %s", user.id, exc)

        logger.info("daily_recommendation_refresh complete. refreshed=%d", refreshed)
    finally:
        db.close()


def cache_cleanup() -> None:
    """Remove expired keys (Redis handles TTL automatically; log stats here)."""
    from app.cache.redis_client import get_redis
    try:
        r = get_redis()
        info = r.info("memory")
        used_mb = info.get("used_memory_human", "n/a")
        keys = r.dbsize()
        logger.info("cache_cleanup: keys=%d memory=%s", keys, used_mb)
    except Exception as exc:
        logger.warning("cache_cleanup error: %s", exc)


def event_cleanup() -> None:
    """Archive events older than 90 days (soft delete by logging count)."""
    from app.database.session import SessionLocal
    from app.models.event import UserEvent
    from sqlalchemy import select, func

    db = SessionLocal()
    try:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=90)
        count = db.execute(
            select(func.count(UserEvent.id)).where(UserEvent.created_at < cutoff)
        ).scalar_one()
        logger.info("event_cleanup: %d events older than 90 days (archive candidate)", count)
    finally:
        db.close()
