"""
app/auth/jwt.py
----------------
JWT creation and verification using python-jose.

Token anatomy
~~~~~~~~~~~~~
Every token contains::

    {
      "sub":  "<user UUID as string>",   # subject — who this token belongs to
      "role": "<user | admin>",           # embedded role — avoids a DB hit on auth
      "iat":  <issued-at epoch>,
      "exp":  <expiry epoch>
    }

Embedding the role in the token keeps most authenticated requests
down to zero extra DB queries.  The trade-off is that role changes
do not take effect until the current token expires — acceptable for
this use-case; implement token revocation / short TTL if needed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from app.core.config import settings
from app.core.exceptions import UnauthorizedException
from app.core.logging import get_logger

logger = get_logger(__name__)


def _utc_now() -> datetime:
    """Return the current moment in UTC (timezone-aware)."""
    return datetime.now(tz=timezone.utc)


def create_access_token(
    subject: str | uuid.UUID,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create and sign a JWT access token.

    Args:
        subject:        The user's UUID (will be stored as ``sub`` claim).
        role:           The user's role string (e.g. ``"user"`` or ``"admin"``).
        expires_delta:  Optional custom TTL; falls back to ``settings.ACCESS_TOKEN_EXPIRE_MINUTES``.

    Returns:
        Encoded JWT string.
    """
    now = _utc_now()
    ttl = expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "iat": now,
        "exp": now + ttl,
    }

    token: str = jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    return token


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT access token.

    Args:
        token: Raw JWT string from the ``Authorization: Bearer`` header.

    Returns:
        The decoded payload dict (contains ``sub``, ``role``, etc.).

    Raises:
        UnauthorizedException: If the token is missing, expired, or tampered with.
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
    except JWTError as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise UnauthorizedException("Token is invalid or has expired.") from exc

    # Guard against tokens that somehow lack the subject claim.
    if payload.get("sub") is None:
        raise UnauthorizedException("Token payload is missing 'sub' claim.")

    return payload
