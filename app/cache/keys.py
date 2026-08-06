"""app/cache/keys.py — Cache key builders and TTL constants."""
from __future__ import annotations
import hashlib, json
from typing import Any

# TTLs in seconds
TTL_BEHAVIOR       = 600   # 10 min
TTL_RECOMMENDATION = 1800  # 30 min
TTL_DASHBOARD      = 300   # 5 min
TTL_SEARCH         = 1800  # 30 min
TTL_ANALYTICS      = 300   # 5 min


def behavior_key(user_id: str) -> str:
    return f"behavior:{user_id}"


def recommendation_key(user_id: str, behavior_hash: str) -> str:
    return f"recommendation:{user_id}:{behavior_hash}"


def dashboard_key(user_id: str) -> str:
    return f"dashboard:{user_id}"


def search_key(behavior_hash: str, query_hash: str) -> str:
    return f"search:{behavior_hash}:{query_hash}"


def analytics_key() -> str:
    return "analytics:global"


def hash_dict(d: Any) -> str:
    """Stable short hash of any JSON-serialisable value."""
    raw = json.dumps(d, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()[:12]
