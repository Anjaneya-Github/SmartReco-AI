"""
app/routers/recommendations.py
--------------------------------
Recommendation engine routes.

Prefix  : /recommendations  (mounted under /api/v1 → /api/v1/recommendations/...)
Tag     : Recommendations

Planned endpoints
~~~~~~~~~~~~~~~~~
GET  /api/v1/recommendations                     — personalised feed for the current user
GET  /api/v1/recommendations/similar/{product_id} — products similar to a given item
GET  /api/v1/recommendations/trending            — trending / popular items
POST /api/v1/recommendations/feedback            — explicit thumbs-up/down signal

Business logic (LangGraph + Qdrant) lives in
app/services/recommendation_service.py (not yet implemented).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from pydantic import BaseModel

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


# ------------------------------------------------------------------ #
# Placeholder schemas                                                 #
# ------------------------------------------------------------------ #

class _Placeholder(BaseModel):
    message: str
    endpoint: str


# ------------------------------------------------------------------ #
# Endpoints                                                           #
# ------------------------------------------------------------------ #

@router.get(
    "",
    response_model=_Placeholder,
    status_code=status.HTTP_200_OK,
    summary="Personalised recommendations for the current user",
)
def get_recommendations() -> _Placeholder:
    """Return a personalised product feed.  *Not yet implemented.*"""
    return _Placeholder(
        message="Not yet implemented",
        endpoint="GET /api/v1/recommendations",
    )


@router.get(
    "/similar/{product_id}",
    response_model=_Placeholder,
    status_code=status.HTTP_200_OK,
    summary="Similar products",
)
def get_similar(product_id: uuid.UUID) -> _Placeholder:
    """Return items similar to the given product.  *Not yet implemented.*"""
    return _Placeholder(
        message="Not yet implemented",
        endpoint=f"GET /api/v1/recommendations/similar/{product_id}",
    )


@router.get(
    "/trending",
    response_model=_Placeholder,
    status_code=status.HTTP_200_OK,
    summary="Trending products",
)
def get_trending() -> _Placeholder:
    """Return currently trending / popular products.  *Not yet implemented.*"""
    return _Placeholder(
        message="Not yet implemented",
        endpoint="GET /api/v1/recommendations/trending",
    )


@router.post(
    "/feedback",
    response_model=_Placeholder,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit recommendation feedback",
)
def submit_feedback() -> _Placeholder:
    """Record explicit user feedback on a recommendation.  *Not yet implemented.*"""
    return _Placeholder(
        message="Not yet implemented",
        endpoint="POST /api/v1/recommendations/feedback",
    )
