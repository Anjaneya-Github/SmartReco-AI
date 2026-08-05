"""
app/routers/products.py
------------------------
Public product catalogue routes (no authentication required).

Prefix : /products    (mounted at /api/v1 → /api/v1/products/...)
Tag    : Products

Endpoints
~~~~~~~~~
GET /api/v1/products          — paginated list of active products
GET /api/v1/products/{id}     — single active product by UUID
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.common import PaginatedResponse
from app.schemas.product import ProductResponse
from app.services.embedding_service import EmbeddingService
from app.services.product_service import ProductService
from app.services.vector_service import VectorService, get_vector_service

router = APIRouter(prefix="/products", tags=["Products"])

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
# Endpoints                                                           #
# ------------------------------------------------------------------ #

@router.get(
    "",
    response_model=PaginatedResponse[ProductResponse],
    status_code=status.HTTP_200_OK,
    summary="List active products",
)
def list_products(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(
        default=20, ge=1, le=_MAX_PAGE_SIZE, description="Items per page"
    ),
    service: ProductService = Depends(_get_product_service),
) -> PaginatedResponse[ProductResponse]:
    """Return a paginated list of active products."""
    return service.list_active(page=page, page_size=page_size)


@router.get(
    "/{product_id}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Get product by ID",
    responses={404: {"description": "Product not found"}},
)
def get_product(
    product_id: uuid.UUID,
    service: ProductService = Depends(_get_product_service),
) -> ProductResponse:
    """Return a single active product by its UUID."""
    return service.get_by_id(product_id)
