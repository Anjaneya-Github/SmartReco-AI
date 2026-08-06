"""
app/services/behavior_analyzer.py
-----------------------------------
Orchestrator for the Behavior Intelligence layer.

Responsibility
~~~~~~~~~~~~~~
Coordinate the three stateless analysis components to produce a
complete ``BehaviorProfile`` for an authenticated user.

Execution flow
~~~~~~~~~~~~~~
1.  Load the user's most recent N events from ``EventRepository``.
2.  Collect the unique product UUIDs referenced in those events.
3.  Batch-fetch the corresponding ``Product`` records from
    ``ProductRepository`` (one SQL query).
4.  Build a product lookup dict (UUID str → Product).
5.  Instantiate ``InterestExtractor`` and ``EngagementScorer``
    with the loaded data (no further DB access).
6.  Compute the recent-activity summary over a rolling 7-day window.
7.  Assemble and return a ``BehaviorProfile``.

Clean-Architecture note
~~~~~~~~~~~~~~~~~~~~~~~
Router → BehaviorAnalyzer → {EventRepository, ProductRepository}
                          → {InterestExtractor, EngagementScorer}

``BehaviorAnalyzer`` is the only service that touches the DB.
``InterestExtractor`` and ``EngagementScorer`` are pure functions
(disguised as classes for testability) — they never touch the DB.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.event import EventType, UserEvent
from app.models.product import Product
from app.repositories.event_repository import EventRepository
from app.repositories.product_repository import ProductRepository
from app.schemas.behavior import BehaviorProfile
from app.services.engagement_scorer import EngagementScorer
from app.services.interest_extractor import InterestExtractor

logger = get_logger(__name__)

# Analysis window — how many recent events to load
_EVENT_WINDOW = 200

# Recent-activity summary window
_RECENT_DAYS = 7


class BehaviorAnalyzer:
    """
    Builds a ``BehaviorProfile`` from a user's interaction history.

    Args:
        db: SQLAlchemy session injected per request via ``get_db``.
    """

    def __init__(self, db: Session) -> None:
        self._event_repo = EventRepository(db)
        self._product_repo = ProductRepository(db)

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def build_profile(self, user_id: uuid.UUID) -> BehaviorProfile:
        """
        Build and return the complete behavioral profile for *user_id*.

        Args:
            user_id: UUID of the authenticated user.

        Returns:
            ``BehaviorProfile`` — computed fresh from the latest events.
        """
        # 1. Load events
        events: list[UserEvent] = self._event_repo.get_recent_events(
            user_id, limit=_EVENT_WINDOW
        )

        if not events:
            logger.debug("No events found for user %s — returning empty profile.", user_id)
            return BehaviorProfile()

        # 2. Collect product IDs referenced in events
        product_ids: list[uuid.UUID] = list(
            {e.product_id for e in events if e.product_id is not None}
        )

        # 3. Batch-fetch products (single SQL round-trip)
        products_list: list[Product] = self._product_repo.get_by_ids(product_ids)
        products: dict[str, Product] = {str(p.id): p for p in products_list}

        # 4. Run stateless analysis components
        extractor = InterestExtractor(events, products)
        scorer = EngagementScorer(events, products)

        # 5. Compute recent-activity summary
        summary = self._recent_activity_summary(events)

        # 6. Determine last active timestamp
        last_active: datetime | None = (
            max((e.created_at for e in events), default=None)
        )

        profile = BehaviorProfile(
            primary_categories=extractor.primary_categories(),
            favorite_tags=extractor.favorite_tags(),
            top_searches=extractor.top_searches(),
            search_frequency=extractor.search_frequency(),
            engagement_score=scorer.engagement_score(),
            learning_level=scorer.learning_level(),
            recent_activity_summary=summary,
            total_events_analysed=len(events),
            last_active_at=last_active,
        )

        logger.info(
            "Behavior profile built. user_id=%s events=%d "
            "engagement=%.4f level=%s",
            user_id,
            len(events),
            profile.engagement_score,
            profile.learning_level,
        )
        return profile

    # ------------------------------------------------------------------ #
    # Private helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _recent_activity_summary(events: list[UserEvent]) -> str:
        """
        Build a human-readable one-liner from the last 7 days of events.

        Format example: "8 views, 3 searches, 2 clicks, 1 purchase"

        Args:
            events: Full analysis-window event list.

        Returns:
            Summary string, or "No recent activity." if the window is empty.
        """
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=_RECENT_DAYS)

        # Collect recent events — handle naive timestamps gracefully
        recent: list[UserEvent] = []
        for e in events:
            ts = e.created_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                recent.append(e)

        if not recent:
            return "No recent activity."

        type_counts: Counter[str] = Counter(
            e.event_type.value for e in recent
        )

        # Display order — most informative types first
        _DISPLAY_ORDER = [
            EventType.PURCHASE,
            EventType.WISHLIST,
            EventType.RATING,
            EventType.SHARE,
            EventType.CLICK,
            EventType.VIEW,
            EventType.SEARCH,
            EventType.IMPRESSION,
        ]

        parts: list[str] = []
        for et in _DISPLAY_ORDER:
            count = type_counts.get(et.value, 0)
            if count:
                noun = et.value + ("s" if count > 1 else "")
                parts.append(f"{count} {noun}")

        return ", ".join(parts) if parts else "No recent activity."
