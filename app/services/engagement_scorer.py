"""
app/services/engagement_scorer.py
-----------------------------------
Pure-Python component that computes engagement and learning-level
signals from a user's raw event list and product metadata.

Responsibility
~~~~~~~~~~~~~~
Answer: *How deeply engaged is this user, and at what level?*

- Engagement score    — float [0.0, 1.0], higher = more engaged
- Learning level      — inferred difficulty preference

Engagement score formula
~~~~~~~~~~~~~~~~~~~~~~~~
Each event type carries a weight (same scale as InterestExtractor).
The raw score is the sum of all event weights, normalised against a
"perfect engagement" ceiling defined as:

    ceiling = window_size × max_event_weight (purchase = 5)

This produces a bounded [0.0, 1.0] value.  A window of 200 events
all being purchases would score 1.0; a window of 200 impressions
would score 0.0.

Learning-level inference
~~~~~~~~~~~~~~~~~~~~~~~~
We look at the difficulty distribution of products the user has
interacted with in high-signal events (weight ≥ 2):

    single dominant level (>60% of interactions) → that level
    two levels tied within 15%                   → "mixed"
    fewer than 3 product interactions             → "unknown"
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from app.models.event import EventType, UserEvent

if TYPE_CHECKING:
    from app.models.product import Product

# Same weights as InterestExtractor — defined here independently so
# EngagementScorer has no dependency on InterestExtractor.
_EVENT_WEIGHT: dict[EventType, int] = {
    EventType.PURCHASE:   5,
    EventType.WISHLIST:   4,
    EventType.RATING:     3,
    EventType.SHARE:      3,
    EventType.CLICK:      2,
    EventType.VIEW:       1,
    EventType.IMPRESSION: 0,
    EventType.SEARCH:     0,
}

_MAX_WEIGHT = 5       # purchase weight = ceiling per event
_MIN_PRODUCT_INTERACTIONS_FOR_LEVEL = 3
_DOMINANT_THRESHOLD = 0.60   # >60% of interactions in one difficulty


class EngagementScorer:
    """
    Computes engagement depth and learning-level preference.

    Args:
        events:   The user's recent events.
        products: Dict mapping product UUID (str) → Product ORM object.
    """

    def __init__(
        self,
        events: list[UserEvent],
        products: dict[str, "Product"],
    ) -> None:
        self._events = events
        self._products = products

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def engagement_score(self) -> float:
        """
        Compute a normalised engagement score in [0.0, 1.0].

        Returns:
            Float rounded to 4 decimal places.
        """
        if not self._events:
            return 0.0

        raw_score = sum(
            _EVENT_WEIGHT.get(e.event_type, 0) for e in self._events
        )
        ceiling = len(self._events) * _MAX_WEIGHT

        if ceiling == 0:
            return 0.0

        return round(min(raw_score / ceiling, 1.0), 4)

    def learning_level(self) -> str:
        """
        Infer the user's preferred difficulty level from product interactions.

        Returns:
            One of: "beginner", "intermediate", "advanced", "mixed", "unknown".
        """
        counter: Counter[str] = Counter()

        for event in self._events:
            # Only count high-signal interactions (click and above)
            if _EVENT_WEIGHT.get(event.event_type, 0) < 2:
                continue
            if event.product_id is None:
                continue
            product = self._products.get(str(event.product_id))
            if product and product.difficulty:
                counter[product.difficulty.lower()] += 1

        total = sum(counter.values())
        if total < _MIN_PRODUCT_INTERACTIONS_FOR_LEVEL:
            return "unknown"

        most_common = counter.most_common(2)
        top_level, top_count = most_common[0]
        top_ratio = top_count / total

        if top_ratio >= _DOMINANT_THRESHOLD:
            return top_level

        # Two levels are close together
        if len(most_common) >= 2:
            second_level, second_count = most_common[1]
            # If top two together cover >80% of interactions → mixed
            if (top_count + second_count) / total > 0.80:
                return "mixed"

        return "mixed"

    def top_interests(self) -> list[str]:
        """
        Return the top product categories by engagement-weighted count.

        This mirrors what ``InterestExtractor.primary_categories`` does
        but is re-exposed here so ``EngagementScorer`` can be used
        standalone in contexts that need both score and interests.

        Returns:
            Ordered list of category slugs, most-engaged first (top 5).
        """
        counter: Counter[str] = Counter()
        for event in self._events:
            weight = _EVENT_WEIGHT.get(event.event_type, 0)
            if weight == 0 or event.product_id is None:
                continue
            product = self._products.get(str(event.product_id))
            if product and product.category:
                counter[product.category] += weight
        return [cat for cat, _ in counter.most_common(5)]
