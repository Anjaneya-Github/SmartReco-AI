"""app/dashboard/dashboard_router.py — Dashboard + analytics + feedback + UI routes."""
from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.auth.dependencies import get_current_admin, get_current_user
from app.core.exceptions import NotFoundException
from app.dashboard.dashboard_schema import AnalyticsResponse, DashboardResponse
from app.dashboard.dashboard_service import DashboardService
from app.database.session import get_db
from app.models.user import User

router = APIRouter(tags=["Dashboard"])

import pathlib
_TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _get_dashboard_service(db: Session = Depends(get_db)) -> DashboardService:
    return DashboardService(db)


# ── JSON API endpoints ────────────────────────────────────────────────

@router.get(
    "/api/v1/dashboard",
    response_model=DashboardResponse,
    summary="Full dashboard for the current user (read-only)",
)
def get_dashboard(
    current_user: User = Depends(get_current_user),
    svc: DashboardService = Depends(_get_dashboard_service),
) -> DashboardResponse:
    """Aggregate user info, behavior profile, latest recommendation. Never regenerates."""
    return svc.get_dashboard(current_user.id)


@router.get(
    "/api/v1/dashboard/analytics",
    response_model=AnalyticsResponse,
    summary="Admin analytics (admin only)",
)
def get_analytics(
    _admin: User = Depends(get_current_admin),
    svc: DashboardService = Depends(_get_dashboard_service),
) -> AnalyticsResponse:
    """Global platform analytics for the admin dashboard."""
    return svc.get_analytics()


# ── Feedback endpoint ─────────────────────────────────────────────────

from pydantic import BaseModel as _BM
class FeedbackRequest(_BM):
    liked: bool

from app.repositories.event_repository import EventRepository
from app.repositories.recommendation_repository import RecommendationRepository
from app.models.event import EventType
import json as _json

@router.post(
    "/api/v1/recommendations/{recommendation_id}/feedback",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit thumbs-up/down feedback on a recommendation",
)
def submit_feedback(
    recommendation_id: uuid.UUID,
    body: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Convert feedback into a behavioral event and persist it."""
    rec_repo = RecommendationRepository(db)
    rec = rec_repo.get_latest_for_user(current_user.id)
    if not rec or rec.id != recommendation_id:
        raise NotFoundException("Recommendation not found.")

    event_repo = EventRepository(db)
    event_type = EventType.RATING
    rows = [{
        "user_id": current_user.id,
        "session_id": f"feedback-{recommendation_id}",
        "event_type": event_type,
        "product_id": None,
        "search_query": None,
        "metadata": {
            "feedback": "liked" if body.liked else "disliked",
            "recommendation_id": str(recommendation_id),
        },
    }]
    event_repo.insert_batch(rows)
    db.commit()

    # Invalidate dashboard cache
    from app.cache.redis_client import CacheClient
    from app.cache.keys import dashboard_key, behavior_key
    cache = CacheClient()
    cache.delete(dashboard_key(str(current_user.id)))
    cache.delete(behavior_key(str(current_user.id)))

    return {"accepted": True, "liked": body.liked}


# ── Jinja2 HTML routes ────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html")


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "dashboard.html")


@router.get("/products", response_class=HTMLResponse, include_in_schema=False)
def products_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "products.html")


@router.get("/products/{product_id}", response_class=HTMLResponse, include_in_schema=False)
def product_detail_page(request: Request, product_id: uuid.UUID) -> HTMLResponse:
    return templates.TemplateResponse(request, "product_detail.html", {"product_id": str(product_id)})


@router.get("/admin/dashboard", response_class=HTMLResponse, include_in_schema=False)
def admin_dashboard_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "admin/dashboard.html")


@router.get("/admin/products", response_class=HTMLResponse, include_in_schema=False)
def admin_products_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "admin/products.html")
