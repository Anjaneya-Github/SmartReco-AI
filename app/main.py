"""
app/main.py
-----------
SmartReco AI — FastAPI application factory.

Responsibilities
~~~~~~~~~~~~~~~~
1. Create the FastAPI instance with Swagger / ReDoc configuration.
2. Register all middleware (order matters — last-added runs first).
3. Register all routers.
4. Register global exception handlers.
5. Handle startup and shutdown lifecycle events.

Nothing else belongs here.  Business logic lives in services/,
data access in repositories/, HTTP concerns in routers/.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from qdrant_client.http.exceptions import UnexpectedResponse

from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.exceptions import AppException
from app.core.logging import get_logger, setup_logging
from app.database.engine import engine
from app.middleware.logging import AccessLogMiddleware
from app.middleware.request_id import RequestIDMiddleware
from app.routers.health import router as health_router
from app.services.vector_service import VectorService, _get_qdrant_client

# Bootstrap logging first so every subsequent log call is formatted.
setup_logging()
logger = get_logger(__name__)


# ------------------------------------------------------------------ #
# Lifespan                                                            #
# ------------------------------------------------------------------ #

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan handler (replaces @app.on_event).

    Startup  → validate DB connectivity, log startup info.
    Shutdown → dispose connection pool gracefully.
    """
    # ---- STARTUP ----
    logger.info(
        "Starting %s v%s [env=%s]",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.APP_ENV,
    )

    # Verify the database engine can be imported without errors.
    # Actual connection attempts happen per-request via get_db().
    logger.info("Database engine ready  [pool_size=%d]", engine.pool.size())

    # Ensure the Qdrant products collection exists.
    try:
        vector_svc = VectorService(_get_qdrant_client())
        vector_svc.ensure_collection()
    except Exception as exc:
        logger.warning("Qdrant unavailable at startup — will retry on first use. error=%s", exc)

    yield  # ← application is running here

    # ---- SHUTDOWN ----
    logger.info("Shutting down %s — disposing connection pool.", settings.APP_NAME)
    engine.dispose()
    logger.info("Shutdown complete.")


# ------------------------------------------------------------------ #
# Application factory                                                 #
# ------------------------------------------------------------------ #

def create_app() -> FastAPI:
    """
    Construct and return the configured FastAPI application.

    Separating construction from module-level instantiation makes
    the app easy to test — tests can call ``create_app()`` with
    overridden settings without side-effects.
    """
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "**SmartReco AI** — intelligent, context-aware recommendation engine.\n\n"
            "Authenticate endpoints via **Bearer** JWT.\n"
            "Obtain a token from `/api/v1/auth/login`."
        ),
        # Swagger UI lives at /docs, ReDoc at /redoc
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        swagger_ui_parameters={
            "persistAuthorization": True,
            "displayRequestDuration": True,
            "filter": True,
            "syntaxHighlight.theme": "monokai",
        },
        lifespan=lifespan,
    )

    _register_middleware(app)
    _register_exception_handlers(app)
    _register_routers(app)
    _mount_static(app)

    return app


# ------------------------------------------------------------------ #
# Private helpers                                                     #
# ------------------------------------------------------------------ #

def _register_middleware(app: FastAPI) -> None:
    """
    Register middleware in reverse execution order.

    Starlette middleware stacks like an onion: the last ``add_middleware``
    call wraps the outermost layer.  For readability, define the order
    you want requests to be processed (top → bottom), then add them
    in reverse below.

    Desired order (outermost → innermost):
        1. RequestIDMiddleware   — assign X-Request-ID
        2. AccessLogMiddleware   — log every request
        3. CORSMiddleware        — handle CORS preflight
    """
    # Added last → runs first (outermost)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=settings.ALLOW_CREDENTIALS,
        allow_methods=settings.ALLOWED_METHODS,
        allow_headers=settings.ALLOWED_HEADERS,
    )


def _register_exception_handlers(app: FastAPI) -> None:
    """Map domain exceptions to JSON HTTP responses."""

    @app.exception_handler(AppException)
    async def _app_exception_handler(
        request: Request, exc: AppException
    ) -> JSONResponse:
        request_id: str = getattr(request.state, "request_id", "")
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "request_id": request_id},
        )

    @app.exception_handler(UnexpectedResponse)
    async def _qdrant_exception_handler(
        request: Request, exc: UnexpectedResponse
    ) -> JSONResponse:
        """Map Qdrant HTTP errors to 503 Service Unavailable."""
        request_id: str = getattr(request.state, "request_id", "")
        logger.error(
            "Qdrant error on %s %s: %s",
            request.method, request.url.path, exc,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": "Vector store is temporarily unavailable.",
                "request_id": request_id,
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        request_id: str = getattr(request.state, "request_id", "")
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "An internal server error occurred.",
                "request_id": request_id,
            },
        )


def _register_routers(app: FastAPI) -> None:
    """
    Include all route modules.

    Routing map
    ~~~~~~~~~~~
    GET  /                        — application metadata (unversioned)
    GET  /health                  — liveness probe       (unversioned, infra)
    GET  /health/ready            — readiness probe      (unversioned, infra)

    /api/v1/auth/...              — authentication
    /api/v1/products/...          — product catalogue
    /api/v1/events/...            — user-interaction events
    /api/v1/recommendations/...   — recommendation engine
    /api/v1/admin/...             — admin operations

    Health is intentionally NOT versioned: load balancers and
    orchestrators call it directly and should not need updating when
    the API version changes.
    """

    # ---- Root endpoint (unversioned) ----
    @app.get(
        "/",
        tags=["Root"],
        summary="Application info",
        response_description="Application name and version",
    )
    def root() -> dict[str, str]:
        """Returns basic application metadata."""
        return {
            "application": settings.APP_NAME,
            "version": settings.APP_VERSION,
        }

    # ---- Infrastructure (unversioned) ----
    app.include_router(health_router)

    # ---- Versioned API v1 ----
    app.include_router(api_v1_router, prefix="/api/v1")


def _mount_static(app: FastAPI) -> None:
    """Mount the static-files directory if it exists."""
    import os
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ------------------------------------------------------------------ #
# Module-level app instance                                           #
# ------------------------------------------------------------------ #

app: FastAPI = create_app()
