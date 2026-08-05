"""add_user_events_table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-06 01:46:00.000000+00:00

What this migration does
~~~~~~~~~~~~~~~~~~~~~~~~
1. Creates the PostgreSQL ENUM type ``eventtypeenum`` with all supported
   event-type values from ``app/models/event.py``.
2. Creates the ``user_events`` table with every column from that model.
3. Creates indexes on the most-queried columns:
   - user_id           — all queries for a user's history
   - event_type        — filtering by event type
   - product_id        — looking up events for a product
   - created_at        — time-range queries
   - (user_id, event_type) — composite index for filtered user queries

Rollback
~~~~~~~~
``downgrade()`` drops the table then the ENUM in the correct order.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# PostgreSQL ENUM for event_type — managed manually for explicit control
event_type_enum = postgresql.ENUM(
    "view",
    "click",
    "search",
    "purchase",
    "wishlist",
    "rating",
    "share",
    "impression",
    name="eventtypeenum",
    create_type=False,  # created/dropped manually in upgrade/downgrade
)


def upgrade() -> None:
    # 1. Create the ENUM type
    event_type_enum.create(op.get_bind(), checkfirst=True)

    # 2. Create the user_events table
    op.create_table(
        "user_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            comment="UUID v4 primary key",
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="User who triggered the event (soft FK → users.id)",
        ),
        sa.Column(
            "session_id",
            sa.String(128),
            nullable=False,
            comment="Client-generated session / device identifier",
        ),
        sa.Column(
            "event_type",
            event_type_enum,
            nullable=False,
            comment="Type of interaction",
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Product related to the event (optional, soft FK)",
        ),
        sa.Column(
            "search_query",
            sa.Text(),
            nullable=True,
            comment="Search query string — populated for SEARCH events",
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
            comment="JSONB bag for arbitrary event context",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="Event timestamp (immutable)",
        ),
    )

    # 3. Indexes — tuned for the most common query patterns
    op.create_index("ix_user_events_id",         "user_events", ["id"])
    op.create_index("ix_user_events_user_id",     "user_events", ["user_id"])
    op.create_index("ix_user_events_event_type",  "user_events", ["event_type"])
    op.create_index("ix_user_events_product_id",  "user_events", ["product_id"])
    op.create_index("ix_user_events_created_at",  "user_events", ["created_at"])
    op.create_index("ix_user_events_session_id",  "user_events", ["session_id"])

    # Composite index: user's events filtered by type (most common pattern)
    op.create_index(
        "ix_user_events_user_type",
        "user_events",
        ["user_id", "event_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_events_user_type",  table_name="user_events")
    op.drop_index("ix_user_events_session_id", table_name="user_events")
    op.drop_index("ix_user_events_created_at", table_name="user_events")
    op.drop_index("ix_user_events_product_id", table_name="user_events")
    op.drop_index("ix_user_events_event_type", table_name="user_events")
    op.drop_index("ix_user_events_user_id",    table_name="user_events")
    op.drop_index("ix_user_events_id",         table_name="user_events")
    op.drop_table("user_events")
    event_type_enum.drop(op.get_bind(), checkfirst=True)
