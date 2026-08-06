"""
app/services/vector_service.py
--------------------------------
Qdrant integration — manages the product vector collection and all
point-level CRUD operations.

Client modes (controlled by VECTOR_MODE in .env)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  qdrant  → connects to a real Qdrant server at QDRANT_URL.
            This is the default and the only mode suitable for
            staging and production.  Data persists across restarts.

  memory  → in-process Qdrant backed by a plain Python dict.
            Zero external dependencies; useful for local dev or CI
            when Docker isn't available.  Data is lost on restart.
            Never use in production.

Dual-write contract
~~~~~~~~~~~~~~~~~~~
On Qdrant failure the caller is responsible for rolling back the
SQL transaction — this service never touches the DB directly.
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any, Literal

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


# ------------------------------------------------------------------ #
# Client factory                                                      #
# ------------------------------------------------------------------ #

@lru_cache(maxsize=1)
def _get_qdrant_client() -> QdrantClient:
    """
    Build and cache the QdrantClient singleton for the process lifetime.

    The client is chosen based on ``settings.VECTOR_MODE``:

    - ``"qdrant"``  → HTTP client pointed at ``QDRANT_URL``.
                      Uses ``QDRANT_API_KEY`` when set (Qdrant Cloud).
    - ``"memory"``  → In-process client; no server required.
                      Logs a prominent warning so the mode is visible.

    This is the *only* place in the codebase that reads ``VECTOR_MODE``.
    """
    mode: str = settings.VECTOR_MODE

    if mode == "memory":
        logger.warning(
            "⚠  Qdrant running in IN-MEMORY mode (VECTOR_MODE=memory). "
            "Data will be lost on restart. NOT for production."
        )
        return QdrantClient(location=":memory:")

    # Default: real Qdrant server
    kwargs: dict[str, Any] = {"url": settings.QDRANT_URL}
    if settings.QDRANT_API_KEY:
        kwargs["api_key"] = settings.QDRANT_API_KEY

    client = QdrantClient(**kwargs)
    logger.info(
        "Qdrant client initialised. mode=qdrant url=%s",
        settings.QDRANT_URL,
    )
    return client


# ------------------------------------------------------------------ #
# Service                                                             #
# ------------------------------------------------------------------ #

class VectorService:
    """
    Manages product vectors in Qdrant.

    Args:
        client: Injected ``QdrantClient`` (use ``get_vector_service()``).
    """

    def __init__(self, client: QdrantClient) -> None:
        self._client = client
        self._collection = settings.QDRANT_COLLECTION

    # ------------------------------------------------------------------ #
    # Collection management                                               #
    # ------------------------------------------------------------------ #

    def ensure_collection(self) -> None:
        """
        Create the products collection if it does not already exist.

        Safe to call multiple times (idempotent).
        Called once during application lifespan startup and lazily
        before the first upsert so the service is self-bootstrapping
        in test contexts where the lifespan is not triggered.
        """
        existing = {c.name for c in self._client.get_collections().collections}

        if self._collection in existing:
            logger.debug(
                "Qdrant collection already exists. name=%s", self._collection
            )
            return

        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=qmodels.VectorParams(
                size=settings.EMBEDDING_DIMENSION,
                distance=qmodels.Distance.COSINE,
                on_disk=False,  # keep in RAM for low-latency retrieval
            ),
        )
        logger.info(
            "Qdrant collection created. name=%s dim=%d",
            self._collection,
            settings.EMBEDDING_DIMENSION,
        )

    # ------------------------------------------------------------------ #
    # Point CRUD                                                          #
    # ------------------------------------------------------------------ #

    def upsert(
        self,
        product_id: uuid.UUID,
        vector: list[float],
        payload: dict[str, Any],
    ) -> None:
        """
        Insert or replace a product vector point.

        Calls ``ensure_collection()`` first so the service is
        self-bootstrapping in any execution context (live server,
        in-process test transport, management scripts).

        Args:
            product_id: UUID used as the Qdrant point ID.
            vector:     Dense embedding (length must equal EMBEDDING_DIMENSION).
            payload:    Metadata stored alongside the vector.

        Raises:
            Exception: Propagates any Qdrant error to the caller so the
                       ``ProductService`` can roll back the SQL transaction.
        """
        self.ensure_collection()  # no-op if collection already exists

        point = qmodels.PointStruct(
            id=str(product_id),
            vector=vector,
            payload=payload,
        )
        self._client.upsert(
            collection_name=self._collection,
            points=[point],
            wait=True,  # synchronous — wait for indexing before returning
        )
        logger.debug("Qdrant upsert OK. product_id=%s", product_id)

    def delete(self, product_id: uuid.UUID) -> None:
        """
        Remove a product vector point from the collection.

        Silently succeeds if the point does not exist (idempotent).

        Args:
            product_id: UUID of the product to remove.

        Raises:
            Exception: Propagates any Qdrant error to the caller.
        """
        self._client.delete(
            collection_name=self._collection,
            points_selector=qmodels.PointIdsList(
                points=[str(product_id)]
            ),
            wait=True,
        )
        logger.debug("Qdrant delete OK. product_id=%s", product_id)

    def search(
        self,
        vector: list[float],
        limit: int = 20,
        score_threshold: float = 0.0,
    ) -> list[uuid.UUID]:
        """
        Find the *limit* most similar product vectors by cosine similarity.

        Args:
            vector:          Query embedding (length must equal EMBEDDING_DIMENSION).
            limit:           Maximum number of results to return.
            score_threshold: Minimum cosine similarity score (0.0 = no filter).

        Returns:
            Ordered list of product UUIDs, best-match first.
            Returns an empty list if the collection is empty.
        """
        try:
            results = self._client.search(
                collection_name=self._collection,
                query_vector=vector,
                limit=limit,
                score_threshold=score_threshold if score_threshold > 0.0 else None,
                with_payload=False,   # we only need the IDs
                with_vectors=False,
            )
            ids = [uuid.UUID(str(hit.id)) for hit in results]
            logger.debug(
                "Qdrant search returned %d results. limit=%d", len(ids), limit
            )
            return ids
        except Exception as exc:
            logger.warning("Qdrant search failed. error=%s", exc)
            return []


# ------------------------------------------------------------------ #
# FastAPI dependency                                                  #
# ------------------------------------------------------------------ #

def get_vector_service() -> VectorService:
    """
    FastAPI dependency — returns a ``VectorService`` backed by the
    cached ``QdrantClient`` singleton.

    Usage in a route::

        @router.post("/products")
        def create(
            payload: CreateProductRequest,
            vector_svc: VectorService = Depends(get_vector_service),
        ):
            ...
    """
    return VectorService(_get_qdrant_client())
