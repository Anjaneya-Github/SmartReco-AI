"""
app/schemas/recommendation.py
-------------------------------
Pydantic v2 schemas for the recommendation generation pipeline.

GenerateRequest       — body for POST /recommendations/generate
RecommendedProduct    — a single product in the result list
RecommendationResult  — the full response (mirrors the DB row)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.schemas.common import AppBaseSchema


class GenerateRequest(AppBaseSchema):
    """
    Request body for POST /api/v1/recommendations/generate.

    Fields
    ~~~~~~
    user_id
        UUID of the user to generate recommendations for.
        Sent in the request body so an admin can trigger generation
        for any user (not just themselves).

    max_products
        How many candidate products to retrieve from the vector store
        and pass to the LLM.  Defaults to 20; LLM will pick the top 5.
    """

    user_id: uuid.UUID = Field(
        description="User to generate recommendations for.",
    )
    max_products: int = Field(
        default=20,
        ge=5,
        le=50,
        description="Number of candidate products to retrieve (5–50).",
    )


class RecommendedProduct(AppBaseSchema):
    """
    A single product returned in a recommendation result.

    Fields mirror the Product model but only carry what the dashboard
    needs — avoids loading the full product object from the DB.
    """

    product_id: uuid.UUID
    title: str
    category: str | None = None
    difficulty: str | None = None
    tags: list[str] = Field(default_factory=list)


class RecommendationResult(AppBaseSchema):
    """
    Full recommendation result returned by the API and stored in the DB.

    Fields
    ~~~~~~
    id                    UUID of the recommendation row
    user_id               User this recommendation belongs to
    summary               LLM-generated personalised intro story
    reasoning             LLM explanation of why these courses fit
    recommended_products  Ordered top-5 product summaries
    confidence            LLM self-reported confidence [0.0, 1.0]
    generated_at          When the LLM call completed
    """

    id: uuid.UUID
    user_id: uuid.UUID
    summary: str
    reasoning: str
    recommended_products: list[RecommendedProduct]
    confidence: float = Field(ge=0.0, le=1.0)
    generated_at: datetime

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, v: float) -> float:
        """Clamp to [0.0, 1.0] defensively — LLMs can drift."""
        return round(max(0.0, min(1.0, v)), 4)
