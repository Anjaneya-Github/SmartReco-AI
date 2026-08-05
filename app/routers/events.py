"""
app/routers/events.py
----------------------
User-interaction event routes.

Prefix : /events    (mounted at /api/v1 → /api/v1/events/...)
Tag    : Events

All endpoints require a valid JWT — events are always attributed to
an authenticated user.

Endpoints
~~~~~~~~~
POST /api/v1/events/batch  — ingest 1-500 events in one request
GET  /api/v1/events/me     — paginated list of the current user's events

Design notes
~~~~~~~~~~~~
- The router is intentionally thin: auth and pagination params are
  resolved here; all logic lives in ``EventService``.
- ``user_id`` is ALWAYS taken from the JWT ``sub`` claim — clients
  cannot submit events on behalf of another user.
- ``POST /events/batch`` returns 202 Accepted (not 201) to signal that
  events are accepted for processing (analytics pipelines may queue
  them downstream in future iterations).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database.session import get_db
from app.models.event import EventType
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.event import (
    BatchEventRequest,
    BatchEventResponse,
    EventResponse,
)
from app.services.event_service import EventService

router = APIRouter(prefix="/events", tags=["Events"])

_MAX_PAGE_SIZE = 100


# ------------------------------------------------------------------ #
# Dependency                                                          #
# ------------------------------------------------------------------ #

def _get_event_service(db: Session = Depends(get_db)) -> EventService:
    return EventService(db)


# ------------------------------------------------------------------ #
# Endpoints                                                           #
# ------------------------------------------------------------------ #

@router.post(
    "/batch",
    response_model=BatchEventResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest a batch of user-interaction events",
    responses={
        400: {"description": "Batch size exceeds maximum"},
        401: {"description": "Not authenticated"},
        422: {"description": "Validation error (invalid event_type, missing fields)"},
    },
)
def ingest_batch(
    payload: BatchEventRequest,
    current_user: User = Depends(get_current_user),
    service: EventService = Depends(_get_event_service),
) -> BatchEventResponse:
    """
    Store 1 – 500 events in a single atomic transaction.

    - ``user_id`` is resolved from the Bearer token — do NOT send it in the body.
    - All events in the batch must be valid; if any fail validation the
      entire request is rejected with 422 before any DB writes occur.
    - On success, returns the count and UUIDs of stored events.
    """
    return service.ingest_batch(user_id=current_user.id, payload=payload)


@router.get(
    "/me",
    response_model=PaginatedResponse[EventResponse],
    status_code=status.HTTP_200_OK,
    summary="Get current user's event history",
    responses={
        401: {"description": "Not authenticated"},
    },
)
def get_my_events(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(
        default=50, ge=1, le=_MAX_PAGE_SIZE, description="Items per page"
    ),
    event_type: EventType | None = Query(
        default=None,
        description="Filter by event type (optional)",
    ),
    current_user: User = Depends(get_current_user),
    service: EventService = Depends(_get_event_service),
) -> PaginatedResponse[EventResponse]:
    """
    Return the authenticated user's interaction history, newest first.

    Supports optional filtering by ``event_type``.
    """
    return service.get_my_events(
        user_id=current_user.id,
        page=page,
        page_size=page_size,
        event_type=event_type,
    )
