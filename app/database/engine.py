"""
app/database/engine.py
----------------------
SQLAlchemy 2.0 engine and session factory.

The engine is created once at import time and reused for the lifetime
of the process.  Connection-pool settings are tuned for a typical
web-service workload; adjust via environment variables as needed.
"""

from __future__ import annotations

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ------------------------------------------------------------------ #
# Engine                                                              #
# ------------------------------------------------------------------ #

engine: Engine = create_engine(
    settings.DATABASE_URL,
    # Pool configuration
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,       # verify connection health before checkout
    pool_recycle=3600,        # recycle connections every hour
    # Echo SQL only in debug mode — never in production
    echo=settings.DEBUG and not settings.is_production,
    future=True,              # SQLAlchemy 2.0-style engine
)


@event.listens_for(engine, "connect")
def _on_connect(dbapi_connection, connection_record) -> None:  # type: ignore[type-arg]
    """Log a line whenever a new physical DB connection is established."""
    logger.debug("New database connection opened.")


# ------------------------------------------------------------------ #
# Session factory                                                      #
# ------------------------------------------------------------------ #

SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,   # objects stay usable after session.commit()
)
