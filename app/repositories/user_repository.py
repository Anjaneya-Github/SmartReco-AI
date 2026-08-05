"""
app/repositories/user_repository.py
-------------------------------------
Data-access layer for the User model.

All database I/O for users lives here.  Services call these methods;
they never touch the ORM directly.  This keeps the data-access
concerns isolated and easy to swap or mock during testing.

Pattern used: plain class with an injected ``Session``.
No base-class inheritance is required for the foundation — add a
``BaseRepository[T]`` generic base when you need shared CRUD.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    """
    Encapsulates all database operations for ``User`` records.

    Args:
        db: An active SQLAlchemy ``Session`` (injected per request via ``get_db``).
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------ #
    # Reads                                                               #
    # ------------------------------------------------------------------ #

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """
        Fetch a user by their UUID primary key.

        Args:
            user_id: UUID of the user to look up.

        Returns:
            The ``User`` instance, or ``None`` if not found.
        """
        return self._db.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        """
        Fetch a user by their email address (case-sensitive).

        Args:
            email: The email to search for.

        Returns:
            The ``User`` instance, or ``None`` if not found.
        """
        stmt = select(User).where(User.email == email)
        return self._db.execute(stmt).scalar_one_or_none()

    def email_exists(self, email: str) -> bool:
        """
        Return ``True`` if any user is registered with *email*.

        Cheaper than ``get_by_email`` when you only need existence.
        """
        stmt = select(User.id).where(User.email == email)
        return self._db.execute(stmt).first() is not None

    # ------------------------------------------------------------------ #
    # Writes                                                              #
    # ------------------------------------------------------------------ #

    def create(
        self,
        email: str,
        hashed_password: str,
        full_name: str | None = None,
        role: str = "user",
        is_active: bool = True,
        is_verified: bool = False,
    ) -> User:
        """
        Persist a new user record and return it.

        The session is **not** committed here — the caller (service or
        seed script) decides when to commit, which keeps the unit of
        work boundary explicit.

        Args:
            email:           Unique email address.
            hashed_password: Pre-hashed bcrypt string.
            full_name:       Optional display name.
            role:            ``"user"`` or ``"admin"`` (default ``"user"``).
            is_active:       Whether the account starts enabled.
            is_verified:     Whether the email is pre-verified.

        Returns:
            The newly created, session-attached ``User`` instance.
        """
        from app.models.user import UserRole

        user = User(
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
            role=UserRole(role),
            is_active=is_active,
            is_verified=is_verified,
        )
        self._db.add(user)
        self._db.flush()   # assign DB-generated defaults (id, timestamps) without committing
        self._db.refresh(user)
        return user
