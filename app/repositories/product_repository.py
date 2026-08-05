"""
app/repositories/product_repository.py
----------------------------------------
Data-access layer for the Product model.

All SQL for products lives here.  Services call these methods and
never touch SQLAlchemy directly — keeping the data-access layer
cleanly separated from business logic.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.product import Product


class ProductRepository:
    """
    Encapsulates all database operations for ``Product`` records.

    Args:
        db: An active SQLAlchemy ``Session`` (injected per request).
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------ #
    # Reads                                                               #
    # ------------------------------------------------------------------ #

    def get_by_id(self, product_id: uuid.UUID) -> Product | None:
        """
        Fetch a product by its UUID primary key.

        Args:
            product_id: UUID of the product.

        Returns:
            The ``Product`` instance, or ``None`` if not found.
        """
        return self._db.get(Product, product_id)

    def list_active(
        self,
        *,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Product], int]:
        """
        Return a page of **active** products and the total active count.

        Args:
            skip:  Number of rows to skip (offset).
            limit: Maximum number of rows to return.

        Returns:
            Tuple of (items, total_count).
        """
        base_filter = Product.is_active.is_(True)

        total: int = self._db.execute(
            select(func.count(Product.id)).where(base_filter)
        ).scalar_one()

        items: list[Product] = list(
            self._db.execute(
                select(Product)
                .where(base_filter)
                .order_by(Product.created_at.desc())
                .offset(skip)
                .limit(limit)
            ).scalars().all()
        )

        return items, total

    def list_all(
        self,
        *,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Product], int]:
        """
        Return a page of **all** products (including inactive) — admin use.

        Args:
            skip:  Number of rows to skip.
            limit: Maximum number of rows to return.

        Returns:
            Tuple of (items, total_count).
        """
        total: int = self._db.execute(
            select(func.count(Product.id))
        ).scalar_one()

        items: list[Product] = list(
            self._db.execute(
                select(Product)
                .order_by(Product.created_at.desc())
                .offset(skip)
                .limit(limit)
            ).scalars().all()
        )

        return items, total

    # ------------------------------------------------------------------ #
    # Writes                                                              #
    # ------------------------------------------------------------------ #

    def create(self, data: dict[str, Any]) -> Product:
        """
        Persist a new product and return it.

        Does **not** commit — the service controls the transaction
        boundary so it can roll back if the subsequent Qdrant write fails.

        Args:
            data: Column values as a plain dict.

        Returns:
            Newly created ``Product`` instance with all fields populated.
        """
        product = Product(**data)
        self._db.add(product)
        self._db.flush()       # generates id / timestamps without committing
        self._db.refresh(product)
        return product

    def update(self, product: Product, data: dict[str, Any]) -> Product:
        """
        Apply *data* to an existing product and return it.

        Does **not** commit.

        Args:
            product: The ORM instance to update (must be session-attached).
            data:    Column values to set.

        Returns:
            Updated ``Product`` instance.
        """
        for key, value in data.items():
            setattr(product, key, value)
        self._db.flush()
        self._db.refresh(product)
        return product

    def delete(self, product: Product) -> None:
        """
        Hard-delete a product row.

        Does **not** commit — caller decides the transaction boundary.

        Args:
            product: The ORM instance to delete.
        """
        self._db.delete(product)
        self._db.flush()
