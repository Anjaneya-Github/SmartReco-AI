"""
app/routers/auth.py
--------------------
Authentication HTTP routes.

Prefix  : /auth      (mounted at /api/v1 → /api/v1/auth/...)
Tag     : Authentication

Endpoints
~~~~~~~~~
POST /api/v1/auth/register  — create a new user account
POST /api/v1/auth/login     — exchange email + password for a JWT
GET  /api/v1/auth/me        — return the current user's profile

The router is intentionally thin:
- Input validation is handled by Pydantic schemas.
- Business logic lives in ``AuthService``.
- Auth/authorisation lives in ``app.auth.dependencies``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.schemas.user import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ------------------------------------------------------------------ #
# Dependency helper — keeps route signatures clean                    #
# ------------------------------------------------------------------ #

def _get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    """Construct ``AuthService`` with the current request's DB session."""
    return AuthService(db)


# ------------------------------------------------------------------ #
# Endpoints                                                           #
# ------------------------------------------------------------------ #

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
    responses={
        409: {"description": "Email is already registered"},
        422: {"description": "Validation error (password too weak, invalid email, etc.)"},
    },
)
def register(
    payload: RegisterRequest,
    service: AuthService = Depends(_get_auth_service),
) -> UserResponse:
    """
    Create a new user account with the ``user`` role.

    - Email must be unique.
    - Password must be ≥ 8 characters and contain an uppercase letter and a digit.
    - Returns the created user profile (no password / token in response).
    """
    user: User = service.register(payload)
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Login — obtain a JWT access token",
    responses={
        401: {"description": "Invalid credentials or account disabled"},
    },
)
def login(
    payload: LoginRequest,
    service: AuthService = Depends(_get_auth_service),
) -> TokenResponse:
    """
    Exchange email + password for a signed JWT access token.

    Send the returned ``access_token`` in subsequent requests as::

        Authorization: Bearer <access_token>
    """
    return service.login(payload)


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current user profile",
    responses={
        401: {"description": "Not authenticated or token expired"},
    },
)
def me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """
    Return the profile of the currently authenticated user.

    Requires a valid ``Authorization: Bearer <token>`` header.
    """
    return UserResponse.model_validate(current_user)
