"""
app/routers/users.py
---------------------
User-profile routes.

Prefix : /users    (mounted at /api/v1 → /api/v1/users/...)
Tag    : Users

Endpoints
~~~~~~~~~
GET /api/v1/users/me/profile  — computed behavioral profile for the
                                current authenticated user

Design notes
~~~~~~~~~~~~
- All endpoints require a valid JWT.
- The profile is computed fresh on every request from the user's
  stored events — no caching in this iteration.
- No LLM, no Qdrant, no external calls — pure Python analytics.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.schemas.behavior import BehaviorProfile
from app.services.behavior_analyzer import BehaviorAnalyzer

router = APIRouter(prefix="/users", tags=["Users"])


# ------------------------------------------------------------------ #
# Dependency                                                          #
# ------------------------------------------------------------------ #

def _get_behavior_analyzer(db: Session = Depends(get_db)) -> BehaviorAnalyzer:
    return BehaviorAnalyzer(db)


# ------------------------------------------------------------------ #
# Endpoints                                                           #
# ------------------------------------------------------------------ #

@router.get(
    "/me/profile",
    response_model=BehaviorProfile,
    status_code=status.HTTP_200_OK,
    summary="Get current user's behavioral profile",
    responses={
        401: {"description": "Not authenticated"},
    },
)
def get_my_profile(
    current_user: User = Depends(get_current_user),
    analyzer: BehaviorAnalyzer = Depends(_get_behavior_analyzer),
) -> BehaviorProfile:
    """
    Return a computed behavioral profile for the authenticated user.

    The profile is derived entirely from the user's stored interaction
    history.  It includes:

    - **primary_categories** — top content categories by engagement
    - **favorite_tags** — most-interacted product tags
    - **top_searches** — most-repeated search queries
    - **search_frequency** — total searches in analysis window
    - **engagement_score** — normalised [0.0, 1.0] engagement depth
    - **learning_level** — inferred difficulty preference
    - **recent_activity_summary** — plain-English 7-day summary
    - **total_events_analysed** — window size
    - **last_active_at** — most recent event timestamp

    Returns an empty profile (all defaults) if the user has no events.
    """
    return analyzer.build_profile(user_id=current_user.id)
