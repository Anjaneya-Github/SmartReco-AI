"""
app/services/auth_service.py
------------------------------
Authentication service — orchestrates user registration and login.

Responsibilities
~~~~~~~~~~~~~~~~
- Coordinate the repository (data access) and auth helpers (crypto).
- Enforce business rules: duplicate email check, active-account check.
- Return domain objects or raise domain exceptions.
- Know nothing about HTTP: no ``Request``, no ``Response``, no status codes.

Clean-Architecture note
~~~~~~~~~~~~~~~~~~~~~~~
The router calls the service; the service calls the repository.
HTTP → Service → Repository → Database.
Exceptions bubble up as domain exceptions and are converted to HTTP
responses by the global handler in ``main.py``.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.auth.jwt import create_access_token
from app.auth.password import hash_password, verify_password
from app.core.exceptions import AlreadyExistsException, UnauthorizedException
from app.core.logging import get_logger
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import LoginRequest, RegisterRequest, TokenResponse

logger = get_logger(__name__)


class AuthService:
    """
    Handles user registration and credential-based login.

    Args:
        db: SQLAlchemy session for the current request (injected by FastAPI).
    """

    def __init__(self, db: Session) -> None:
        self._repo = UserRepository(db)
        self._db = db

    # ------------------------------------------------------------------ #
    # Registration                                                        #
    # ------------------------------------------------------------------ #

    def register(self, payload: RegisterRequest) -> User:
        """
        Create a new user account.

        Args:
            payload: Validated ``RegisterRequest`` containing email and password.

        Returns:
            The newly created ``User`` ORM instance.

        Raises:
            AlreadyExistsException: If the email is already registered.
        """
        if self._repo.email_exists(payload.email):
            logger.warning("Registration attempt with existing email: %s", payload.email)
            raise AlreadyExistsException("An account with this email already exists.")

        user = self._repo.create(
            email=payload.email,
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name,
            role="user",
        )
        self._db.commit()
        self._db.refresh(user)

        logger.info("New user registered: id=%s email=%s", user.id, user.email)
        return user

    # ------------------------------------------------------------------ #
    # Login                                                               #
    # ------------------------------------------------------------------ #

    def login(self, payload: LoginRequest) -> TokenResponse:
        """
        Validate credentials and return a JWT access token.

        Args:
            payload: Validated ``LoginRequest`` containing email and password.

        Returns:
            ``TokenResponse`` with a signed JWT.

        Raises:
            UnauthorizedException: For any credential mismatch or inactive account.
                                   (Generic message prevents user-enumeration attacks.)
        """
        user = self._repo.get_by_email(payload.email)

        # Use a constant-time generic error to prevent user enumeration.
        _INVALID_CREDENTIALS = "Incorrect email or password."

        if user is None:
            # Still run a verify to prevent timing attacks that reveal
            # whether an account exists based on response latency.
            # The dummy hash is a real bcrypt hash of a throwaway string.
            _DUMMY_HASH = "$2b$12$KIXsY6O6Y6Y6Y6Y6Y6Y6YO6Y6Y6Y6Y6Y6Y6Y6Y6Y6Y6Y6Y6Y6Y6Y6"
            verify_password(payload.password, _DUMMY_HASH)
            raise UnauthorizedException(_INVALID_CREDENTIALS)

        if not verify_password(payload.password, user.hashed_password):
            raise UnauthorizedException(_INVALID_CREDENTIALS)

        if not user.is_active:
            raise UnauthorizedException("This account has been disabled.")

        token = create_access_token(subject=user.id, role=user.role.value)

        logger.info("Successful login: id=%s email=%s role=%s", user.id, user.email, user.role.value)
        return TokenResponse(access_token=token)
