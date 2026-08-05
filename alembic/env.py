"""
alembic/env.py
--------------
Alembic migration environment.

Reads the live DATABASE_URL from Pydantic Settings and targets the
same declarative Base that all ORM models use — so ``alembic revision
--autogenerate`` picks up model changes automatically.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.database.base import Base

# Import all models so their tables appear in Base.metadata
import app.models  # noqa: F401

# Alembic Config object — access values from alembic.ini
alembic_cfg = context.config

# Configure stdlib logging from alembic.ini [loggers] section
if alembic_cfg.config_file_name is not None:
    fileConfig(alembic_cfg.config_file_name)

# Override the sqlalchemy.url with the live setting value
alembic_cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = Base.metadata


# ------------------------------------------------------------------ #
# Offline migration (generates SQL without a live DB connection)      #
# ------------------------------------------------------------------ #

def run_migrations_offline() -> None:
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ------------------------------------------------------------------ #
# Online migration (runs against a live DB connection)               #
# ------------------------------------------------------------------ #

def run_migrations_online() -> None:
    connectable = engine_from_config(
        alembic_cfg.get_section(alembic_cfg.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # single connection per migration run
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
