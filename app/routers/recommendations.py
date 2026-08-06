"""
app/routers/recommendations.py
--------------------------------
Recommendation engine routes.

Prefix  : /recommendations  (mounted under /api/v1)
Tag     : Recommendations

Endpoints
~~~~~~~~~
POST /api/v1/recommendations/generate
    Admin-only.  Triggers the LLM pipeline for a given user and
    persists the result to the ``recommendations`` table.

GET  /api/v1/recommendations/me
    Returns the most recently generated recommendation for the
    authenticated user (reads from DB — no LLM call).

GET  /api/v1/recommendations/similar/{product_id}   — placeholder
GET  /api/v1/recommendations/trending               — placeholder
POST /api/v1/recommendations/feedback               — placeholder
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_admin, get_current_user
from app.core.exceptions import NotFoundException
from app.database.session import get_db
from app.models.user import User
from app.schemas.recommendation import GenerateRequest, RecommendationResult
from app.services.recommendation_service import RecommendationService

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


# ------------------------------------------------------------------ #
# Dependency                                                          #
# ------------------------------------------------------------------ #

def _get_recommendation_service(
    db: Session = Depends(get_db),
) -> RecommendationService:
    return RecommendationService(db)


# ------------------------------------------------------------------ #
# Endpoints                                                           #
# ------------------------------------------------------------------ #

@router.post(
    "/generate",
    response_model=RecommendationResult,
    status_code=status.HTTP_201_CREATED,
    summary="Generate and persist recommendations for a user (admin only)",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required"},
        404: {"description": "User not found"},
        503: {"description": "LLM or vector store unavailable"},
    },
)
def generate_recommendations(
    payload: GenerateRequest,
    _admin: User = Depends(get_current_admin),
    service: RecommendationService = Depends(_get_recommendation_service),
) -> RecommendationResult:
    """
    Run the full recommendation pipeline for ``payload.user_id``.

    Steps (all handled by ``RecommendationService``):
    1. Build the user's ``BehaviorProfile`` from recent events.
    2. Retrieve candidate products via vector similarity.
    3. Call the LLM with the profile + candidates.
    4. Validate and persist the result.
    5. Return the ``RecommendationResult``.

    The result is stored in the ``recommendations`` table so subsequent
    ``GET /me`` requests can return it without re-invoking the LLM.

    Admin-only — call this manually or from a scheduled job.
    """
    return service.generate(
        user_id=payload.user_id,
        max_products=payload.max_products,
    )


@router.get(
    "/me",
    response_model=RecommendationResult,
    status_code=status.HTTP_200_OK,
    summary="Get the latest cached recommendation for the current user",
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "No recommendations generated yet"},
    },
)
def get_my_recommendations(
    current_user: User = Depends(get_current_user),
    service: RecommendationService = Depends(_get_recommendation_service),
) -> RecommendationResult:
    """
    Return the most recently generated recommendation for the current user.

    Reads from the ``recommendations`` table — **no LLM call**.
    Raises 404 if no recommendation has been generated yet.
    """
    result = service.get_latest(current_user.id)
    if result is None:
        raise NotFoundException(
            "No recommendations found. Ask an admin to generate them."
        )
    return result


# ------------------------------------------------------------------ #
# Placeholder endpoints (future iterations)                           #
# ------------------------------------------------------------------ #

@router.get(
    "/similar/{product_id}",
    status_code=status.HTTP_200_OK,
    summary="Similar products — not yet implemented",
    include_in_schema=True,
)
def get_similar(product_id: uuid.UUID) -> dict:
    """Return items similar to the given product.  *Not yet implemented.*"""
    return {"message": "Not yet implemented", "product_id": str(product_id)}


@router.get(
    "/trending",
    status_code=status.HTTP_200_OK,
    summary="Trending products — not yet implemented",
    include_in_schema=True,
)
def get_trending() -> dict:
    """Return currently trending / popular products.  *Not yet implemented.*"""
    return {"message": "Not yet implemented"}


@router.post(
    "/feedback",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit recommendation feedback — not yet implemented",
    include_in_schema=True,
)
def submit_feedback() -> dict:
    """Record explicit user feedback on a recommendation.  *Not yet implemented.*"""
    return {"message": "Not yet implemented"}
