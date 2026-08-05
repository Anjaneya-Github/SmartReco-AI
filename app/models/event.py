"""
app/models/event.py
--------------------
UserEvent ORM model — records every user-interaction signal.

Design choices
~~~~~~~~~~~~~~
- ``event_type`` uses a native PostgreSQL ENUM (``eventtypeenum``) so
  invalid values are rejected at the DB level, not just the application.
- ``product_id`` is a soft foreign key (no FK constraint) — products
  can be deleted without cascading event deletions, and events can
  reference product IDs from external catalogs too.
- ``metadata`` is a ``JSONB`` column (not plain JSON) so PostgreSQL
  can index and query individual keys efficiently.
- ``session_id`` is a plain VARCHAR; the client generates it (e.g.,
  browser session / anonymous device fingerprint).
- ``created_at`` only — events are immutable append-only records,
  so there is no ``updated_at``.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import ENUM as pgEnum, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class EventType(str, enum.Enum):
    """
    Supported user-interaction event types.

    ``str`` mixin makes values JSON-serialisable without conversion.

    VIEW        — user viewed a product detail page
    CLICK       — user clicked a product in a listing
    SEARCH      — user submitted a search query
    PURCHASE    — user completed a purchase
    WISHLIST    — user added a product to their wishlist
    RATING      — user rated a product (score in metadata)
    SHARE       — user shared a product
    IMPRESSION  — product appeared in a listing (scroll / page view)
    """

    VIEW = "view"
    CLICK = "click"
    SEARCH = "search"
    PURCHASE = "purchase"
    WISHLIST = "wishlist"
    RATING = "rating"
    SHARE = "share"
    IMPRESSION = "impression"


# Native PostgreSQL ENUM — DB enforces validity
_event_type_enum = pgEnum(
    EventType,
    name="eventtypeenum",
    create_type=True,
    values_callable=lambda obj: [e.value for e in obj],
)


class UserEvent(Base):
    """
    Immutable append-only record of a single user interaction.

    Events are never updated or soft-deleted — the history is
    sacrosanct for analytics and recommendation training.

    Columns
    ~~~~~~~
    id              UUID v4 PK
    user_id         UUID — references users.id (soft FK)
    session_id      client-generated session identifier
    event_type      EventType ENUM
    product_id      optional — product this event relates to
    search_query    optional — raw query string for SEARCH events
    metadata        JSONB — additional context (rating value, position, etc.)
    created_at      UTC timestamp of the event (immutable)
    """

    __tablename__ = "user_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="User who triggered the event (soft FK → users.id)",
    )
    session_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        comment="Client-generated session / device identifier",
    )
    event_type: Mapped[EventType] = mapped_column(
        _event_type_enum,
        nullable=False,
        index=True,
        comment="Type of interaction",
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="Product related to the event (optional, soft FK)",
    )
    search_query: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Search query string — populated for SEARCH events",
    )
    metadata: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="JSONB bag for arbitrary event context (rating, position, etc.)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
        index=True,
        comment="Event timestamp (immutable)",
    )

    def __init__(self, **kwargs: object) -> None:
        # Ensure id and created_at are populated at construction time
        # (same pattern as BaseModel) so the object is valid before flush.
        if "id" not in kwargs:
            kwargs["id"] = uuid.uuid4()
        if "created_at" not in kwargs:
            kwargs["created_at"] = datetime.now(tz=timezone.utc)
        if "metadata" not in kwargs:
            kwargs["metadata"] = {}
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return (
            f"<UserEvent id={self.id} "
            f"type={self.event_type.value} "
            f"user={self.user_id}>"
        )
