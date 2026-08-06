"""
app/cache/redis_client.py
--------------------------
Redis connection manager with automatic graceful fallback.

What is this?
~~~~~~~~~~~~~
Redis is an in-memory key-value store used to cache expensive results
(database queries, AI responses) so they can be served instantly on
repeat requests instead of recomputing them every time.

Graceful degradation
~~~~~~~~~~~~~~~~~~~~
Redis is OPTIONAL in this project. If Redis is not running (e.g. during
local development without Docker), the app continues working normally —
just without caching. Every cache operation becomes an instant no-op
(does nothing and returns None) instead of crashing.

How it works
~~~~~~~~~~~~
1. ``_get_redis_or_none()`` attempts to connect once (1-second timeout).
   - If it succeeds  → returns the Redis client, cached via @lru_cache.
   - If it fails     → returns None, also cached, so we never retry.
2. ``CacheClient`` wraps the Redis client, checking ``_enabled`` before
   every operation. If Redis is unavailable, the method returns
   immediately without doing any network I/O.

Usage
~~~~~
    from app.cache.redis_client import CacheClient

    cache = CacheClient()
    cache.set("my_key", {"data": "value"}, ttl=300)  # stores for 5 min
    result = cache.get("my_key")                      # {"data": "value"}
    cache.delete("my_key")                            # removes it
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _get_redis_or_none():
    """
    Try to connect to Redis exactly once. Cache the result forever.

    ``@lru_cache(maxsize=1)`` means this function only runs once per
    process lifetime, no matter how many times it is called. If Redis
    was unavailable at startup it will stay None for the entire process —
    this prevents repeated 1-second connection timeouts on every request.

    Returns:
        A connected ``redis.Redis`` client, or ``None`` if unavailable.
    """
    try:
        import redis as _redis
        from app.core.config import settings

        client = _redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,   # return strings, not bytes
            socket_connect_timeout=1,  # fail fast if Redis is down
            socket_timeout=1,
        )
        client.ping()  # verify the connection is actually alive
        logger.info("Redis connected. url=%s", settings.REDIS_URL)
        return client

    except Exception as exc:
        logger.warning(
            "Redis unavailable — caching disabled for this process. error=%s", exc
        )
        return None


class CacheClient:
    """
    A safe, JSON-aware wrapper around Redis.

    All methods silently do nothing when Redis is unavailable, so the
    rest of the application never needs to check whether Redis is up.

    Values are automatically serialised to JSON on write and deserialised
    back to Python objects on read, so you can store dicts, lists, etc.

    Args:
        (none — the Redis connection is managed internally)

    Example::

        cache = CacheClient()

        # Store a user's behavior profile for 10 minutes
        cache.set("behavior:user-123", profile_dict, ttl=600)

        # Read it back (returns None if not cached or if Redis is down)
        cached = cache.get("behavior:user-123")

        # Remove it (e.g. when user gets new events)
        cache.delete("behavior:user-123")
    """

    def __init__(self) -> None:
        # Connect once. If None, all operations become no-ops.
        self._r = _get_redis_or_none()
        self._enabled = self._r is not None

    # ------------------------------------------------------------------ #
    # Read                                                                #
    # ------------------------------------------------------------------ #

    def get(self, key: str) -> Any | None:
        """
        Return the cached value for *key*, or ``None`` if not found.

        Args:
            key: The cache key string (e.g. "behavior:user-123").

        Returns:
            The deserialised Python value, or ``None`` on cache miss /
            Redis unavailable.
        """
        if not self._enabled:
            return None
        try:
            raw = self._r.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Write                                                               #
    # ------------------------------------------------------------------ #

    def set(self, key: str, value: Any, ttl: int) -> None:
        """
        Store *value* under *key* for *ttl* seconds, then auto-expire.

        Args:
            key:   Cache key string.
            value: Any JSON-serialisable Python value (dict, list, str…).
            ttl:   Time-to-live in seconds. After this time Redis deletes
                   the key automatically. Use constants from ``cache/keys.py``.
        """
        if not self._enabled:
            return
        try:
            # setex = SET with EXpiry. Stores as a JSON string.
            self._r.setex(key, ttl, json.dumps(value, default=str))
        except Exception:
            pass  # never crash the caller on a cache write failure

    # ------------------------------------------------------------------ #
    # Delete                                                              #
    # ------------------------------------------------------------------ #

    def delete(self, key: str) -> None:
        """
        Remove a single key from the cache (e.g. after a data change).

        Args:
            key: The exact key to remove.
        """
        if not self._enabled:
            return
        try:
            self._r.delete(key)
        except Exception:
            pass

    def delete_pattern(self, pattern: str) -> int:
        """
        Remove all keys matching a glob pattern.

        Used for bulk cache invalidation, e.g. clearing all
        recommendation caches for a user after new data arrives.

        Example:
            cache.delete_pattern("recommendation:user-123:*")

        Args:
            pattern: Redis glob pattern (e.g. "dashboard:*").

        Returns:
            Number of keys deleted (0 if Redis unavailable).

        Warning:
            ``KEYS`` is an O(N) operation — avoid on very large keyspaces.
            Fine for development; use ``SCAN`` for production at scale.
        """
        if not self._enabled:
            return 0
        try:
            keys = self._r.keys(pattern)
            if keys:
                self._r.delete(*keys)
            return len(keys)
        except Exception:
            return 0

    # ------------------------------------------------------------------ #
    # Health                                                              #
    # ------------------------------------------------------------------ #

    def ping(self) -> bool:
        """
        Check if Redis is reachable right now.

        Returns:
            True if Redis responds to a ping, False otherwise.
        """
        if not self._enabled:
            return False
        try:
            return bool(self._r.ping())
        except Exception:
            return False
