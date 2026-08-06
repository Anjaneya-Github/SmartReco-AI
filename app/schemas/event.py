"""
app/schemas/event.py
---------------------
Pydantic v2 schemas for the UserEvent domain.

Schemas
~~~~~~~
EventRequest       — one event in a batch payload
BatchEventRequest  — body for POST /api/v1/events/batch (1-500 events)
EventResponse      — outbound representation of a persisted event
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from app.models.event import EventType
from app.schemas.common import AppBaseSchema

# Hard limit per batch — protect against runaway payloads
MAX_BATCH_SIZE: int = 500


# ------------------------------------------------------------------ #
# Inbound (request) schemas                                          #
# ------------------------------------------------------------------ #

class EventRequest(AppBaseSchema):
    """
    A single user-interaction event.

    Validation rules
    ~~~~~~~~~~~~~~~~
    - ``event_type`` must be a known ``EventType`` value.
    - ``product_id`` is required for product-specific events
      (VIEW, CLICK, PURCHASE, WISHLIST, RATING, SHARE, IMPRESSION).
    - ``search_query`` is required for SEARCH events.
    - ``metadata`` is a free-form dict; no keys are required.
    """

    session_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Client-generated session / device identifier.",
    )
    event_type: EventType = Field(
        ...,
        description=(
            "Type of interaction. One of: "
            + ", ".join(e.value for e in EventType)
        ),
    )
    product_id: uuid.UUID | None = Field(
        default=None,
        description="Product UUID — required for product-related event types.",
    )
    search_query: str | None = Field(
        default=None,
        max_length=1000,
        description="Raw search query — required for SEARCH events.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary JSON context (e.g. rating value, list position).",
    )

    @model_validator(mode="after")
    def _cross_field_rules(self) -> "EventRequest":
        product_events = {
            EventType.VIEW,
            EventType.CLICK,
            EventType.PURCHASE,
            EventType.WISHLIST,
            EventType.RATING,
            EventType.SHARE,
            EventType.IMPRESSION,
        }
        if self.event_type in product_events and self.product_id is None:
            raise ValueError(
                f"product_id is required for event_type='{self.event_type.value}'."
            )
        if self.event_type == EventType.SEARCH and not self.search_query:
            raise ValueError("search_query is required for event_type='search'.")
        return self


class BatchEventRequest(AppBaseSchema):
    """
    Body for ``POST /api/v1/events/batch``.

    Accepts 1 – MAX_BATCH_SIZE events in a single request.
    All events in a batch share the same authenticated user; the
    ``user_id`` is injected server-side from the JWT — clients must
    not supply it.
    """

    events: list[EventRequest] = Field(
        ...,
        min_length=1,
        max_length=MAX_BATCH_SIZE,
        description=f"List of events (1 – {MAX_BATCH_SIZE}).",
    )


# ------------------------------------------------------------------ #
# Outbound (response) schemas                                        #
# ------------------------------------------------------------------ #

class EventResponse(AppBaseSchema):
    """
    Serialised view of a persisted ``UserEvent`` record.

    ``from_attributes=True`` (from ``AppBaseSchema``) allows direct
    construction from an ORM instance.

    Note: the ORM column was renamed from ``metadata`` to ``event_metadata``
    to avoid clashing with SQLAlchemy's reserved ``metadata`` attribute.
    The JSON response still uses the key ``metadata`` via ``validation_alias``.
    """

    id: uuid.UUID
    user_id: uuid.UUID
    session_id: str
    event_type: EventType
    product_id: uuid.UUID | None
    search_query: str | None
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="event_metadata",
    )
    created_at: datetime


class BatchEventResponse(AppBaseSchema):
    """Response returned after a successful batch insert."""

    accepted: int = Field(description="Number of events successfully stored.")
    event_ids: list[uuid.UUID] = Field(
        description="UUIDs of the newly created events, in insertion order."
    )
