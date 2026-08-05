"""
app/database/session.py
-----------------------
FastAPI dependency that provides a database session per request.

Usage in any route::

    from fastapi import Depends
    from sqlalchemy.orm import Session
    from app.database.session import get_db

    @router.get("/items")
    def list_items(db: Session = Depends(get_db)):
        ...
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from app.database.engine import SessionLocal
from app.core.logging import get_logger

logger = get_logger(__name__)


def get_db() -> Generator[Session, None, None]:
    """
    Yield a SQLAlchemy session and guarantee cleanup.

    - Commits automatically on a clean exit.
    - Rolls back on any exception so the connection is returned
      to the pool in a clean state.
    """
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
