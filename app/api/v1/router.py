"""
app/api/v1/router.py
---------------------
Central aggregator for all API v1 routes.

This is the ONLY file that ``main.py`` needs to know about for
versioned routes.  Adding a new domain = one ``include_router`` line.

URL structure
~~~~~~~~~~~~~
/api/v1/auth/...
/api/v1/products/...
/api/v1/events/...
/api/v1/recommendations/...
/api/v1/admin/products/...
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routers.auth import router as auth_router
from app.routers.products import router as products_router
from app.routers.events import router as events_router
from app.routers.recommendations import router as recommendations_router
from app.routers.admin import router as admin_router

# Parent router that every feature router attaches to.
# ``main.py`` mounts this at prefix="/api/v1".
api_v1_router = APIRouter()

api_v1_router.include_router(auth_router)
api_v1_router.include_router(products_router)
api_v1_router.include_router(events_router)
api_v1_router.include_router(recommendations_router)
api_v1_router.include_router(admin_router)
