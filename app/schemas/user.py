"""
app/schemas/user.py
--------------------
Pydantic v2 schemas for the User domain.

Separation of concerns
~~~~~~~~~~~~~~~~~~~~~~~
RegisterRequest   — inbound: what the client sends to create an account
LoginRequest      — inbound: credentials for the login endpoint
TokenResponse     — outbound: JWT pair returned after successful auth
UserResponse      — outbound: safe public representation of a User record
                              (never includes hashed_password)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import EmailStr, Field, field_validator

from app.models.user import UserRole
from app.schemas.common import AppBaseSchema


# ------------------------------------------------------------------ #
# Inbound (request) schemas                                          #
# ------------------------------------------------------------------ #

class RegisterRequest(AppBaseSchema):
    """
    Body for ``POST /api/v1/auth/register``.

    Password rules enforced here so validation errors surface at the
    API boundary before any database or hashing work is done.
    """

    email: EmailStr = Field(
        ...,
        description="Valid email address — used as the login identifier.",
    )
    full_name: str | None = Field(
        default=None,
        max_length=255,
        description="Optional display name.",
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Plain-text password (min 8 chars). Never stored.",
    )

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        """Require at least one uppercase letter and one digit."""
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        return v


class LoginRequest(AppBaseSchema):
    """
    Body for ``POST /api/v1/auth/login``.

    Uses ``email`` (not username) as the identifier to match the
    ``RegisterRequest`` model and keep the auth flow consistent.
    """

    email: EmailStr = Field(..., description="Registered email address.")
    password: str = Field(..., description="Account password.")


# ------------------------------------------------------------------ #
# Outbound (response) schemas                                        #
# ------------------------------------------------------------------ #

class TokenResponse(AppBaseSchema):
    """
    Returned by ``/login`` and ``/refresh``.

    ``access_token``  — short-lived JWT (default 60 min); send in
                        ``Authorization: Bearer <token>`` header.
    ``token_type``    — always "bearer" per OAuth2 spec.
    """

    access_token: str
    token_type: str = "bearer"


class UserResponse(AppBaseSchema):
    """
    Safe public view of a User record.

    ``hashed_password`` is intentionally excluded.  Uses
    ``from_attributes=True`` (inherited from AppBaseSchema) so it can
    be constructed directly from an ORM ``User`` instance.
    """

    id: uuid.UUID
    email: str
    full_name: str | None
    role: UserRole
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime
