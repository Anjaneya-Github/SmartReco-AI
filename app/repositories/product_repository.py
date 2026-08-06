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
        return self._db.get(Product, product_id)

    def list_active(
        self,
        *,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[Product], int]:
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

    def get_by_ids(self, product_ids: list[uuid.UUID]) -> list[Product]:
        """
        Fetch multiple products by their UUIDs in a single query.

        Used by the behavior analyzer to resolve product metadata
        (category, tags) for a user's viewed/clicked products.

        Args:
            product_ids: List of product UUIDs to fetch.

        Returns:
            List of ``Product`` instances that exist and are active.
            Order is not guaranteed.
        """
        if not product_ids:
            return []
        return list(
            self._db.execute(
                select(Product).where(
                    Product.id.in_(product_ids),
                    Product.is_active.is_(True),
                )
            )
            .scalars()
            .all()
        )

    # ------------------------------------------------------------------ #
    # Writes                                                              #
    # ------------------------------------------------------------------ #

    def create(self, data: dict[str, Any]) -> Product:
        product = Product(**data)
        self._db.add(product)
        self._db.flush()
        self._db.refresh(product)
        return product

    def update(self, product: Product, data: dict[str, Any]) -> Product:
        for key, value in data.items():
            setattr(product, key, value)
        self._db.flush()
        self._db.refresh(product)
        return product

    def delete(self, product: Product) -> None:
        self._db.delete(product)
        self._db.flush()
