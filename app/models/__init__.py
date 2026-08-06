"""
app/models/__init__.py
-----------------------
Re-export every ORM model so Alembic autogenerate can discover them
by importing this single module in ``alembic/env.py``.

Add new models here as they are created.
"""

from app.database.base import Base  # noqa: F401 — keeps metadata populated
from app.models.user import User, UserRole  # noqa: F401
from app.models.product import Product  # noqa: F401
from app.models.event import UserEvent, EventType  # noqa: F401
from app.models.recommendation import Recommendation  # noqa: F401

__all__ = [
    "Base",
    "User", "UserRole",
    "Product",
    "UserEvent", "EventType",
    "Recommendation",
]
