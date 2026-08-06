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
POST /api/v1/events/batch  — ingest 1-500 events; auto-triggers reco generation
GET  /api/v1/events/me     — paginated list of the current user's events

Auto-trigger design
~~~~~~~~~~~~~~~~~~~
After every successful batch ingest, we evaluate the four trigger rules
(``RecommendationService.should_generate``) against the authenticated
user's event history.  If any rule fires, the LangGraph recommendation
workflow is invoked synchronously within the same request.

This is intentionally simple for v1.  In production you would push the
``user_id`` onto a background task queue (Celery/RQ/ARQ) instead of
calling the service inline, so the HTTP response doesn't block on LLM
latency.  The architecture is identical — only the invocation mechanism
changes.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.core.logging import get_logger
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
from app.services.recommendation_service import RecommendationService

router = APIRouter(prefix="/events", tags=["Events"])
logger = get_logger(__name__)

_MAX_PAGE_SIZE = 100


# ------------------------------------------------------------------ #
# Dependencies                                                        #
# ------------------------------------------------------------------ #

def _get_event_service(db: Session = Depends(get_db)) -> EventService:
    return EventService(db)


def _get_recommendation_service(db: Session = Depends(get_db)) -> RecommendationService:
    return RecommendationService(db)


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
    event_svc: EventService = Depends(_get_event_service),
    reco_svc: RecommendationService = Depends(_get_recommendation_service),
) -> BatchEventResponse:
    """
    Store 1–500 events in a single atomic transaction, then check whether
    a new recommendation should be generated.

    Auto-trigger behaviour
    ~~~~~~~~~~~~~~~~~~~~~~
    After persisting the events, ``RecommendationService.should_generate``
    evaluates four rules:

    1. **new_events_threshold** — ≥ 20 new events since last recommendation.
    2. **repeated_search** — same query submitted more than once.
    3. **purchase_or_wishlist** — any high-intent event in the window.
    4. **inactivity_reengagement** — silent for ≥ 10 minutes.

    If any rule fires, the full LangGraph workflow runs and the result is
    persisted before the response is returned.  If the trigger doesn't
    fire, or if generation fails, the batch response is returned unchanged
    (trigger errors are logged but never surface to the caller).

    ``user_id`` is always taken from the JWT ``sub`` claim.
    """
    # 1. Persist events
    result = event_svc.ingest_batch(user_id=current_user.id, payload=payload)

    # 2. Evaluate trigger rules
    try:
        trigger_status = reco_svc.should_generate(current_user.id)
        logger.info(
            "trigger_evaluated user_id=%s should_trigger=%s reason=%s rules=%s",
            current_user.id,
            trigger_status.should_trigger,
            trigger_status.reason,
            trigger_status.rules_evaluated,
        )

        if trigger_status.should_trigger:
            logger.info(
                "trigger_fired user_id=%s reason=%s — starting recommendation workflow",
                current_user.id,
                trigger_status.reason,
            )
            reco_svc.generate(user_id=current_user.id)

    except Exception as exc:
        # Never let trigger/generation failures break the event ingest response
        logger.error(
            "trigger_error user_id=%s error=%s", current_user.id, exc
        )

    return result


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
