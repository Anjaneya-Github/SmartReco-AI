"""
app/services/event_service.py
------------------------------
Event service — orchestrates batch event ingestion and user-event retrieval.

Responsibilities
~~~~~~~~~~~~~~~~
- Validate and normalise inbound event payloads.
- Call the repository to persist events in one DB transaction.
- Enforce the batch size cap (secondary guard — Pydantic is the first).
- Return typed response objects; raise domain exceptions on failure.

Clean-Architecture note
~~~~~~~~~~~~~~~~~~~~~~~
Router → EventService → EventRepository → DB.
The service layer is the only code that knows both the HTTP contract
(schemas) and the persistence contract (repository).  Neither the
router nor the repository should cross that boundary.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException
from app.core.logging import get_logger
from app.models.event import EventType, UserEvent
from app.repositories.event_repository import EventRepository
from app.schemas.common import PaginatedResponse
from app.schemas.event import (
    BatchEventRequest,
    BatchEventResponse,
    EventResponse,
)

logger = get_logger(__name__)

# Absolute ceiling — the schema already validates, this is a safety net
_MAX_BATCH = 500


class EventService:
    """
    Business logic for user-event tracking.

    Args:
        db: SQLAlchemy session injected per request via ``get_db``.
    """

    def __init__(self, db: Session) -> None:
        self._repo = EventRepository(db)
        self._db = db

    # ------------------------------------------------------------------ #
    # Batch ingest                                                        #
    # ------------------------------------------------------------------ #

    def ingest_batch(
        self,
        user_id: uuid.UUID,
        payload: BatchEventRequest,
    ) -> BatchEventResponse:
        """
        Persist a batch of user-interaction events in a single transaction.

        All events are written atomically — if any DB error occurs the
        entire batch is rolled back (the ``get_db`` dependency handles
        the rollback automatically on exception).

        Args:
            user_id: UUID of the authenticated user (from JWT ``sub`` claim).
            payload: Validated ``BatchEventRequest`` containing 1-500 events.

        Returns:
            ``BatchEventResponse`` with the count and IDs of stored events.

        Raises:
            BadRequestException: If the batch exceeds the hard cap.
        """
        if len(payload.events) > _MAX_BATCH:
            raise BadRequestException(
                f"Batch size {len(payload.events)} exceeds maximum of {_MAX_BATCH}."
            )

        rows = [
            {
                "user_id": user_id,
                "session_id": event.session_id,
                "event_type": event.event_type,
                "product_id": event.product_id,
                "search_query": event.search_query,
                "metadata": event.metadata,
            }
            for event in payload.events
        ]

        event_ids = self._repo.insert_batch(rows)
        self._db.commit()

        logger.info(
            "Batch events ingested. user_id=%s count=%d types=%s",
            user_id,
            len(event_ids),
            list({e.event_type.value for e in payload.events}),
        )

        return BatchEventResponse(
            accepted=len(event_ids),
            event_ids=event_ids,
        )

    # ------------------------------------------------------------------ #
    # Read                                                                #
    # ------------------------------------------------------------------ #

    def get_my_events(
        self,
        user_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        event_type: EventType | None = None,
    ) -> PaginatedResponse[EventResponse]:
        """
        Return a paginated list of the authenticated user's events.

        Args:
            user_id:    Filter to this user's events.
            page:       1-indexed page number.
            page_size:  Items per page.
            event_type: Optional filter by event type.

        Returns:
            ``PaginatedResponse[EventResponse]`` — newest first.
        """
        skip = (page - 1) * page_size
        events, total = self._repo.list_by_user(
            user_id,
            skip=skip,
            limit=page_size,
            event_type=event_type,
        )
        return PaginatedResponse.of(
            items=[EventResponse.model_validate(e) for e in events],
            total=total,
            page=page,
            page_size=page_size,
        )
