"""
app/services/product_service.py
---------------------------------
Product service — orchestrates the dual-write to PostgreSQL + Qdrant.

Dual-write contract
~~~~~~~~~~~~~~~~~~~
CREATE
  1. Begin SQL transaction (via session).
  2. INSERT product row → flush (assign id, timestamps).
  3. Generate embedding from product text.
  4. Upsert vector in Qdrant.
  5. If Qdrant raises → rollback SQL (session.rollback via exception propagation).
  6. If both succeed  → commit SQL.

UPDATE
  1. Begin SQL transaction.
  2. UPDATE product row → flush.
  3. Regenerate embedding.
  4. Replace vector in Qdrant (upsert overwrites the existing point).
  5. If Qdrant raises → rollback SQL.
  6. Commit SQL.

DELETE
  1. Begin SQL transaction.
  2. DELETE product row → flush.
  3. Delete vector from Qdrant.
  4. If Qdrant raises → rollback SQL.
  5. Commit SQL.

Why roll back SQL if Qdrant fails?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The two stores must stay consistent: a product in PostgreSQL with no
vector in Qdrant would be invisible to semantic search.  The safest
strategy is to treat Qdrant as the second phase of a two-phase commit —
if it fails, the SQL change is undone and the caller receives a 503.

Clean Architecture note
~~~~~~~~~~~~~~~~~~~~~~~
This service is the only place that knows about both stores.
Routers → Service → (Repository, EmbeddingService, VectorService).
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundException
from app.core.logging import get_logger
from app.models.product import Product
from app.repositories.product_repository import ProductRepository
from app.schemas.common import PaginatedResponse
from app.schemas.product import (
    CreateProductRequest,
    ProductResponse,
    UpdateProductRequest,
)
from app.services.embedding_service import EmbeddingService
from app.services.vector_service import VectorService

logger = get_logger(__name__)


class ProductService:
    """
    Orchestrates product lifecycle with guaranteed dual-write consistency.

    Args:
        db:          SQLAlchemy session (injected per request).
        vector_svc:  Qdrant vector service (injected per request).
        embedding_svc: Sentence-transformer service (injected per request).
    """

    def __init__(
        self,
        db: Session,
        vector_svc: VectorService,
        embedding_svc: EmbeddingService,
    ) -> None:
        self._repo = ProductRepository(db)
        self._db = db
        self._vector = vector_svc
        self._embedding = embedding_svc

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _build_embedding_text(self, product: Product) -> str:
        return EmbeddingService.build_document_text(
            title=product.title,
            description=product.description,
            category=product.category,
            difficulty=product.difficulty,
            tags=product.tags or [],
        )

    def _build_payload(self, product: Product) -> dict:
        """Minimal Qdrant payload — mirrors the most-searched fields."""
        return {
            "title": product.title,
            "category": product.category,
            "difficulty": product.difficulty,
            "tags": product.tags or [],
            "is_active": product.is_active,
        }

    def _get_or_404(self, product_id: uuid.UUID) -> Product:
        product = self._repo.get_by_id(product_id)
        if product is None:
            raise NotFoundException(f"Product {product_id} not found.")
        return product

    # ------------------------------------------------------------------ #
    # CREATE                                                              #
    # ------------------------------------------------------------------ #

    def create(self, payload: CreateProductRequest) -> ProductResponse:
        """
        Create a product and index its embedding in Qdrant.

        Steps:
        1. Persist in PostgreSQL (flush only — not committed yet).
        2. Generate embedding from product text.
        3. Upsert vector in Qdrant.
        4. If Qdrant fails → exception propagates, session auto-rolls back.
        5. Commit SQL.

        Args:
            payload: Validated ``CreateProductRequest``.

        Returns:
            ``ProductResponse`` for the newly created product.

        Raises:
            Exception: Propagates Qdrant errors as 503 (handled by caller).
        """
        data = payload.model_dump()
        product = self._repo.create(data)

        try:
            text = self._build_embedding_text(product)
            vector = self._embedding.embed_document(text)
            self._vector.upsert(
                product_id=product.id,
                vector=vector,
                payload=self._build_payload(product),
            )
        except Exception as exc:
            # Qdrant failed — roll back the SQL INSERT
            self._db.rollback()
            logger.error(
                "Qdrant upsert failed on create — SQL rolled back. "
                "product_id=%s error=%s",
                product.id,
                exc,
            )
            raise

        self._db.commit()
        self._db.refresh(product)

        logger.info(
            "Product created. id=%s title=%r",
            product.id,
            product.title,
        )
        return ProductResponse.model_validate(product)

    # ------------------------------------------------------------------ #
    # UPDATE                                                              #
    # ------------------------------------------------------------------ #

    def update(
        self,
        product_id: uuid.UUID,
        payload: UpdateProductRequest,
    ) -> ProductResponse:
        """
        Replace all product fields and re-index the embedding.

        Args:
            product_id: UUID of the product to update.
            payload:    Validated ``UpdateProductRequest``.

        Returns:
            ``ProductResponse`` for the updated product.

        Raises:
            NotFoundException:  Product not found.
            Exception:          Propagates Qdrant errors; SQL is rolled back.
        """
        product = self._get_or_404(product_id)
        data = payload.model_dump()
        product = self._repo.update(product, data)

        try:
            text = self._build_embedding_text(product)
            vector = self._embedding.embed_document(text)
            self._vector.upsert(
                product_id=product.id,
                vector=vector,
                payload=self._build_payload(product),
            )
        except Exception as exc:
            self._db.rollback()
            logger.error(
                "Qdrant upsert failed on update — SQL rolled back. "
                "product_id=%s error=%s",
                product_id,
                exc,
            )
            raise

        self._db.commit()
        self._db.refresh(product)

        logger.info("Product updated. id=%s title=%r", product.id, product.title)
        return ProductResponse.model_validate(product)

    # ------------------------------------------------------------------ #
    # DELETE                                                              #
    # ------------------------------------------------------------------ #

    def delete(self, product_id: uuid.UUID) -> None:
        """
        Hard-delete a product from PostgreSQL and Qdrant.

        Args:
            product_id: UUID of the product to delete.

        Raises:
            NotFoundException: Product not found.
            Exception:         Propagates Qdrant errors; SQL is rolled back.
        """
        product = self._get_or_404(product_id)
        self._repo.delete(product)

        try:
            self._vector.delete(product_id)
        except Exception as exc:
            self._db.rollback()
            logger.error(
                "Qdrant delete failed — SQL rolled back. "
                "product_id=%s error=%s",
                product_id,
                exc,
            )
            raise

        self._db.commit()
        logger.info("Product deleted. id=%s", product_id)

    # ------------------------------------------------------------------ #
    # READ                                                                #
    # ------------------------------------------------------------------ #

    def get_by_id(self, product_id: uuid.UUID) -> ProductResponse:
        """
        Return a single active product by ID.

        Args:
            product_id: UUID of the product.

        Returns:
            ``ProductResponse``.

        Raises:
            NotFoundException: Product not found or is inactive.
        """
        product = self._repo.get_by_id(product_id)
        if product is None or not product.is_active:
            raise NotFoundException(f"Product {product_id} not found.")
        return ProductResponse.model_validate(product)

    def list_active(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> PaginatedResponse[ProductResponse]:
        """
        Return a paginated list of active products (public endpoint).

        Args:
            page:      1-indexed page number.
            page_size: Items per page (max 100).

        Returns:
            ``PaginatedResponse[ProductResponse]``.
        """
        skip = (page - 1) * page_size
        items, total = self._repo.list_active(skip=skip, limit=page_size)
        return PaginatedResponse.of(
            items=[ProductResponse.model_validate(p) for p in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    def list_all(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> PaginatedResponse[ProductResponse]:
        """
        Return a paginated list of ALL products including inactive (admin).

        Args:
            page:      1-indexed page number.
            page_size: Items per page.

        Returns:
            ``PaginatedResponse[ProductResponse]``.
        """
        skip = (page - 1) * page_size
        items, total = self._repo.list_all(skip=skip, limit=page_size)
        return PaginatedResponse.of(
            items=[ProductResponse.model_validate(p) for p in items],
            total=total,
            page=page,
            page_size=page_size,
        )
