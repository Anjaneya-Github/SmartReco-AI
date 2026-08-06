"""
app/services/interest_extractor.py
------------------------------------
Pure-Python component that derives interest signals from a user's
raw event list and a corresponding product catalogue snapshot.

Responsibility
~~~~~~~~~~~~~~
Answer: *What does this user care about?*

- Primary categories  — ranked by weighted interaction count
- Favorite tags       — ranked by co-occurrence with high-signal events
- Top searches        — most-repeated normalised query strings
- Search frequency    — total SEARCH event count

This class is stateless and dependency-free (no DB, no network).
It receives pre-loaded data and returns plain Python values, which
makes it trivial to unit-test in isolation.

Weighting scheme
~~~~~~~~~~~~~~~~
Event weights reflect how much deliberate intent each action signals:

    purchase  = 5   (highest intent — user committed money)
    wishlist  = 4   (strong intent — saved for later)
    rating    = 3   (explicit feedback)
    share     = 3   (strong positive signal)
    click     = 2   (moderate intent)
    view      = 1   (passive consumption)
    impression = 0  (passive exposure — does not count toward interests)
    search     = 0  (handled separately via search_frequency / top_searches)
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from app.models.event import EventType, UserEvent

if TYPE_CHECKING:
    from app.models.product import Product

# Interaction weight by event type — 0 means "do not count toward interests"
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

# How many top results to surface in each list
_TOP_N = 10


class InterestExtractor:
    """
    Derives interest signals from events and product metadata.

    Args:
        events:   The user's recent events (any order; filtered internally).
        products: Dict mapping product UUID → Product ORM object.
                  May be a subset — missing products are silently skipped.
    """

    def __init__(
        self,
        events: list[UserEvent],
        products: dict[str, "Product"],
    ) -> None:
        self._events = events
        self._products = products  # product_id (str) → Product

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def primary_categories(self) -> list[str]:
        """
        Return top categories ranked by weighted interaction count.

        Only product-related events (VIEW, CLICK, PURCHASE …) where
        we can resolve the product's category contribute.

        Returns:
            Ordered list of category slugs, most-engaged first.
        """
        counter: Counter[str] = Counter()
        for event in self._events:
            weight = _EVENT_WEIGHT.get(event.event_type, 0)
            if weight == 0 or event.product_id is None:
                continue
            product = self._products.get(str(event.product_id))
            if product and product.category:
                counter[product.category] += weight

        return [cat for cat, _ in counter.most_common(_TOP_N)]

    def favorite_tags(self) -> list[str]:
        """
        Return most-frequent product tags across weighted interactions.

        Each tag from a product's tag list is weighted by the event that
        triggered the interaction.

        Returns:
            Ordered list of tag strings, most-frequent first.
        """
        counter: Counter[str] = Counter()
        for event in self._events:
            weight = _EVENT_WEIGHT.get(event.event_type, 0)
            if weight == 0 or event.product_id is None:
                continue
            product = self._products.get(str(event.product_id))
            if product:
                for tag in (product.tags or []):
                    counter[tag] += weight

        return [tag for tag, _ in counter.most_common(_TOP_N)]

    def top_searches(self) -> list[str]:
        """
        Return most-repeated search query terms, normalised to lowercase.

        Deduplication: identical queries are counted once per occurrence
        (repetition is intentional signal — the user keeps searching for
        the same thing, which is a strong interest indicator).

        Returns:
            Ordered list of query strings, most-repeated first.
        """
        counter: Counter[str] = Counter()
        for event in self._events:
            if event.event_type is EventType.SEARCH and event.search_query:
                normalised = event.search_query.strip().lower()
                if normalised:
                    counter[normalised] += 1

        return [q for q, _ in counter.most_common(_TOP_N)]

    def search_frequency(self) -> int:
        """
        Count total SEARCH events in the provided event list.

        Returns:
            Non-negative integer.
        """
        return sum(
            1 for e in self._events if e.event_type is EventType.SEARCH
        )

    def repeated_searches(self) -> list[str]:
        """
        Return queries the user has searched for more than once.

        Used by ``RecommendationTrigger`` to detect repeated search
        intent (one of the trigger rules).

        Returns:
            List of repeated query strings.
        """
        counter: Counter[str] = Counter()
        for event in self._events:
            if event.event_type is EventType.SEARCH and event.search_query:
                normalised = event.search_query.strip().lower()
                if normalised:
                    counter[normalised] += 1
        return [q for q, count in counter.items() if count > 1]
