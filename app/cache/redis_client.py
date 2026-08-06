"""app/cache/redis_client.py — Redis connection with graceful no-op fallback."""
from __future__ import annotations
import json
from functools import lru_cache
from typing import Any
from app.core.logging import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _get_redis_or_none():
    """Return a connected Redis client, or None if Redis is unavailable."""
    try:
        import redis as _redis
        from app.core.config import settings
        client = _redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        client.ping()
        logger.info("Redis connected. url=%s", settings.REDIS_URL)
        return client
    except Exception as exc:
        logger.warning("Redis unavailable — caching disabled. error=%s", exc)
        return None


class CacheClient:
    """
    Thin Redis wrapper with JSON serialisation.
    Every method is a no-op when Redis is unavailable — the app
    continues working without caching, never raising an exception.
    """

    def __init__(self) -> None:
        self._r = _get_redis_or_none()
        self._enabled = self._r is not None

    def get(self, key: str) -> Any | None:
        if not self._enabled:
            return None
        try:
            raw = self._r.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    def set(self, key: str, value: Any, ttl: int) -> None:
        if not self._enabled:
            return
        try:
            self._r.setex(key, ttl, json.dumps(value, default=str))
        except Exception:
            pass

    def delete(self, key: str) -> None:
        if not self._enabled:
            return
        try:
            self._r.delete(key)
        except Exception:
            pass

    def delete_pattern(self, pattern: str) -> int:
        if not self._enabled:
            return 0
        try:
            keys = self._r.keys(pattern)
            if keys:
                self._r.delete(*keys)
            return len(keys)
        except Exception:
            return 0

    def ping(self) -> bool:
        if not self._enabled:
            return False
        try:
            return bool(self._r.ping())
        except Exception:
            return False
