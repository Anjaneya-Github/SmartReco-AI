"""
app/models/user.py
------------------
User ORM model.

Inherits UUID primary key and audit timestamps from ``BaseModel``.
The ``role`` column uses a native PostgreSQL ENUM via SQLAlchemy's
``pgEnum`` so the constraint lives in the database, not just the app.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import ENUM as pgEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import BaseModel


class UserRole(str, enum.Enum):
    """
    Application roles.

    ``str`` mixin means the values compare equal to plain strings and
    serialise cleanly to JSON without extra conversion.

    USER  — standard authenticated user
    ADMIN — full back-office access
    """

    USER = "user"
    ADMIN = "admin"


# SQLAlchemy type that maps to a native PostgreSQL ENUM column.
# ``create_type=True`` means Alembic will emit CREATE TYPE … AS ENUM.
_role_enum = pgEnum(
    UserRole,
    name="userrole",
    create_type=True,
    values_callable=lambda obj: [e.value for e in obj],
)


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class User(BaseModel):
    """
    Persistent user record.

    Columns
    ~~~~~~~
    id              UUID v4, PK (from BaseModel)
    email           unique, indexed, max 255 chars
    full_name       optional display name
    hashed_password bcrypt hash — never store plain-text
    role            UserRole enum, default USER
    is_active       soft-disable account without deletion
    is_verified     email-verification flag (not yet wired)
    created_at      UTC timestamp (from BaseModel)
    updated_at      UTC timestamp, auto-updated (from BaseModel)

    Python-side defaults (``default=``) are set alongside
    ``server_default`` so that newly created instances have correct
    values immediately — without needing a round-trip DB flush.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="User's unique email address (login identifier)",
    )
    full_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Optional display name",
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="bcrypt hash of the user's password",
    )
    role: Mapped[UserRole] = mapped_column(
        _role_enum,
        nullable=False,
        default=UserRole.USER,
        server_default=UserRole.USER.value,
        comment="Access role: user | admin",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="False = account disabled (soft-ban)",
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True once email has been confirmed",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role.value}>"
