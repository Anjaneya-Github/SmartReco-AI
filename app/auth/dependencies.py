"""
app/auth/dependencies.py
--------------------------
FastAPI injectable dependencies for authentication and authorisation.

Usage in routes
~~~~~~~~~~~~~~~
``get_current_user`` — any authenticated request::

    @router.get("/me")
    def me(current_user: User = Depends(get_current_user)):
        ...

``get_current_admin`` — admin-only routes::

    @router.delete("/users/{id}")
    def delete_user(
        user_id: uuid.UUID,
        _: User = Depends(get_current_admin),
    ):
        ...

How it works
~~~~~~~~~~~~
1. ``OAuth2PasswordBearer`` extracts the raw JWT from the
   ``Authorization: Bearer <token>`` header and raises 401 if absent.
2. ``decode_access_token`` verifies the signature and expiry.
3. ``UserRepository.get_by_id`` loads the live user record so that
   account deactivations take effect immediately (not just at token expiry).
"""

from __future__ import annotations

import uuid

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth.jwt import decode_access_token
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.database.session import get_db
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository

# Points to the login endpoint so Swagger UI's "Authorize" button works.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Resolve the JWT to a live ``User`` record.

    Steps:
    1. Decode + verify the JWT (raises 401 on failure).
    2. Extract ``sub`` (user UUID).
    3. Load the user from DB (raises 401 if not found).
    4. Reject inactive accounts (raises 401).

    Args:
        token: Raw JWT string extracted by ``OAuth2PasswordBearer``.
        db:    Database session (injected per request).

    Returns:
        The authenticated, active ``User`` instance.

    Raises:
        UnauthorizedException: Token invalid / user missing / account disabled.
    """
    payload = decode_access_token(token)

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise UnauthorizedException("Token payload is malformed.") from exc

    repo = UserRepository(db)
    user = repo.get_by_id(user_id)

    if user is None:
        raise UnauthorizedException("User not found.")

    if not user.is_active:
        raise UnauthorizedException("This account has been disabled.")

    return user


def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Extend ``get_current_user`` with an admin-role gate.

    Args:
        current_user: Resolved by ``get_current_user``.

    Returns:
        The authenticated user, confirmed to have the ``ADMIN`` role.

    Raises:
        ForbiddenException: If the user's role is not ``ADMIN``.
    """
    if current_user.role is not UserRole.ADMIN:
        raise ForbiddenException("Administrator access required.")
    return current_user
