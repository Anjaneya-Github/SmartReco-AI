"""
app/repositories/recommendation_repository.py
-----------------------------------------------
Data-access layer for ``Recommendation`` records.

All SQL lives here.  Services call these methods; they never touch
SQLAlchemy directly — keeping the data-access layer cleanly separated
from business logic.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.recommendation import Recommendation


class RecommendationRepository:
    """
    Encapsulates all database operations for ``Recommendation`` records.

    Args:
        db: An active SQLAlchemy ``Session`` (injected per request).
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------ #
    # Writes                                                              #
    # ------------------------------------------------------------------ #

    def create(
        self,
        user_id: uuid.UUID,
        summary: str,
        reasoning: str,
        recommended_products: list[dict],
        confidence: float,
    ) -> Recommendation:
        """
        Persist a new recommendation row and return the flushed instance.

        The caller is responsible for committing the transaction.

        Args:
            user_id:               Target user.
            summary:               LLM-generated personalised story.
            reasoning:             LLM explanation paragraph.
            recommended_products:  List of product dicts (top 5).
            confidence:            Confidence score [0.0, 1.0].

        Returns:
            Newly created ``Recommendation`` instance with ``id`` populated.
        """
        rec = Recommendation(
            user_id=user_id,
            summary=summary,
            reasoning=reasoning,
            recommended_products=recommended_products,
            confidence=confidence,
        )
        self._db.add(rec)
        self._db.flush()
        self._db.refresh(rec)
        return rec

    # ------------------------------------------------------------------ #
    # Reads                                                               #
    # ------------------------------------------------------------------ #

    def get_latest_for_user(self, user_id: uuid.UUID) -> Recommendation | None:
        """
        Return the most recently generated recommendation for a user.

        The dashboard calls this instead of re-running the LLM.

        Args:
            user_id: Target user UUID.

        Returns:
            Most recent ``Recommendation`` row, or ``None`` if none exists.
        """
        return self._db.execute(
            select(Recommendation)
            .where(Recommendation.user_id == user_id)
            .order_by(Recommendation.generated_at.desc())
            .limit(1)
        ).scalars().first()

    def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        limit: int = 10,
    ) -> list[Recommendation]:
        """
        Return the *limit* most recent recommendations for a user.

        Useful for a history view or audit log.

        Args:
            user_id: Target user UUID.
            limit:   Maximum number of rows to return (default 10).

        Returns:
            List ordered newest-first.
        """
        return list(
            self._db.execute(
                select(Recommendation)
                .where(Recommendation.user_id == user_id)
                .order_by(Recommendation.generated_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
