"""
app/schemas/common.py
----------------------
Shared Pydantic schemas reused across the API.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


# ------------------------------------------------------------------ #
# Base schema                                                         #
# ------------------------------------------------------------------ #

class AppBaseSchema(BaseModel):
    """
    Root schema for all Pydantic models in this project.

    - ``from_attributes=True``  enables ORM → schema conversion.
    - ``populate_by_name=True`` lets you use both the field name and alias.
    """

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ------------------------------------------------------------------ #
# Generic response envelopes                                          #
# ------------------------------------------------------------------ #

class MessageResponse(AppBaseSchema):
    """Simple success message."""

    message: str


class ErrorResponse(AppBaseSchema):
    """Standard error body returned by exception handlers."""

    detail: str
    request_id: str | None = None


class PaginatedResponse(AppBaseSchema, Generic[T]):
    """Paginated list wrapper."""

    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def of(
        cls,
        items: list[T],
        total: int,
        page: int,
        page_size: int,
    ) -> "PaginatedResponse[T]":
        import math
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if page_size else 0,
        )
