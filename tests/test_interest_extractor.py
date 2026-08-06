"""
tests/test_interest_extractor.py
----------------------------------
Unit tests for InterestExtractor.

All tests are pure-Python — no database, no HTTP server, no ORM session.
Events and products are built using object-level construction.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.models.event import EventType, UserEvent
from app.models.product import Product
from app.services.interest_extractor import InterestExtractor


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _event(
    event_type: EventType,
    product_id: uuid.UUID | None = None,
    search_query: str | None = None,
) -> UserEvent:
    """Build a minimal UserEvent without a DB session."""
    e = UserEvent.__new__(UserEvent)
    e.id = uuid.uuid4()
    e.user_id = uuid.uuid4()
    e.session_id = "sess"
    e.event_type = event_type
    e.product_id = product_id
    e.search_query = search_query
    e.event_metadata = {}
    e.created_at = datetime.now(tz=timezone.utc)
    return e


def _product(
    category: str | None = "machine-learning",
    difficulty: str | None = "beginner",
    tags: list[str] | None = None,
) -> tuple[uuid.UUID, Product]:
    """Return (uuid, Product mock)."""
    pid = uuid.uuid4()
    p = MagicMock(spec=Product)
    p.id = pid
    p.category = category
    p.difficulty = difficulty
    p.tags = tags or ["python", "ml"]
    return pid, p


# ------------------------------------------------------------------ #
# primary_categories                                                  #
# ------------------------------------------------------------------ #

class TestPrimaryCategories:

    def test_empty_events_returns_empty(self):
        ix = InterestExtractor([], {})
        assert ix.primary_categories() == []

    def test_single_view_returns_category(self):
        pid, prod = _product("machine-learning")
        events = [_event(EventType.VIEW, pid)]
        ix = InterestExtractor(events, {str(pid): prod})
        assert ix.primary_categories() == ["machine-learning"]

    def test_purchase_outweighs_five_views(self):
        pid1, p1 = _product("data-science")
        pid2, p2 = _product("web-dev")
        # 5 views of web-dev vs 1 purchase of data-science
        events = [_event(EventType.VIEW, pid2)] * 5
        events += [_event(EventType.PURCHASE, pid1)]
        ix = InterestExtractor(events, {str(pid1): p1, str(pid2): p2})
        cats = ix.primary_categories()
        # data-science: 5 pts (purchase=5); web-dev: 5 pts (5×view=5)
        # Tied — both should appear
        assert "data-science" in cats
        assert "web-dev" in cats

    def test_impression_events_excluded(self):
        pid, prod = _product("excluded-cat")
        events = [_event(EventType.IMPRESSION, pid)] * 10
        ix = InterestExtractor(events, {str(pid): prod})
        assert ix.primary_categories() == []

    def test_missing_product_silently_skipped(self):
        events = [_event(EventType.VIEW, uuid.uuid4())]
        ix = InterestExtractor(events, {})  # empty product dict
        assert ix.primary_categories() == []

    def test_product_without_category_excluded(self):
        pid, prod = _product(category=None)
        events = [_event(EventType.VIEW, pid)]
        ix = InterestExtractor(events, {str(pid): prod})
        assert ix.primary_categories() == []

    def test_top_categories_ranked_correctly(self):
        pid_a, pa = _product("category-a")
        pid_b, pb = _product("category-b")
        pid_c, pc = _product("category-c")
        events = (
            [_event(EventType.VIEW, pid_a)] * 10 +   # 10 pts
            [_event(EventType.CLICK, pid_b)] * 3 +   # 6 pts
            [_event(EventType.VIEW, pid_c)] * 1      # 1 pt
        )
        ix = InterestExtractor(events, {
            str(pid_a): pa, str(pid_b): pb, str(pid_c): pc,
        })
        cats = ix.primary_categories()
        assert cats[0] == "category-a"
        assert cats[1] == "category-b"
        assert cats[2] == "category-c"


# ------------------------------------------------------------------ #
# favorite_tags                                                        #
# ------------------------------------------------------------------ #

class TestFavoriteTags:

    def test_empty_events_returns_empty(self):
        ix = InterestExtractor([], {})
        assert ix.favorite_tags() == []

    def test_tags_aggregated_from_product(self):
        pid, prod = _product(tags=["python", "numpy", "pandas"])
        events = [_event(EventType.VIEW, pid)]
        ix = InterestExtractor(events, {str(pid): prod})
        tags = ix.favorite_tags()
        assert "python" in tags
        assert "numpy" in tags

    def test_tags_weighted_by_event_type(self):
        pid, prod = _product(tags=["shared-tag"])
        events = (
            [_event(EventType.PURCHASE, pid)] +   # weight 5
            [_event(EventType.IMPRESSION, pid)] * 10  # weight 0
        )
        ix = InterestExtractor(events, {str(pid): prod})
        # Impression events contribute 0 — only the purchase matters
        assert "shared-tag" in ix.favorite_tags()

    def test_product_with_no_tags_ignored(self):
        pid, prod = _product(tags=[])
        events = [_event(EventType.VIEW, pid)]
        ix = InterestExtractor(events, {str(pid): prod})
        assert ix.favorite_tags() == []


# ------------------------------------------------------------------ #
# top_searches / search_frequency                                     #
# ------------------------------------------------------------------ #

class TestSearches:

    def test_empty_events_returns_zero_and_empty(self):
        ix = InterestExtractor([], {})
        assert ix.search_frequency() == 0
        assert ix.top_searches() == []

    def test_search_frequency_counts_only_search_events(self):
        pid, prod = _product()
        events = [
            _event(EventType.SEARCH, search_query="python"),
            _event(EventType.SEARCH, search_query="ml"),
            _event(EventType.VIEW, pid),
        ]
        ix = InterestExtractor(events, {str(pid): prod})
        assert ix.search_frequency() == 2

    def test_top_searches_normalised_lowercase(self):
        events = [
            _event(EventType.SEARCH, search_query="Python ML"),
            _event(EventType.SEARCH, search_query="  python ml  "),
        ]
        ix = InterestExtractor(events, {})
        searches = ix.top_searches()
        assert "python ml" in searches

    def test_top_searches_ranked_by_frequency(self):
        events = (
            [_event(EventType.SEARCH, search_query="deep learning")] * 5 +
            [_event(EventType.SEARCH, search_query="nlp")] * 2
        )
        ix = InterestExtractor(events, {})
        assert ix.top_searches()[0] == "deep learning"

    def test_repeated_searches_only_returns_multi_occurrence(self):
        events = [
            _event(EventType.SEARCH, search_query="transformers"),
            _event(EventType.SEARCH, search_query="transformers"),
            _event(EventType.SEARCH, search_query="unique-query"),
        ]
        ix = InterestExtractor(events, {})
        repeated = ix.repeated_searches()
        assert "transformers" in repeated
        assert "unique-query" not in repeated

    def test_no_repeated_searches_returns_empty(self):
        events = [
            _event(EventType.SEARCH, search_query="q1"),
            _event(EventType.SEARCH, search_query="q2"),
        ]
        ix = InterestExtractor(events, {})
        assert ix.repeated_searches() == []
