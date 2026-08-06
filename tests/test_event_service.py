"""
tests/test_event_service.py
----------------------------
Unit tests for EventService — uses a mock repository so no database
connection is required.

Tests verify:
- ``ingest_batch`` delegates to the repository with the correct rows.
- ``user_id`` from the caller (JWT) is injected into every event row.
- The service commits after a successful batch.
- The service raises ``BadRequestException`` when the batch cap is exceeded.
- ``get_my_events`` returns a correctly shaped ``PaginatedResponse``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.core.exceptions import BadRequestException
from app.models.event import EventType, UserEvent
from app.schemas.event import (
    BatchEventRequest,
    BatchEventResponse,
    MAX_BATCH_SIZE,
)
from app.services.event_service import EventService


# ------------------------------------------------------------------ #
# Fixtures                                                           #
# ------------------------------------------------------------------ #

@pytest.fixture()
def mock_db():
    """A minimal SQLAlchemy Session mock."""
    db = MagicMock()
    db.commit = MagicMock()
    db.rollback = MagicMock()
    return db


@pytest.fixture()
def mock_repo(mock_db):
    """Mock EventRepository injected into EventService."""
    with patch("app.services.event_service.EventRepository") as MockRepo:
        repo_instance = MagicMock()
        MockRepo.return_value = repo_instance
        yield repo_instance


@pytest.fixture()
def service(mock_db, mock_repo):
    return EventService(mock_db)


def _make_event(event_type: str = "view", pid: uuid.UUID | None = None) -> dict:
    if pid is None:
        pid = uuid.uuid4()
    return {
        "session_id": "sess-test",
        "event_type": event_type,
        "product_id": str(pid),
    }


def _make_batch(*events: dict) -> BatchEventRequest:
    return BatchEventRequest(events=list(events))


# ------------------------------------------------------------------ #
# ingest_batch                                                       #
# ------------------------------------------------------------------ #

class TestIngestBatch:

    def test_delegates_to_repository(self, service, mock_repo, mock_db):
        uid = uuid.uuid4()
        pids = [uuid.uuid4() for _ in range(3)]
        batch = _make_batch(*[_make_event("view", p) for p in pids])

        mock_repo.insert_batch.return_value = [uuid.uuid4() for _ in range(3)]

        result = service.ingest_batch(user_id=uid, payload=batch)

        mock_repo.insert_batch.assert_called_once()
        rows_arg = mock_repo.insert_batch.call_args[0][0]
        assert len(rows_arg) == 3

    def test_user_id_injected_into_every_row(self, service, mock_repo, mock_db):
        uid = uuid.uuid4()
        batch = _make_batch(_make_event("click"), _make_event("view"))
        mock_repo.insert_batch.return_value = [uuid.uuid4(), uuid.uuid4()]

        service.ingest_batch(user_id=uid, payload=batch)

        rows = mock_repo.insert_batch.call_args[0][0]
        for row in rows:
            assert row["user_id"] == uid

    def test_commits_on_success(self, service, mock_repo, mock_db):
        uid = uuid.uuid4()
        batch = _make_batch(_make_event())
        mock_repo.insert_batch.return_value = [uuid.uuid4()]

        service.ingest_batch(user_id=uid, payload=batch)

        mock_db.commit.assert_called_once()

    def test_returns_accepted_count_and_ids(self, service, mock_repo, mock_db):
        uid = uuid.uuid4()
        generated_ids = [uuid.uuid4(), uuid.uuid4()]
        batch = _make_batch(_make_event(), _make_event("click"))
        mock_repo.insert_batch.return_value = generated_ids

        result = service.ingest_batch(user_id=uid, payload=batch)

        assert isinstance(result, BatchEventResponse)
        assert result.accepted == 2
        assert result.event_ids == generated_ids

    def test_raises_bad_request_when_cap_exceeded(self, service, mock_repo, mock_db):
        """Service-layer cap guard (independent of Pydantic schema cap)."""
        uid = uuid.uuid4()
        # Bypass Pydantic by constructing a fake payload object
        fake_payload = MagicMock()
        fake_payload.events = [_make_event() for _ in range(MAX_BATCH_SIZE + 1)]

        with pytest.raises(BadRequestException):
            service.ingest_batch(user_id=uid, payload=fake_payload)

        mock_db.commit.assert_not_called()

    def test_search_event_rows_include_query(self, service, mock_repo, mock_db):
        uid = uuid.uuid4()
        batch = BatchEventRequest(events=[
            {
                "session_id": "s",
                "event_type": "search",
                "search_query": "neural networks",
            }
        ])
        mock_repo.insert_batch.return_value = [uuid.uuid4()]

        service.ingest_batch(user_id=uid, payload=batch)

        rows = mock_repo.insert_batch.call_args[0][0]
        assert rows[0]["search_query"] == "neural networks"

    def test_event_type_preserved_in_rows(self, service, mock_repo, mock_db):
        uid = uuid.uuid4()
        pid = uuid.uuid4()
        batch = _make_batch(
            {"session_id": "s", "event_type": "purchase", "product_id": str(pid)},
        )
        mock_repo.insert_batch.return_value = [uuid.uuid4()]

        service.ingest_batch(user_id=uid, payload=batch)

        rows = mock_repo.insert_batch.call_args[0][0]
        assert rows[0]["event_type"] == EventType.PURCHASE


# ------------------------------------------------------------------ #
# get_my_events                                                      #
# ------------------------------------------------------------------ #

class TestGetMyEvents:

    def _make_user_event(self, user_id: uuid.UUID, event_type: EventType) -> UserEvent:
        """Build a minimal UserEvent without a DB session."""
        e = UserEvent.__new__(UserEvent)
        e.id = uuid.uuid4()
        e.user_id = user_id
        e.session_id = "sess-x"
        e.event_type = event_type
        e.product_id = uuid.uuid4()
        e.search_query = None
        e.event_metadata = {}
        e.created_at = datetime.now(tz=timezone.utc)
        return e

    def test_returns_paginated_response(self, service, mock_repo, mock_db):
        uid = uuid.uuid4()
        events = [self._make_user_event(uid, EventType.VIEW) for _ in range(3)]
        mock_repo.list_by_user.return_value = (events, 3)

        result = service.get_my_events(user_id=uid, page=1, page_size=10)

        assert result.total == 3
        assert result.page == 1
        assert result.page_size == 10
        assert len(result.items) == 3

    def test_skip_calculated_correctly(self, service, mock_repo, mock_db):
        uid = uuid.uuid4()
        mock_repo.list_by_user.return_value = ([], 100)

        service.get_my_events(user_id=uid, page=3, page_size=20)

        _, kwargs = mock_repo.list_by_user.call_args
        assert kwargs["skip"] == 40   # (3-1) * 20
        assert kwargs["limit"] == 20

    def test_event_type_filter_passed_through(self, service, mock_repo, mock_db):
        uid = uuid.uuid4()
        mock_repo.list_by_user.return_value = ([], 0)

        service.get_my_events(uid, event_type=EventType.PURCHASE)

        _, kwargs = mock_repo.list_by_user.call_args
        assert kwargs["event_type"] == EventType.PURCHASE

    def test_no_filter_passes_none(self, service, mock_repo, mock_db):
        uid = uuid.uuid4()
        mock_repo.list_by_user.return_value = ([], 0)

        service.get_my_events(uid)

        _, kwargs = mock_repo.list_by_user.call_args
        assert kwargs["event_type"] is None

    def test_items_serialised_to_event_response(self, service, mock_repo, mock_db):
        uid = uuid.uuid4()
        event = self._make_user_event(uid, EventType.CLICK)
        mock_repo.list_by_user.return_value = ([event], 1)

        result = service.get_my_events(uid)

        assert result.items[0].user_id == uid
        assert result.items[0].event_type == EventType.CLICK
