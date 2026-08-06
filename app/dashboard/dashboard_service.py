"""app/dashboard/dashboard_service.py — Read-only dashboard aggregation service."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.cache.redis_client import CacheClient
from app.cache.keys import (
    dashboard_key, behavior_key, hash_dict,
    TTL_DASHBOARD, TTL_BEHAVIOR, TTL_ANALYTICS, analytics_key,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.dashboard.dashboard_schema import (
    ActivityItem, AnalyticsResponse, DashboardResponse, UserSummary,
)
from app.models.event import UserEvent
from app.models.product import Product
from app.models.recommendation import Recommendation
from app.models.user import User
from app.repositories.event_repository import EventRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.recommendation_repository import RecommendationRepository
from app.repositories.user_repository import UserRepository
from app.schemas.recommendation import RecommendedProduct
from app.services.behavior_analyzer import BehaviorAnalyzer

logger = get_logger(__name__)


def _confidence_label(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    if score > 0.0:
        return "low"
    return "none"


class DashboardService:
    """Aggregate all dashboard data from DB/cache. Never generates recommendations."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._cache = CacheClient()
        self._user_repo = UserRepository(db)
        self._event_repo = EventRepository(db)
        self._product_repo = ProductRepository(db)
        self._rec_repo = RecommendationRepository(db)

    def get_dashboard(self, user_id: uuid.UUID) -> DashboardResponse:
        """Return full dashboard — cache-first."""
        cache_k = dashboard_key(str(user_id))
        cached = self._cache.get(cache_k)
        if cached:
            logger.debug("dashboard cache hit user_id=%s", user_id)
            cached["cache_hit"] = True
            cached["cache_key"] = cache_k
            return DashboardResponse(**cached)

        user = self._user_repo.get_by_id(user_id)
        if not user:
            from app.core.exceptions import NotFoundException
            raise NotFoundException("User not found.")

        # Behavior profile (cache-aware)
        bkey = behavior_key(str(user_id))
        profile_dict = self._cache.get(bkey)
        if profile_dict is None:
            analyzer = BehaviorAnalyzer(self._db)
            profile = analyzer.build_profile(user_id)
            profile_dict = {
                "primary_categories": profile.primary_categories,
                "favorite_tags": profile.favorite_tags,
                "top_searches": profile.top_searches,
                "engagement_score": profile.engagement_score,
                "learning_level": profile.learning_level,
                "recent_activity_summary": profile.recent_activity_summary,
                "total_events_analysed": profile.total_events_analysed,
            }
            self._cache.set(bkey, profile_dict, TTL_BEHAVIOR)

        # Latest recommendation
        rec = self._rec_repo.get_latest_for_user(user_id)
        reco_products: list[RecommendedProduct] = []
        if rec:
            pids = [
                uuid.UUID(p["product_id"]) if isinstance(p, dict) else uuid.UUID(str(p))
                for p in rec.recommended_products
            ]
            products = self._product_repo.get_by_ids(pids)
            pm = {str(p.id): p for p in products}
            for item in rec.recommended_products:
                pid = str(item.get("product_id", "")) if isinstance(item, dict) else str(item)
                p = pm.get(pid)
                reco_products.append(RecommendedProduct(
                    product_id=uuid.UUID(pid) if pid else uuid.uuid4(),
                    title=p.title if p else item.get("title", "") if isinstance(item, dict) else "",
                    category=p.category if p else None,
                    difficulty=p.difficulty if p else None,
                    tags=p.tags if p else [],
                ))

        # Recent activity timeline (last 10 events)
        recent_events = self._event_repo.get_recent_events(user_id, limit=10)
        pids_for_activity = [e.product_id for e in recent_events if e.product_id]
        activity_products = self._product_repo.get_by_ids(pids_for_activity) if pids_for_activity else []
        ap_map = {str(p.id): p for p in activity_products}
        timeline: list[ActivityItem] = []
        for e in recent_events:
            p = ap_map.get(str(e.product_id)) if e.product_id else None
            timeline.append(ActivityItem(
                event_type=e.event_type.value,
                product_title=p.title if p else None,
                search_query=e.search_query,
                created_at=e.created_at,
            ))

        confidence = rec.confidence if rec else 0.0
        dash = DashboardResponse(
            user=UserSummary(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=user.role.value,
                is_active=user.is_active,
                member_since=user.created_at,
            ),
            primary_categories=profile_dict.get("primary_categories", []),
            favorite_tags=profile_dict.get("favorite_tags", []),
            top_searches=profile_dict.get("top_searches", []),
            engagement_score=profile_dict.get("engagement_score", 0.0),
            learning_level=profile_dict.get("learning_level", "unknown"),
            recent_activity_summary=profile_dict.get("recent_activity_summary", ""),
            total_events_analysed=profile_dict.get("total_events_analysed", 0),
            has_recommendation=rec is not None,
            recommendation_id=rec.id if rec else None,
            recommendation_summary=rec.summary if rec else None,
            recommendation_reasoning=rec.reasoning if rec else None,
            recommended_products=reco_products,
            confidence_score=confidence,
            confidence_label=_confidence_label(confidence),
            generated_at=rec.generated_at if rec else None,
            recommendation_source="ai" if rec and confidence > 0.1 else ("fallback" if rec else "none"),
            ai_model=settings.LLM_MODEL if rec else None,
            evidence_categories=profile_dict.get("primary_categories", [])[:3],
            evidence_searches=profile_dict.get("top_searches", [])[:3],
            recent_activity=timeline,
            cache_hit=False,
            cache_key=cache_k,
        )

        self._cache.set(cache_k, dash.model_dump(), TTL_DASHBOARD)
        return dash

    def get_analytics(self) -> AnalyticsResponse:
        """Admin analytics — cached 5 min."""
        cache_k = analytics_key()
        cached = self._cache.get(cache_k)
        if cached:
            return AnalyticsResponse(**cached)

        from sqlalchemy import distinct, text as sa_text
        db = self._db

        total_users = db.execute(select(func.count(User.id))).scalar_one()
        total_products = db.execute(select(func.count(Product.id))).scalar_one()
        total_events = db.execute(select(func.count(UserEvent.id))).scalar_one()
        total_recs = db.execute(select(func.count(Recommendation.id))).scalar_one()

        # Top categories from events → products
        cat_rows = db.execute(
            select(Product.category, func.count(UserEvent.id).label("cnt"))
            .join(UserEvent, UserEvent.product_id == Product.id)
            .where(Product.category.isnot(None))
            .group_by(Product.category)
            .order_by(func.count(UserEvent.id).desc())
            .limit(10)
        ).all()
        top_cats = [{"category": r[0], "count": r[1]} for r in cat_rows]

        # Top searches
        search_rows = db.execute(
            select(UserEvent.search_query, func.count(UserEvent.id).label("cnt"))
            .where(UserEvent.search_query.isnot(None))
            .group_by(UserEvent.search_query)
            .order_by(func.count(UserEvent.id).desc())
            .limit(10)
        ).all()
        top_searches = [{"query": r[0], "count": r[1]} for r in search_rows]

        # Most viewed products
        view_rows = db.execute(
            select(Product.title, func.count(UserEvent.id).label("cnt"))
            .join(UserEvent, UserEvent.product_id == Product.id)
            .group_by(Product.title)
            .order_by(func.count(UserEvent.id).desc())
            .limit(10)
        ).all()
        most_viewed = [{"title": r[0], "count": r[1]} for r in view_rows]

        result = AnalyticsResponse(
            total_users=total_users,
            total_products=total_products,
            total_events=total_events,
            total_recommendations=total_recs,
            cache_hit_rate=0.0,
            cache_miss_rate=0.0,
            top_categories=top_cats,
            top_searches=top_searches,
            most_viewed_products=most_viewed,
            trigger_counts={},
        )
        self._cache.set(cache_k, result.model_dump(), TTL_ANALYTICS)
        return result

    def invalidate_user(self, user_id: str) -> None:
        """Invalidate all cache keys for a user."""
        self._cache.delete(dashboard_key(user_id))
        self._cache.delete(behavior_key(user_id))
        self._cache.delete_pattern(f"recommendation:{user_id}:*")
