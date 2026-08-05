"""
app/routers/health.py
----------------------
Health-check endpoints used by load balancers and container
orchestrators (Kubernetes liveness / readiness probes, ECS, etc.).

GET /health        — liveness   (is the process alive?)
GET /health/ready  — readiness  (can it serve traffic? checks DB)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.session import get_db

router = APIRouter(tags=["Health"])


# ------------------------------------------------------------------ #
# Response schemas                                                    #
# ------------------------------------------------------------------ #

class HealthResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    database: str


# ------------------------------------------------------------------ #
# Endpoints                                                           #
# ------------------------------------------------------------------ #

@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
    description="Returns **healthy** when the application process is running.",
)
def health_check() -> HealthResponse:
    return HealthResponse(status="healthy")


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
    summary="Readiness probe",
    description="Returns **ready** when the application can reach the database.",
)
def readiness_check(db: Session = Depends(get_db)) -> ReadinessResponse:
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "unavailable"

    return ReadinessResponse(
        status="ready" if db_status == "ok" else "degraded",
        database=db_status,
    )
