"""
app/auth/password.py
---------------------
Password hashing and verification using bcrypt directly.

We call the ``bcrypt`` library directly rather than going through
Passlib because Passlib ≤ 1.7.4 has a compatibility issue with
bcrypt ≥ 4.0 (missing ``__about__`` attribute).  Using bcrypt
directly is explicit, dependency-free, and fully supported.

Why bcrypt?
~~~~~~~~~~~
- Adaptive work factor (``rounds``) — increase as hardware gets faster.
- Built-in random 128-bit salt per hash.
- Industry standard for password storage.

Encoding note
~~~~~~~~~~~~~
``bcrypt.hashpw`` and ``bcrypt.checkpw`` operate on ``bytes``.
Passwords are UTF-8 encoded before hashing.  bcrypt silently
truncates at 72 bytes, which is a known design limitation — mitigated
here by raising an explicit error so callers know to enforce the
max-length constraint at the schema level (already done in
``RegisterRequest.password`` max_length=128 warning is pre-enforced
by Pydantic to 128 chars, well within 72 *bytes* for typical ASCII;
adjust if you need to support long non-ASCII passwords).
"""

from __future__ import annotations

import bcrypt

# Work factor — 12 is the recommended minimum for 2024.
# Increase to 13 on hardware with <300ms acceptable latency.
_ROUNDS: int = 12


def hash_password(plain_password: str) -> str:
    """
    Return a bcrypt hash of *plain_password*.

    Args:
        plain_password: The raw password string supplied by the user.

    Returns:
        A bcrypt hash string (60 chars) safe to store in the database.

    Raises:
        ValueError: If the encoded password exceeds 72 bytes (bcrypt limit).
    """
    encoded = plain_password.encode("utf-8")
    if len(encoded) > 72:
        raise ValueError(
            "Password exceeds the 72-byte bcrypt limit. "
            "Enforce max_length=72 in the schema."
        )
    salt = bcrypt.gensalt(rounds=_ROUNDS)
    hashed = bcrypt.hashpw(encoded, salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Return ``True`` if *plain_password* matches *hashed_password*.

    Args:
        plain_password:  The raw password from the login request.
        hashed_password: The stored bcrypt hash from the database.

    Returns:
        ``True`` on match, ``False`` otherwise.
        Never raises — mismatches return ``False``.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False
