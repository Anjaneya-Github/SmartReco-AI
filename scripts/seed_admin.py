"""
scripts/seed_admin.py
----------------------
Create the first administrator account.

Run once after ``alembic upgrade head``::

    python scripts/seed_admin.py

Or with custom values via environment variables::

    ADMIN_EMAIL=boss@example.com ADMIN_PASSWORD=S3cret! python scripts/seed_admin.py

The script is idempotent — running it twice will print a notice and
exit without modifying the database if the email already exists.

Security note
~~~~~~~~~~~~~
Never hard-code real credentials here.  Provide them via environment
variables or a secrets manager and rotate the password immediately
after first login.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path so ``app.*`` imports resolve
# regardless of where the script is invoked from.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.auth.password import hash_password
from app.core.logging import get_logger, setup_logging
from app.database.engine import SessionLocal
from app.models.user import UserRole  # noqa: F401 — triggers model registration
from app.repositories.user_repository import UserRepository

setup_logging()
logger = get_logger(__name__)


def main() -> None:
    """Entry point — create admin user if it does not already exist."""

    admin_email: str = os.environ.get("ADMIN_EMAIL", "admin@smartreco.ai")
    admin_password: str = os.environ.get("ADMIN_PASSWORD", "Admin1234!")
    admin_name: str = os.environ.get("ADMIN_FULL_NAME", "SmartReco Admin")

    # Basic password sanity check so the script refuses obviously weak secrets.
    if len(admin_password) < 8:
        logger.error("ADMIN_PASSWORD must be at least 8 characters.")
        sys.exit(1)

    with SessionLocal() as db:
        repo = UserRepository(db)

        if repo.email_exists(admin_email):
            logger.info(
                "Admin account already exists — nothing to do. email=%s",
                admin_email,
            )
            return

        user = repo.create(
            email=admin_email,
            hashed_password=hash_password(admin_password),
            full_name=admin_name,
            role="admin",
            is_active=True,
            is_verified=True,
        )
        db.commit()
        db.refresh(user)

        logger.info(
            "Admin account created successfully. id=%s email=%s",
            user.id,
            user.email,
        )
        print(f"\n✅  Admin created — id: {user.id}  email: {admin_email}\n")


if __name__ == "__main__":
    main()
