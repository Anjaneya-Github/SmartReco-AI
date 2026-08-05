"""
app/schemas/product.py
-----------------------
Pydantic v2 schemas for the Product domain.

CreateProductRequest   — inbound: admin creates a product
UpdateProductRequest   — inbound: admin replaces a product (full update)
ProductResponse        — outbound: public product representation
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.schemas.common import AppBaseSchema

# Allowed values enforced at the API boundary so the DB column stays
# a plain VARCHAR and vocabulary can grow without migrations.
_ALLOWED_DIFFICULTIES: frozenset[str] = frozenset(
    {"beginner", "intermediate", "advanced"}
)


# ------------------------------------------------------------------ #
# Request schemas                                                     #
# ------------------------------------------------------------------ #

class CreateProductRequest(AppBaseSchema):
    """Body for ``POST /api/v1/admin/products``."""

    title: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Short product name.",
    )
    description: str | None = Field(
        default=None,
        description="Long-form description (markdown supported).",
    )
    category: str | None = Field(
        default=None,
        max_length=100,
        description="Top-level category slug, e.g. 'machine-learning'.",
    )
    difficulty: str | None = Field(
        default=None,
        description="Difficulty level: beginner | intermediate | advanced.",
    )
    duration: int | None = Field(
        default=None,
        ge=1,
        description="Duration in minutes.",
    )
    price: float | None = Field(
        default=None,
        ge=0,
        description="Price in USD. Omit or set null for free products.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Searchable tag labels.",
    )
    is_active: bool = Field(
        default=True,
        description="Set False to hide from public listing.",
    )

    @field_validator("difficulty")
    @classmethod
    def _validate_difficulty(cls, v: str | None) -> str | None:
        if v is not None and v not in _ALLOWED_DIFFICULTIES:
            raise ValueError(
                f"difficulty must be one of {sorted(_ALLOWED_DIFFICULTIES)}"
            )
        return v

    @field_validator("tags", mode="before")
    @classmethod
    def _clean_tags(cls, v: list[str]) -> list[str]:
        """Strip whitespace and deduplicate tags, preserving order."""
        seen: set[str] = set()
        result: list[str] = []
        for tag in v:
            cleaned = str(tag).strip().lower()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return result


class UpdateProductRequest(AppBaseSchema):
    """
    Body for ``PUT /api/v1/admin/products/{id}``.

    Full replacement — all fields are required (caller must send the
    complete resource).  Use PATCH for partial updates in future.
    """

    title: str = Field(..., min_length=3, max_length=500)
    description: str | None = None
    category: str | None = Field(default=None, max_length=100)
    difficulty: str | None = None
    duration: int | None = Field(default=None, ge=1)
    price: float | None = Field(default=None, ge=0)
    tags: list[str] = Field(default_factory=list)
    is_active: bool = True

    @field_validator("difficulty")
    @classmethod
    def _validate_difficulty(cls, v: str | None) -> str | None:
        if v is not None and v not in _ALLOWED_DIFFICULTIES:
            raise ValueError(
                f"difficulty must be one of {sorted(_ALLOWED_DIFFICULTIES)}"
            )
        return v

    @field_validator("tags", mode="before")
    @classmethod
    def _clean_tags(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for tag in v:
            cleaned = str(tag).strip().lower()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return result


# ------------------------------------------------------------------ #
# Response schema                                                     #
# ------------------------------------------------------------------ #

class ProductResponse(AppBaseSchema):
    """
    Public product representation.

    ``from_attributes=True`` (inherited from ``AppBaseSchema``) allows
    direct construction from a SQLAlchemy ``Product`` ORM instance.
    """

    id: uuid.UUID
    title: str
    description: str | None
    category: str | None
    difficulty: str | None
    duration: int | None
    price: float | None
    tags: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
