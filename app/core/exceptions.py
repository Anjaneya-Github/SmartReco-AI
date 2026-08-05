"""
app/core/exceptions.py
----------------------
Domain exception hierarchy.

Services and repositories raise these.  The global exception handlers
in ``app/main.py`` convert them to the correct HTTP responses — keeping
HTTP concerns out of the domain layer.
"""

from __future__ import annotations

from http import HTTPStatus


class AppException(Exception):
    """Root application exception."""

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR.value
    detail: str = "An unexpected error occurred."

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.__class__.detail
        super().__init__(self.detail)


class NotFoundException(AppException):
    status_code = HTTPStatus.NOT_FOUND.value
    detail = "Resource not found."


class AlreadyExistsException(AppException):
    status_code = HTTPStatus.CONFLICT.value
    detail = "Resource already exists."


class UnauthorizedException(AppException):
    status_code = HTTPStatus.UNAUTHORIZED.value
    detail = "Authentication required."


class ForbiddenException(AppException):
    status_code = HTTPStatus.FORBIDDEN.value
    detail = "You do not have permission to perform this action."


class BadRequestException(AppException):
    status_code = HTTPStatus.BAD_REQUEST.value
    detail = "Bad request."


class UnprocessableEntityException(AppException):
    status_code = HTTPStatus.UNPROCESSABLE_ENTITY.value
    detail = "Validation error."
