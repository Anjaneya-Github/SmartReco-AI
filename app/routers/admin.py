"""
app/routers/admin.py
---------------------
Admin-only routes.

Prefix : /admin    (mounted at /api/v1 → /api/v1/admin/...)
Tag    : Admin

All routes require ADMIN role — enforced by the router-level
``dependencies=[Depends(get_current_admin)]``.

Product endpoints
~~~~~~~~~~~~~~~~~
POST   /api/v1/admin/products           — create product + embed + index
PUT    /api/v1/admin/products/{id}      — full replace + re-embed + re-index
DELETE /api/v1/admin/products/{id}      — delete SQL row + delete vector
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_admin
from app.database.session import get_db
from app.schemas.common import PaginatedResponse
from app.schemas.product import (
    CreateProductRequest,
    ProductResponse,
    UpdateProductRequest,
)
from app.services.embedding_service import EmbeddingService
from app.services.product_service import ProductService
from app.services.vector_service import VectorService, get_vector_service

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(get_current_admin)],  # protects every route below
)

_MAX_PAGE_SIZE = 100


# ------------------------------------------------------------------ #
# Dependency                                                          #
# ------------------------------------------------------------------ #

def _get_product_service(
    db: Session = Depends(get_db),
    vector_svc: VectorService = Depends(get_vector_service),
) -> ProductService:
    return ProductService(db, vector_svc, EmbeddingService())


# ------------------------------------------------------------------ #
# Product management                                                  #
# ------------------------------------------------------------------ #

@router.post(
    "/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[Admin] Create a product",
    responses={
        422: {"description": "Validation error"},
        503: {"description": "Vector store unavailable — SQL rolled back"},
    },
)
def admin_create_product(
    payload: CreateProductRequest,
    service: ProductService = Depends(_get_product_service),
) -> ProductResponse:
    """
    Create a product, generate its embedding, and store in Qdrant.

    If the Qdrant write fails the SQL INSERT is rolled back and
    a 503 is returned — guaranteeing both stores stay in sync.
    """
    return service.create(payload)


@router.put(
    "/products/{product_id}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="[Admin] Replace a product",
    responses={
        404: {"description": "Product not found"},
        503: {"description": "Vector store unavailable — SQL rolled back"},
    },
)
def admin_update_product(
    product_id: uuid.UUID,
    payload: UpdateProductRequest,
    service: ProductService = Depends(_get_product_service),
) -> ProductResponse:
    """
    Fully replace a product and re-index its embedding in Qdrant.

    If the Qdrant write fails the SQL UPDATE is rolled back.
    """
    return service.update(product_id, payload)


@router.delete(
    "/products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="[Admin] Delete a product",
    responses={
        404: {"description": "Product not found"},
        503: {"description": "Vector store unavailable — SQL rolled back"},
    },
)
def admin_delete_product(
    product_id: uuid.UUID,
    service: ProductService = Depends(_get_product_service),
) -> None:
    """
    Hard-delete a product from PostgreSQL and its vector from Qdrant.

    If the Qdrant delete fails the SQL DELETE is rolled back.
    """
    service.delete(product_id)
