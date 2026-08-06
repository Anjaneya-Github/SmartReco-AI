"""
app/core/exceptions.py
-----------------------
Domain exception hierarchy for SmartReco AI.

Why a custom exception hierarchy?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
FastAPI's default behaviour is to catch unhandled Python exceptions and
return a generic 500 Internal Server Error. That's fine for unexpected
errors, but for predictable domain errors (user not found, already exists,
bad input) we want:

  1. Specific HTTP status codes (404, 409, 400, etc.)
  2. Clear error messages for the client
  3. No HTTP knowledge inside services or repositories

The solution: services raise domain exceptions (e.g. ``NotFoundException``),
and the global exception handler in ``app/main.py`` converts them to the
appropriate HTTP response. Services never import ``fastapi`` or ``starlette``.

Exception Map
~~~~~~~~~~~~~
    AppException              → 500 Internal Server Error (catch-all)
    NotFoundException         → 404 Not Found
    AlreadyExistsException    → 409 Conflict
    UnauthorizedException     → 401 Unauthorized
    ForbiddenException        → 403 Forbidden
    BadRequestException       → 400 Bad Request
    UnprocessableEntityException → 422 Unprocessable Entity

Usage
~~~~~
    # In a service:
    from app.core.exceptions import NotFoundException

    user = repo.get_by_id(user_id)
    if user is None:
        raise NotFoundException(f"User {user_id} not found.")
    # → HTTP 404 with body: {"detail": "User ... not found."}
"""

from __future__ import annotations

from http import HTTPStatus


class AppException(Exception):
    """
    Root exception for all application-level errors.

    Every custom exception inherits from this base class.
    The global exception handler in main.py catches ``AppException``
    and converts it to a JSON HTTP response automatically.

    Class attributes:
        status_code: The HTTP status code to return (default 500).
        detail:      The error message to include in the response body.
    """

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR.value
    detail: str = "An unexpected error occurred."

    def __init__(self, detail: str | None = None) -> None:
        # Allow passing a custom message; fall back to class-level default
        self.detail = detail or self.__class__.detail
        super().__init__(self.detail)


# ------------------------------------------------------------------ #
# Concrete exceptions — one per HTTP error category                   #
# ------------------------------------------------------------------ #

class NotFoundException(AppException):
    """
    Raised when a requested resource does not exist in the database.

    Examples: user not found, product not found, recommendation not found.
    → HTTP 404 Not Found
    """
    status_code = HTTPStatus.NOT_FOUND.value
    detail = "Resource not found."


class AlreadyExistsException(AppException):
    """
    Raised when trying to create a resource that already exists.

    Example: registering with an email that is already in use.
    → HTTP 409 Conflict
    """
    status_code = HTTPStatus.CONFLICT.value
    detail = "Resource already exists."


class UnauthorizedException(AppException):
    """
    Raised when a request requires authentication but none was provided,
    or the provided token is invalid / expired.

    → HTTP 401 Unauthorized
    """
    status_code = HTTPStatus.UNAUTHORIZED.value
    detail = "Authentication required."


class ForbiddenException(AppException):
    """
    Raised when an authenticated user tries to access a resource they
    don't have permission for (e.g. a regular user accessing admin routes).

    → HTTP 403 Forbidden
    """
    status_code = HTTPStatus.FORBIDDEN.value
    detail = "You do not have permission to perform this action."


class BadRequestException(AppException):
    """
    Raised when the request is structurally valid but logically wrong.

    Examples: batch size exceeds maximum, invalid job ID for scheduler.
    → HTTP 400 Bad Request
    """
    status_code = HTTPStatus.BAD_REQUEST.value
    detail = "Bad request."


class UnprocessableEntityException(AppException):
    """
    Raised when the request data fails business-rule validation
    (distinct from schema validation which Pydantic handles as 422).

    → HTTP 422 Unprocessable Entity
    """
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY.value
    detail = "Validation error."
