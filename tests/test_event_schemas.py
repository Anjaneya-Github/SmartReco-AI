"""
tests/test_event_schemas.py
----------------------------
Unit tests for EventRequest and BatchEventRequest Pydantic schemas.

Tests are pure-Python — no database or HTTP server required.
They validate that:
- Valid payloads are accepted and normalised correctly.
- Invalid payloads are rejected with clear errors.
- Cross-field rules (product_id required for product events,
  search_query required for SEARCH) are enforced.
- Batch size limits are enforced.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.models.event import EventType
from app.schemas.event import (
    BatchEventRequest,
    EventRequest,
    MAX_BATCH_SIZE,
)


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _product_event(event_type: str = "view", **overrides) -> dict:
    return {
        "session_id": "sess-abc",
        "event_type": event_type,
        "product_id": str(uuid.uuid4()),
        **overrides,
    }

def _search_event(**overrides) -> dict:
    return {
        "session_id": "sess-abc",
        "event_type": "search",
        "search_query": "python machine learning",
        **overrides,
    }


# ------------------------------------------------------------------ #
# EventRequest — valid cases                                         #
# ------------------------------------------------------------------ #

class TestEventRequestValid:

    def test_view_event_accepted(self):
        e = EventRequest(**_product_event("view"))
        assert e.event_type == EventType.VIEW
        assert e.product_id is not None

    def test_click_event_accepted(self):
        e = EventRequest(**_product_event("click"))
        assert e.event_type == EventType.CLICK

    def test_purchase_event_accepted(self):
        e = EventRequest(**_product_event("purchase"))
        assert e.event_type == EventType.PURCHASE

    def test_wishlist_event_accepted(self):
        e = EventRequest(**_product_event("wishlist"))
        assert e.event_type == EventType.WISHLIST

    def test_rating_event_accepted(self):
        e = EventRequest(**_product_event("rating", metadata={"score": 4}))
        assert e.event_type == EventType.RATING
        assert e.metadata["score"] == 4

    def test_search_event_accepted(self):
        e = EventRequest(**_search_event())
        assert e.event_type == EventType.SEARCH
        assert e.search_query == "python machine learning"

    def test_metadata_defaults_to_empty_dict(self):
        e = EventRequest(**_product_event())
        assert e.metadata == {}

    def test_session_id_stripped_of_whitespace(self):
        e = EventRequest(**_product_event(session_id="  sess-trim  "))
        assert e.session_id == "sess-trim"

    def test_all_event_types_roundtrip(self):
        """Every EventType value should deserialise without error."""
        product_types = {
            EventType.VIEW, EventType.CLICK, EventType.PURCHASE,
            EventType.WISHLIST, EventType.RATING, EventType.SHARE,
            EventType.IMPRESSION,
        }
        for et in EventType:
            if et in product_types:
                data = _product_event(et.value)
            else:
                data = _search_event()
            e = EventRequest(**data)
            assert e.event_type == et


# ------------------------------------------------------------------ #
# EventRequest — invalid cases                                       #
# ------------------------------------------------------------------ #

class TestEventRequestInvalid:

    def test_unknown_event_type_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            EventRequest(session_id="s", event_type="explode")
        assert "event_type" in str(exc_info.value).lower()

    def test_view_without_product_id_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            EventRequest(session_id="s", event_type="view")
        assert "product_id" in str(exc_info.value)

    def test_click_without_product_id_rejected(self):
        with pytest.raises(ValidationError):
            EventRequest(session_id="s", event_type="click")

    def test_purchase_without_product_id_rejected(self):
        with pytest.raises(ValidationError):
            EventRequest(session_id="s", event_type="purchase")

    def test_search_without_query_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            EventRequest(session_id="s", event_type="search")
        assert "search_query" in str(exc_info.value)

    def test_search_with_empty_query_rejected(self):
        with pytest.raises(ValidationError):
            EventRequest(session_id="s", event_type="search", search_query="")

    def test_empty_session_id_rejected(self):
        with pytest.raises(ValidationError):
            EventRequest(**_product_event(session_id=""))

    def test_session_id_too_long_rejected(self):
        with pytest.raises(ValidationError):
            EventRequest(**_product_event(session_id="x" * 129))

    def test_missing_session_id_rejected(self):
        with pytest.raises(ValidationError):
            EventRequest(event_type="view", product_id=str(uuid.uuid4()))


# ------------------------------------------------------------------ #
# BatchEventRequest                                                  #
# ------------------------------------------------------------------ #

class TestBatchEventRequest:

    def test_single_event_batch_accepted(self):
        b = BatchEventRequest(events=[_product_event()])
        assert len(b.events) == 1

    def test_multiple_events_accepted(self):
        events = [_product_event("view") for _ in range(10)]
        events += [_search_event() for _ in range(5)]
        b = BatchEventRequest(events=events)
        assert len(b.events) == 15

    def test_empty_batch_rejected(self):
        with pytest.raises(ValidationError):
            BatchEventRequest(events=[])

    def test_batch_at_max_size_accepted(self):
        events = [_product_event() for _ in range(MAX_BATCH_SIZE)]
        b = BatchEventRequest(events=events)
        assert len(b.events) == MAX_BATCH_SIZE

    def test_batch_exceeding_max_size_rejected(self):
        events = [_product_event() for _ in range(MAX_BATCH_SIZE + 1)]
        with pytest.raises(ValidationError):
            BatchEventRequest(events=events)

    def test_mixed_valid_events_accepted(self):
        """VIEW, SEARCH, PURCHASE all in one batch."""
        pid = str(uuid.uuid4())
        b = BatchEventRequest(events=[
            {"session_id": "s1", "event_type": "view",     "product_id": pid},
            {"session_id": "s1", "event_type": "search",   "search_query": "deep learning"},
            {"session_id": "s1", "event_type": "purchase", "product_id": pid},
        ])
        assert len(b.events) == 3
        types = {e.event_type for e in b.events}
        assert EventType.VIEW in types
        assert EventType.SEARCH in types
        assert EventType.PURCHASE in types

    def test_one_invalid_event_rejects_whole_batch(self):
        """A single invalid event should cause the entire request to fail."""
        with pytest.raises(ValidationError):
            BatchEventRequest(events=[
                _product_event("view"),   # valid
                {"session_id": "s", "event_type": "view"},  # missing product_id
            ])
