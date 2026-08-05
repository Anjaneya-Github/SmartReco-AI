"""
app/database/base.py
--------------------
Declarative base and reusable model mixins.

All ORM models inherit from ``Base``.  Domain models should inherit
from ``BaseModel`` which adds a UUID primary key and audit timestamps.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# ------------------------------------------------------------------ #
# Declarative base                                                    #
# ------------------------------------------------------------------ #

class Base(DeclarativeBase):
    """
    Root SQLAlchemy 2.0 declarative base.

    Import this in ``alembic/env.py`` so Alembic can detect all models
    for autogenerate::

        from app.database.base import Base
        target_metadata = Base.metadata
    """
    pass


# ------------------------------------------------------------------ #
# Mixins                                                              #
# ------------------------------------------------------------------ #

class UUIDMixin:
    """
    UUID v4 primary key.

    ``insert_sentinel=True`` tells SQLAlchemy 2.0 to treat this column
    as the implicit row sentinel on bulk INSERT, which is required when
    using server-side UUIDs.  ``default=uuid.uuid4`` fires on the Python
    side at INSERT time so the object has its PK immediately after
    ``session.flush()`` — and also when constructed directly in tests
    without a live DB connection.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )


class TimestampMixin:
    """
    Automatic ``created_at`` / ``updated_at`` audit columns.

    Both ``default`` (Python-side, fires at INSERT) and
    ``server_default`` (DB-side, used by raw SQL / Alembic) are set so
    the object is always fully populated regardless of whether it was
    created through the ORM or loaded from the DB.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


# ------------------------------------------------------------------ #
# Concrete abstract base model                                        #
# ------------------------------------------------------------------ #

class BaseModel(UUIDMixin, TimestampMixin, Base):
    """
    Abstract base for all domain models.

    Provides:
    - ``id``         — UUID v4 primary key (Python default fires at __init__)
    - ``created_at`` — timezone-aware creation timestamp
    - ``updated_at`` — timezone-aware last-update timestamp
    - ``__repr__``   — useful default representation

    The ``__init__`` override ensures ``id``, ``created_at``, and
    ``updated_at`` are populated immediately on object construction —
    before any ``session.flush()`` — so the object is valid for
    serialisation right away.
    """

    __abstract__ = True

    def __init__(self, **kwargs: object) -> None:
        # Assign Python-side defaults before delegating to SQLAlchemy's
        # generated __init__ so all columns have values immediately.
        if "id" not in kwargs:
            kwargs["id"] = uuid.uuid4()
        now = datetime.now(tz=timezone.utc)
        if "created_at" not in kwargs:
            kwargs["created_at"] = now
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = now
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id}>"
