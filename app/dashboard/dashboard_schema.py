"""app/dashboard/dashboard_schema.py — Read-only dashboard response schemas."""
from __future__ import annotations
import uuid
from datetime import datetime
from pydantic import Field
from app.schemas.common import AppBaseSchema
from app.schemas.recommendation import RecommendedProduct


class ActivityItem(AppBaseSchema):
    event_type: str
    product_title: str | None = None
    search_query: str | None = None
    created_at: datetime


class UserSummary(AppBaseSchema):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: str
    is_active: bool
    member_since: datetime


class DashboardResponse(AppBaseSchema):
    """Full dashboard payload — all reads, no generation."""
    # User
    user: UserSummary
    # Behavior
    primary_categories: list[str] = Field(default_factory=list)
    favorite_tags: list[str] = Field(default_factory=list)
    top_searches: list[str] = Field(default_factory=list)
    engagement_score: float = 0.0
    learning_level: str = "unknown"
    recent_activity_summary: str = "No recent activity."
    total_events_analysed: int = 0
    # Recommendation
    has_recommendation: bool = False
    recommendation_id: uuid.UUID | None = None
    recommendation_summary: str | None = None
    recommendation_reasoning: str | None = None
    recommended_products: list[RecommendedProduct] = Field(default_factory=list)
    confidence_score: float = 0.0
    confidence_label: str = "none"         # none / low / medium / high
    generated_at: datetime | None = None
    recommendation_source: str = "none"    # ai / fallback / none
    ai_model: str | None = None
    # Evidence
    evidence_categories: list[str] = Field(default_factory=list)
    evidence_searches: list[str] = Field(default_factory=list)
    # Recent activity timeline (last 10 events)
    recent_activity: list[ActivityItem] = Field(default_factory=list)
    # Cache
    cache_hit: bool = False
    cache_key: str | None = None


class AnalyticsResponse(AppBaseSchema):
    """Admin analytics aggregate."""
    total_users: int = 0
    total_products: int = 0
    total_events: int = 0
    total_recommendations: int = 0
    cache_hit_rate: float = 0.0
    cache_miss_rate: float = 0.0
    top_categories: list[dict] = Field(default_factory=list)
    top_searches: list[dict] = Field(default_factory=list)
    most_viewed_products: list[dict] = Field(default_factory=list)
    trigger_counts: dict[str, int] = Field(default_factory=dict)
