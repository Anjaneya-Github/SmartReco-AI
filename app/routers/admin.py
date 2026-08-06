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

Scheduler endpoints
~~~~~~~~~~~~~~~~~~~
POST   /api/v1/admin/scheduler/run      — run a job immediately
GET    /api/v1/admin/scheduler/status   — scheduler + per-job status
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, status
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


# ------------------------------------------------------------------ #
# Scheduler endpoints                                                 #
# ------------------------------------------------------------------ #

_VALID_JOB_IDS = ["daily_reco_refresh", "cache_cleanup", "event_cleanup"]


@router.post(
    "/scheduler/run",
    status_code=status.HTTP_202_ACCEPTED,
    summary="[Admin] Run a scheduler job immediately",
    responses={
        400: {"description": "Unknown job_id"},
    },
)
def run_scheduler_job(
    job_id: str = Body(..., embed=True, description=f"One of: {_VALID_JOB_IDS}"),
) -> dict:
    """
    Trigger a registered scheduler job immediately (runs synchronously).

    Useful for testing job logic without waiting for the cron schedule.
    The job runs in the current request thread and returns when complete.
    """
    from app.core.exceptions import BadRequestException
    from app.scheduler.scheduler import run_job_now

    try:
        result = run_job_now(job_id)
    except ValueError as exc:
        raise BadRequestException(str(exc)) from exc

    return result


@router.get(
    "/scheduler/status",
    status_code=status.HTTP_200_OK,
    summary="[Admin] Get scheduler status and job metadata",
)
def get_scheduler_status() -> dict:
    """
    Return the current APScheduler status and per-job metadata.

    Response fields per job:
    - ``id``                      — job identifier
    - ``name``                    — human-readable name
    - ``next_run_time``           — ISO 8601 UTC timestamp of next execution
    - ``last_run``                — ISO 8601 UTC timestamp of last execution
    - ``last_status``             — success / error / never / skipped_no_redis
    - ``last_duration_s``         — execution time in seconds
    - ``recommendations_generated`` — count (daily_reco_refresh only)
    - ``events_archived``         — count (event_cleanup only)
    - ``keys_found``              — Redis key count (cache_cleanup only)
    """
    from app.scheduler.scheduler import get_status
    return get_status()


# ------------------------------------------------------------------ #
# User listing (admin)                                                #
# ------------------------------------------------------------------ #

@router.get(
    "/users",
    status_code=status.HTTP_200_OK,
    summary="[Admin] List all users",
)
def admin_list_users(db: Session = Depends(get_db)) -> dict:
    """Return all registered users — used by the admin dashboard user picker."""
    from sqlalchemy import select
    from app.models.user import User as UserModel
    users = db.execute(select(UserModel).order_by(UserModel.created_at)).scalars().all()
    return {
        "users": [
            {
                "id":        str(u.id),
                "email":     u.email,
                "full_name": u.full_name or "",
                "role":      u.role.value,
                "is_active": u.is_active,
            }
            for u in users
        ],
        "total": len(users),
    }
