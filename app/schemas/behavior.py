"""
app/schemas/behavior.py
------------------------
Pydantic v2 schemas for the Behavior Intelligence layer.

BehaviorProfile   — computed behavioral summary for a user
TriggerStatus     — whether a recommendation trigger has fired
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field

from app.schemas.common import AppBaseSchema


class BehaviorProfile(AppBaseSchema):
    """
    Aggregated behavioral fingerprint computed from a user's event history.

    All fields are derived entirely from ``UserEvent`` records — no LLM,
    no external API calls.  The profile is computed fresh on each request
    so it always reflects the latest activity.

    Fields
    ~~~~~~
    primary_categories
        The top content categories the user has interacted with (viewed,
        clicked, purchased), ranked by interaction frequency.

    favorite_tags
        Most-frequent product tags across all product interactions.

    top_searches
        Most-repeated search query terms (normalised to lowercase).

    search_frequency
        Number of SEARCH events in the analysis window.

    engagement_score
        Float in [0.0, 1.0].  Computed as a weighted sum of high-value
        interactions (purchase > wishlist > rating > click > view >
        impression) normalised against the window size.

    learning_level
        Inferred difficulty preference: "beginner" | "intermediate" |
        "advanced" | "mixed" | "unknown".  Derived from the difficulty
        distribution of products the user has viewed or purchased.

    recent_activity_summary
        Human-readable one-line summary of activity in the last 7 days,
        e.g. "12 views, 3 searches, 1 purchase".

    total_events_analysed
        Number of events used to build this profile (window size).

    last_active_at
        Timestamp of the user's most recent event, or ``None`` if no
        events exist yet.
    """

    primary_categories: list[str] = Field(
        default_factory=list,
        description="Top categories ranked by interaction count.",
    )
    favorite_tags: list[str] = Field(
        default_factory=list,
        description="Most-frequent product tags across interactions.",
    )
    top_searches: list[str] = Field(
        default_factory=list,
        description="Most-repeated search queries (lowercase, deduplicated).",
    )
    search_frequency: int = Field(
        default=0,
        ge=0,
        description="Total SEARCH events in the analysis window.",
    )
    engagement_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Normalised engagement score in [0.0, 1.0].",
    )
    learning_level: str = Field(
        default="unknown",
        description=(
            "Inferred difficulty preference: "
            "beginner | intermediate | advanced | mixed | unknown."
        ),
    )
    recent_activity_summary: str = Field(
        default="No recent activity.",
        description="One-line summary of the last 7 days of activity.",
    )
    total_events_analysed: int = Field(
        default=0,
        ge=0,
        description="Number of events used to build this profile.",
    )
    last_active_at: datetime | None = Field(
        default=None,
        description="Timestamp of the user's most recent event.",
    )


class TriggerStatus(AppBaseSchema):
    """
    Result of evaluating whether a recommendation run should be triggered.

    Fields
    ~~~~~~
    should_trigger
        True if any trigger condition is met.

    reason
        Human-readable explanation of which rule fired (or "none").

    rules_evaluated
        Dictionary mapping each rule name to its boolean result, useful
        for debugging and logging.
    """

    should_trigger: bool
    reason: str
    rules_evaluated: dict[str, bool] = Field(default_factory=dict)
