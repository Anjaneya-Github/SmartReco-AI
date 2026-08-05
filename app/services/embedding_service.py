"""
app/services/embedding_service.py
-----------------------------------
Generates dense vector embeddings using sentence-transformers.

Model: BAAI/bge-small-en-v1.5
  - Dimension  : 384
  - Max tokens : 512
  - Optimised for semantic search / retrieval tasks

The model is loaded once at module import time (lazy on first call)
and reused across all requests — loading takes ~1-2 s and ~100 MB RAM.

BGE models benefit from a query prefix when encoding search queries
vs. when encoding documents.  We expose both modes explicitly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from app.core.config import settings
from app.core.logging import get_logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _get_model() -> "SentenceTransformer":
    """
    Load and cache the sentence-transformer model.

    Called lazily on first use so the application starts fast even if
    the model isn't needed on every request (e.g. health checks).
    """
    from sentence_transformers import SentenceTransformer

    logger.info("Loading embedding model: %s", settings.EMBEDDING_MODEL)
    model = SentenceTransformer(settings.EMBEDDING_MODEL)
    logger.info("Embedding model loaded. dimension=%d", settings.EMBEDDING_DIMENSION)
    return model


class EmbeddingService:
    """
    Wraps sentence-transformers for document and query embedding.

    Usage::

        svc = EmbeddingService()
        vector = svc.embed_document("Python for beginners")
        # → list[float] of length 384
    """

    # ------------------------------------------------------------------ #
    # Document embedding (used when indexing products)                    #
    # ------------------------------------------------------------------ #

    def embed_document(self, text: str) -> list[float]:
        """
        Embed a product document for indexing.

        BGE models recommend **no** special prefix for passages.

        Args:
            text: Combined product text (title + description + tags, etc.).

        Returns:
            Unit-normalised dense vector as ``list[float]``.
        """
        return self._encode(text)

    # ------------------------------------------------------------------ #
    # Query embedding (used when performing similarity search)            #
    # ------------------------------------------------------------------ #

    def embed_query(self, query: str) -> list[float]:
        """
        Embed a user search query for retrieval.

        BGE models recommend prefixing queries with
        ``"Represent this sentence: "`` for best retrieval quality.

        Args:
            query: Free-text search query from the user.

        Returns:
            Unit-normalised dense vector as ``list[float]``.
        """
        return self._encode(f"Represent this sentence: {query}")

    # ------------------------------------------------------------------ #
    # Internal                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _encode(text: str) -> list[float]:
        """Encode *text* to a unit-normalised vector."""
        model = _get_model()
        vector = model.encode(
            text,
            normalize_embeddings=True,   # cosine similarity via dot product
            show_progress_bar=False,
        )
        return vector.tolist()

    @staticmethod
    def build_document_text(
        title: str,
        description: str | None,
        category: str | None,
        difficulty: str | None,
        tags: list[str],
    ) -> str:
        """
        Concatenate product fields into a single string for embedding.

        The field order and weighting (repetition) is tuned for
        retrieval quality: title appears first and category/tags at the
        end so the model pays most attention to the most discriminative
        parts of a product description.

        Args:
            title:       Product title.
            description: Long-form description (may be None).
            category:    Category slug (may be None).
            difficulty:  Difficulty level (may be None).
            tags:        List of tag strings.

        Returns:
            Single concatenated string ready for ``embed_document``.
        """
        parts: list[str] = [title]

        if description:
            parts.append(description)
        if category:
            parts.append(f"Category: {category}")
        if difficulty:
            parts.append(f"Difficulty: {difficulty}")
        if tags:
            parts.append("Tags: " + ", ".join(tags))

        return " | ".join(parts)
