"""
app/models/product.py
----------------------
Product ORM model.

Inherits UUID primary key and audit timestamps from ``BaseModel``.

The ``tags`` column stores a variable-length list of strings using
PostgreSQL's native ``ARRAY(TEXT)`` type — no join table required for
simple tag lookups and the array can be indexed with GIN.

``category`` and ``difficulty`` are plain ``VARCHAR`` columns rather than
ENUM types so the catalogue vocabulary can evolve without DDL migrations.
Use application-level validation (Pydantic) to enforce allowed values.
"""

from __future__ import annotations

from sqlalchemy import ARRAY, Boolean, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import BaseModel


class Product(BaseModel):
    """
    Persistent product / course record.

    Columns
    ~~~~~~~
    id           UUID v4, PK (from BaseModel)
    title        short product name, required, indexed for text search
    description  long-form markdown or plain-text description
    category     e.g. "machine-learning", "web-development"
    difficulty   e.g. "beginner", "intermediate", "advanced"
    duration     duration in minutes (integer stored as Numeric for flexibility)
    price        decimal price in USD; NULL = free
    tags         PostgreSQL TEXT[] — zero or more searchable labels
    is_active    False = soft-hidden from public listing
    created_at   UTC timestamp (from BaseModel)
    updated_at   UTC timestamp, auto-updated (from BaseModel)
    """

    __tablename__ = "products"

    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        index=True,
        comment="Short product name",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Long-form description (markdown)",
    )
    category: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Top-level category slug",
    )
    difficulty: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Difficulty level: beginner | intermediate | advanced",
    )
    duration: Mapped[int | None] = mapped_column(
        Numeric(precision=6, scale=0),
        nullable=True,
        comment="Duration in minutes",
    )
    price: Mapped[float | None] = mapped_column(
        Numeric(precision=10, scale=2),
        nullable=True,
        comment="Price in USD; NULL = free",
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)),
        nullable=False,
        default=list,
        server_default="{}",
        comment="Searchable tag labels (PostgreSQL TEXT[])",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="False = hidden from public listing",
    )

    def __repr__(self) -> str:
        return f"<Product id={self.id} title={self.title!r}>"
