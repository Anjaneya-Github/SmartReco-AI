"""add_users_table

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-08-06 00:14:00.000000+00:00

What this migration does
~~~~~~~~~~~~~~~~~~~~~~~~
1. Creates the PostgreSQL ENUM type ``userrole`` with values
   ``user`` and ``admin``.
2. Creates the ``users`` table with all columns defined in
   ``app/models/user.py``.

Rollback
~~~~~~~~
``downgrade()`` drops the table then the ENUM type in the correct order
(the type cannot be dropped while any column still references it).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers — used by Alembic
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Native PostgreSQL ENUM type (must be created before the table)
userrole_enum = postgresql.ENUM(
    "user",
    "admin",
    name="userrole",
    create_type=False,   # we manage CREATE/DROP manually below
)


def upgrade() -> None:
    # 1. Create the ENUM type
    userrole_enum.create(op.get_bind(), checkfirst=True)

    # 2. Create the users table
    op.create_table(
        "users",
        # Primary key — UUID v4
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            comment="UUID v4 primary key",
        ),
        # Core fields
        sa.Column(
            "email",
            sa.String(255),
            nullable=False,
            comment="Unique email address (login identifier)",
        ),
        sa.Column(
            "full_name",
            sa.String(255),
            nullable=True,
            comment="Optional display name",
        ),
        sa.Column(
            "hashed_password",
            sa.String(255),
            nullable=False,
            comment="bcrypt hash of the user's password",
        ),
        sa.Column(
            "role",
            userrole_enum,
            nullable=False,
            server_default="user",
            comment="Access role: user | admin",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="False = account disabled",
        ),
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="True once email has been confirmed",
        ),
        # Audit timestamps (server-side defaults so DB handles them)
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Constraints and indexes
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_email", "users", ["email"])
    op.create_unique_constraint("uq_users_email", "users", ["email"])


def downgrade() -> None:
    # Drop constraints, table, then ENUM type (order matters)
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_id", table_name="users")
    op.drop_table("users")
    userrole_enum.drop(op.get_bind(), checkfirst=True)
