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

        The method assigns a UUID and ``created_at`` timestamp to every
        row server-side (Python), so the objects are usable immediately
        without a DB round-trip.

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
                    "id": eid,
                    "created_at": now,
                    "metadata": {},
                    **row,                    # caller values override defaults
                    "id": eid,               # id is always our generated UUID
                    "created_at": now,       # timestamp is always server-set
                }
            )

        # bulk_insert_mappings issues one multi-row INSERT statement —
        # dramatically faster than N individual session.add() calls.
        self._db.bulk_insert_mappings(UserEvent, enriched)  # type: ignore[arg-type]
        return ids

    # ------------------------------------------------------------------ #
    # Reads                                                               #
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
