"""
app/dashboard/dashboard_schema.py
-----------------------------------
Pydantic schemas for the read-only dashboard API responses.

These schemas define the exact shape of data returned by:
  - GET /api/v1/dashboard       → DashboardResponse
  - GET /api/v1/dashboard/analytics → AnalyticsResponse

Design principle: READ-ONLY
~~~~~~~~~~~~~~~~~~~~~~~~~~~
These schemas are for OUTPUT only. The dashboard never generates, modifies,
or stores any data. It reads from the database and cache and assembles
everything here into one structured response.

Schema summary
~~~~~~~~~~~~~~
ActivityItem
    A single event in the user's activity timeline
    (e.g. "viewed Python for ML at 3:45 PM").

UserSummary
    Basic user profile info shown at the top of the dashboard.

DashboardResponse
    The full dashboard payload: user info + behavior profile
    + recommendation + evidence + activity timeline + cache metadata.

AnalyticsResponse
    Platform-wide aggregated statistics for admin dashboards.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import AppBaseSchema
from app.schemas.recommendation import RecommendedProduct


# ------------------------------------------------------------------ #
# ActivityItem — one row in the "Recent Activity" timeline           #
# ------------------------------------------------------------------ #

class ActivityItem(AppBaseSchema):
    """
    Represents a single user interaction event in the activity timeline.

    Fields
    ~~~~~~
    event_type      What the user did: "view", "click", "search", "purchase", etc.
    product_title   Name of the product involved (if any).
    search_query    The search term typed (for "search" events only).
    created_at      When the event happened (UTC timestamp).
    """

    event_type:    str
    product_title: str | None = None   # None for non-product events (e.g. search)
    search_query:  str | None = None   # None for non-search events
    created_at:    datetime


# ------------------------------------------------------------------ #
# UserSummary — basic profile shown at top of dashboard              #
# ------------------------------------------------------------------ #

class UserSummary(AppBaseSchema):
    """
    A trimmed user profile for the dashboard header.

    We intentionally exclude: hashed_password, is_verified, updated_at
    — the dashboard only needs what's shown on screen.
    """

    id:           uuid.UUID
    email:        str
    full_name:    str | None   # Optional — not all users set this
    role:         str          # "user" or "admin"
    is_active:    bool
    member_since: datetime     # Maps to User.created_at


# ------------------------------------------------------------------ #
# DashboardResponse — the full dashboard payload                     #
# ------------------------------------------------------------------ #

class DashboardResponse(AppBaseSchema):
    """
    Complete dashboard response — everything shown on the user's dashboard page.

    Assembled by ``DashboardService.get_dashboard()`` which reads from
    the database and Redis cache. This endpoint NEVER calls the AI.

    Sections
    --------
    **User**
        Basic account information.

    **Behavior** (computed from event history)
        - primary_categories: Top course categories the user has interacted with
        - favorite_tags: Most common product tags across interactions
        - top_searches: Most repeated search queries
        - engagement_score: Float 0.0–1.0 measuring interaction depth
        - learning_level: Inferred difficulty preference (beginner/intermediate/advanced/mixed/unknown)
        - recent_activity_summary: Human-readable summary like "3 views, 2 searches"

    **Recommendation** (read from the latest AI-generated row in DB)
        - has_recommendation: True if an AI recommendation exists for this user
        - recommendation_summary: The personalised story written by the LLM
        - recommended_products: The top 5 course suggestions
        - confidence_score: How confident the AI was (0.0–1.0)
        - confidence_label: "high" / "medium" / "low" / "none"
        - ai_model: Which LLM model generated this recommendation
        - generated_at: When it was generated

    **Evidence**
        What behavioral signals drove this recommendation.

    **Activity Timeline**
        Last 10 events (views, searches, purchases, etc.) with timestamps.

    **Cache Metadata**
        cache_hit: True if this response was served from Redis (fast path).
        cache_key: The Redis key used (useful for debugging).
    """

    # ── User section ────────────────────────────────────────────────
    user: UserSummary

    # ── Behavior section ────────────────────────────────────────────
    primary_categories:      list[str] = Field(default_factory=list)
    favorite_tags:           list[str] = Field(default_factory=list)
    top_searches:            list[str] = Field(default_factory=list)
    search_frequency:        int       = 0
    engagement_score:        float     = 0.0
    learning_level:          str       = "unknown"
    recent_activity_summary: str       = "No recent activity."
    total_events_analysed:   int       = 0

    # ── Recommendation section ───────────────────────────────────────
    has_recommendation:        bool                  = False
    recommendation_id:         uuid.UUID | None      = None
    recommendation_summary:    str | None            = None
    recommendation_reasoning:  str | None            = None
    recommended_products:      list[RecommendedProduct] = Field(default_factory=list)
    confidence_score:          float                 = 0.0
    confidence_label:          str                   = "none"   # none | low | medium | high
    generated_at:              datetime | None       = None
    recommendation_source:     str                   = "none"   # ai | fallback | none
    ai_model:                  str | None            = None

    # ── Evidence section ────────────────────────────────────────────
    evidence_categories: list[str] = Field(default_factory=list)  # categories that drove retrieval
    evidence_searches:   list[str] = Field(default_factory=list)  # searches that drove retrieval

    # ── Activity timeline ────────────────────────────────────────────
    recent_activity: list[ActivityItem] = Field(default_factory=list)  # last 10 events

    # ── Cache metadata ───────────────────────────────────────────────
    cache_hit:  bool       = False   # True = served from Redis, False = fresh DB read
    cache_key:  str | None = None    # e.g. "dashboard:550e8400-..."


# ------------------------------------------------------------------ #
# AnalyticsResponse — admin platform statistics                      #
# ------------------------------------------------------------------ #

class AnalyticsResponse(AppBaseSchema):
    """
    Platform-wide aggregate statistics returned to admin users.

    This is what powers the admin dashboard stat cards and charts.
    All counts come from live DB queries (cached for 5 minutes).

    Fields
    ------
    total_users          Total registered user accounts.
    total_products       Total products/courses in the catalogue.
    total_events         Total behavioral events across all users.
    total_recommendations Total AI recommendation rows generated.
    cache_hit_rate       Fraction of dashboard requests served from cache (0.0–1.0).
    cache_miss_rate      Fraction that required a fresh DB read (1 - hit_rate).
    top_categories       Top course categories by interaction count.
    top_searches         Most common search queries across all users.
    most_viewed_products Products with the most VIEW events.
    trigger_counts       How many times each trigger rule has fired.
    """

    total_users:          int   = 0
    total_products:       int   = 0
    total_events:         int   = 0
    total_recommendations: int  = 0
    cache_hit_rate:       float = 0.0
    cache_miss_rate:      float = 0.0

    # Each item is {"category": "machine-learning", "count": 42}
    top_categories:       list[dict] = Field(default_factory=list)

    # Each item is {"query": "python ml", "count": 15}
    top_searches:         list[dict] = Field(default_factory=list)

    # Each item is {"title": "Python for ML", "count": 78}
    most_viewed_products: list[dict] = Field(default_factory=list)

    # e.g. {"purchase_or_wishlist": 12, "repeated_search": 8}
    trigger_counts:       dict[str, int] = Field(default_factory=dict)
