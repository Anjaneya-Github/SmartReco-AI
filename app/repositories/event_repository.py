"""
app/repositories/event_repository.py
--------------------------------------
Data-access layer for ``UserEvent`` records.

High-throughput design
~~~~~~~~~~~~~~~~~~~~~~
``insert_batch`` uses ``session.bulk_insert_mappings`` rather than
individual ``session.add`` calls.  This generates a single
``INSERT … VALUES (…),(…),(…)`` statement (via SQLAlchemy Core's bulk
path), avoiding N round-trips for a batch of events.

The repository never commits — the service controls the transaction
boundary so it can roll back atomically on any error.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.event import EventType, UserEvent


class EventRepository:
    """
    All database I/O for ``UserEvent`` records.

    Args:
        db: SQLAlchemy ``Session`` injected per request via ``get_db``.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------ #
    # Writes                                                              #
    # ------------------------------------------------------------------ #

    def insert_batch(
        self,
        rows: list[dict[str, Any]],
    ) -> list[uuid.UUID]:
        """
        Insert a batch of event rows in a single database round-trip.

        Each dict in *rows* must contain at minimum:
          - user_id       (uuid.UUID)
          - session_id    (str)
          - event_type    (EventType | str)
          - metadata      (dict)

        Optional keys: product_id, search_query.

        Args:
            rows: List of column-value dicts (one per event).

        Returns:
            List of UUIDs in the same order as *rows*.
        """
        now = datetime.now(tz=timezone.utc)
        ids: list[uuid.UUID] = []
        enriched: list[dict[str, Any]] = []

        for row in rows:
            eid = uuid.uuid4()
            ids.append(eid)
            enriched.append(
                {
                    "metadata": {},
                    **row,
                    "id": eid,          # always our generated UUID
                    "created_at": now,  # always server-set
                }
            )

        self._db.bulk_insert_mappings(UserEvent, enriched)  # type: ignore[arg-type]
        return ids

    # ------------------------------------------------------------------ #
    # Reads — pagination                                                  #
    # ------------------------------------------------------------------ #

    def list_by_user(
        self,
        user_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        event_type: EventType | None = None,
    ) -> tuple[list[UserEvent], int]:
        """
        Return a page of events for a given user, newest first.

        Args:
            user_id:    Filter to this user's events.
            skip:       Pagination offset.
            limit:      Page size.
            event_type: Optional filter by event type.

        Returns:
            Tuple of (events, total_count_for_user).
        """
        filters = [UserEvent.user_id == user_id]
        if event_type is not None:
            filters.append(UserEvent.event_type == event_type)

        total: int = self._db.execute(
            select(func.count(UserEvent.id)).where(*filters)
        ).scalar_one()

        events: list[UserEvent] = list(
            self._db.execute(
                select(UserEvent)
                .where(*filters)
                .order_by(UserEvent.created_at.desc())
                .offset(skip)
                .limit(limit)
            )
            .scalars()
            .all()
        )

        return events, total

    # ------------------------------------------------------------------ #
    # Reads — behavior analysis                                          #
    # ------------------------------------------------------------------ #

    def get_recent_events(
        self,
        user_id: uuid.UUID,
        limit: int = 200,
    ) -> list[UserEvent]:
        """
        Return the most recent *limit* events for *user_id*, newest first.

        Used by the behavior analyzer to build an in-memory profile
        without loading the entire event history.

        Args:
            user_id: Target user's UUID.
            limit:   Maximum number of events to fetch (default 200).

        Returns:
            List of ``UserEvent`` instances ordered by ``created_at DESC``.
        """
        return list(
            self._db.execute(
                select(UserEvent)
                .where(UserEvent.user_id == user_id)
                .order_by(UserEvent.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )

    def count_since(
        self,
        user_id: uuid.UUID,
        since: datetime,
        event_type: EventType | None = None,
    ) -> int:
        """
        Count events for *user_id* after *since*.

        Used by ``RecommendationTriggerService`` to check thresholds.

        Args:
            user_id:    Target user.
            since:      Inclusive lower bound for ``created_at``.
            event_type: Optional type filter.

        Returns:
            Integer count.
        """
        filters = [
            UserEvent.user_id == user_id,
            UserEvent.created_at >= since,
        ]
        if event_type is not None:
            filters.append(UserEvent.event_type == event_type)

        return self._db.execute(
            select(func.count(UserEvent.id)).where(*filters)
        ).scalar_one()

    def get_last_event_time(self, user_id: uuid.UUID) -> datetime | None:
        """
        Return the timestamp of the user's most recent event, or ``None``
        if the user has no events at all.

        Args:
            user_id: Target user.

        Returns:
            Timezone-aware UTC datetime or ``None``.
        """
        result = self._db.execute(
            select(func.max(UserEvent.created_at)).where(
                UserEvent.user_id == user_id
            )
        ).scalar_one_or_none()
        return result
