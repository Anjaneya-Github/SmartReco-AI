"""
app/cache/keys.py
------------------
Centralised cache key builders and TTL (Time-To-Live) constants.

Why centralise keys?
~~~~~~~~~~~~~~~~~~~~
If cache keys are scattered across the codebase as magic strings, it
becomes easy to introduce typos, forget to invalidate related keys, or
change a key pattern in one place but not another.

By defining all keys and TTLs here, every part of the application uses
the same key format — making cache invalidation reliable and predictable.

TTL Design Decisions
~~~~~~~~~~~~~~~~~~~~
- Behavior profile (10 min): changes frequently as users interact.
- Recommendation (30 min): expensive to generate; valid for longer.
- Dashboard (5 min): quick freshness — includes live behavior data.
- Search results (30 min): vector search is slow; results are stable.
- Analytics (5 min): aggregates; acceptable to be slightly stale.

Cache Key Format
~~~~~~~~~~~~~~~~
Keys follow the pattern: ``<domain>:<identifier>[:<sub-key>]``
This makes keys easy to scan, debug, and bulk-delete by pattern.

    behavior:550e8400-e29b-41d4-a716-446655440000
    recommendation:550e8400...:a1b2c3d4e5f6
    dashboard:550e8400-e29b-41d4-a716-446655440000
    search:a1b2c3d4e5f6:d7e8f9a0b1c2
    analytics:global
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# ------------------------------------------------------------------ #
# TTL constants — all values are in seconds                           #
# ------------------------------------------------------------------ #

TTL_BEHAVIOR       = 600    # 10 minutes — user behavior profile
TTL_RECOMMENDATION = 1800   # 30 minutes — AI recommendation result
TTL_DASHBOARD      = 300    # 5 minutes  — full dashboard payload
TTL_SEARCH         = 1800   # 30 minutes — vector search results
TTL_ANALYTICS      = 300    # 5 minutes  — admin analytics aggregate


# ------------------------------------------------------------------ #
# Key builders — always use these functions, never raw strings        #
# ------------------------------------------------------------------ #

def behavior_key(user_id: str) -> str:
    """
    Cache key for a user's computed behavior profile.

    Invalidate when: new events are ingested for this user.

    Args:
        user_id: UUID string of the user.

    Returns:
        e.g. "behavior:550e8400-e29b-41d4-a716-446655440000"
    """
    return f"behavior:{user_id}"


def recommendation_key(user_id: str, behavior_hash: str) -> str:
    """
    Cache key for a user's recommendation, scoped to their current behavior.

    The ``behavior_hash`` component means the cached result becomes stale
    automatically when the user's profile changes enough to produce a
    different hash — no explicit invalidation needed.

    Args:
        user_id:       UUID string of the user.
        behavior_hash: Short hash of the behavior profile dict (from hash_dict).

    Returns:
        e.g. "recommendation:550e8400...:a1b2c3d4e5f6"
    """
    return f"recommendation:{user_id}:{behavior_hash}"


def dashboard_key(user_id: str) -> str:
    """
    Cache key for the full dashboard payload for a user.

    Invalidate when: feedback submitted, or new recommendation generated.

    Args:
        user_id: UUID string of the user.

    Returns:
        e.g. "dashboard:550e8400-e29b-41d4-a716-446655440000"
    """
    return f"dashboard:{user_id}"


def search_key(behavior_hash: str, query_hash: str) -> str:
    """
    Cache key for a vector search result, scoped to both the query and user context.

    Combining both hashes means the same query from two users with different
    profiles gets different cache entries (since retrieval is personalised).

    Args:
        behavior_hash: Hash of the user's current behavior profile.
        query_hash:    Hash of the vector search query string.

    Returns:
        e.g. "search:a1b2c3d4e5f6:d7e8f9a0b1c2"
    """
    return f"search:{behavior_hash}:{query_hash}"


def analytics_key() -> str:
    """
    Cache key for the global admin analytics aggregate.

    There is only one analytics snapshot at a time (not per-user),
    so the key has no dynamic component.

    Returns:
        "analytics:global"
    """
    return "analytics:global"


# ------------------------------------------------------------------ #
# Utility                                                             #
# ------------------------------------------------------------------ #

def hash_dict(d: Any) -> str:
    """
    Produce a short, stable hash string for any JSON-serialisable value.

    Used to create cache keys that automatically change when the underlying
    data changes — without needing to track every field explicitly.

    The MD5 hash is used purely for a short, fast fingerprint — NOT for
    security. Sorting keys ensures the same dict always produces the same
    hash regardless of insertion order.

    Args:
        d: Any JSON-serialisable value (dict, list, string, etc.).

    Returns:
        12-character hexadecimal string, e.g. "a1b2c3d4e5f6".
    """
    # sort_keys=True ensures {"b":2,"a":1} and {"a":1,"b":2} hash identically
    raw = json.dumps(d, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()[:12]
