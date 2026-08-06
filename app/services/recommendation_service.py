"""
app/services/recommendation_service.py
----------------------------------------
Thin orchestrator that drives the LangGraph recommendation workflow.

Responsibility
~~~~~~~~~~~~~~
This service owns three things:

1.  ``generate(user_id, max_products)``
    - Fast-path guard for thin profiles (< 3 events) and empty catalogues.
    - Builds ``WorkflowDeps`` and invokes the compiled LangGraph graph.
    - Converts the final state dict to a ``RecommendationResult`` schema.

2.  ``get_latest(user_id)``
    - Reads the most recent cached result from the DB (no LLM call).
    - Used by the dashboard / GET /me endpoint.

3.  ``should_generate(user_id) → TriggerStatus``
    - Evaluates the four trigger rules and returns whether a new
      recommendation run is warranted.
    - Called by the event router after batch ingest so recommendations
      are generated reactively, not on every request.

Architecture
~~~~~~~~~~~~
Router → RecommendationService → LangGraph workflow → {nodes}
                               → RecommendationTrigger (for should_generate)
                               → RecommendationRepository (for get_latest)

The graph is built fresh per call — it's cheap (no I/O) and avoids
shared mutable state across requests.

Mesh API note
~~~~~~~~~~~~~
All LLM calls route through the Mesh API because the OpenAI client
is constructed in ``nodes.py`` using:

    OpenAI(
        api_key=settings.LLM_API_KEY,   # MESH_API_KEY value
        base_url=settings.LLM_BASE_URL, # https://api.meshapi.ai/v1
    )

Set LLM_BASE_URL=https://api.meshapi.ai/v1 and LLM_API_KEY=<mesh_key>
in .env to activate Mesh routing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories.event_repository import EventRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.recommendation_repository import RecommendationRepository
from app.repositories.user_repository import UserRepository
from app.schemas.behavior import TriggerStatus
from app.schemas.recommendation import RecommendedProduct, RecommendationResult
from app.services.behavior_analyzer import BehaviorAnalyzer
from app.services.workflow.graph import build_graph
from app.services.workflow.nodes import WorkflowDeps

logger = get_logger(__name__)

# Minimum events for a meaningful LLM run
_MIN_EVENTS_FOR_LLM = 3


class RecommendationService:
    """
    Entry-point for all recommendation operations.

    Args:
        db: SQLAlchemy session injected per request.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._user_repo    = UserRepository(db)
        self._product_repo = ProductRepository(db)
        self._rec_repo     = RecommendationRepository(db)
        self._event_repo   = EventRepository(db)

    # ------------------------------------------------------------------ #
    # Generate                                                            #
    # ------------------------------------------------------------------ #

    def generate(
        self,
        user_id: uuid.UUID,
        max_products: int = 20,
    ) -> RecommendationResult:
        """
        Run the LangGraph recommendation workflow and persist the result.

        Args:
            user_id:      Target user UUID.
            max_products: Candidate pool size passed to the retrieval node.

        Returns:
            Fully populated ``RecommendationResult``.

        Raises:
            NotFoundException: User does not exist.
        """
        # Validate user
        user = self._user_repo.get_by_id(user_id)
        if user is None:
            from app.core.exceptions import NotFoundException
            raise NotFoundException(f"User {user_id} not found.")

        # Fast-path: too few events — skip the whole graph
        event_count = len(
            self._event_repo.get_recent_events(user_id, limit=_MIN_EVENTS_FOR_LLM)
        )
        if event_count < _MIN_EVENTS_FOR_LLM:
            logger.info(
                "generate:thin_profile user_id=%s events=%d", user_id, event_count
            )
            return self._thin_profile_result(user_id)

        # Fast-path: empty catalogue
        _, total_products = self._product_repo.list_active(limit=1)
        if total_products == 0:
            return self._no_products_result(user_id)

        # Build deps and run the workflow graph
        deps = WorkflowDeps(
            analyzer=BehaviorAnalyzer(self._db),
            product_repo=self._product_repo,
            rec_repo=self._rec_repo,
            db=self._db,
        )
        compiled = build_graph(deps)

        initial_state = {
            "user_id":           user_id,
            "max_products":      max_products,
            "retrieval_attempts": 0,
        }

        logger.info(
            "generate:workflow_start user_id=%s max_products=%d",
            user_id, max_products,
        )

        final_state = compiled.invoke(initial_state)

        result_dict: dict | None = final_state.get("result")
        if not result_dict:
            # Graph encountered an unrecoverable error and stored a fallback
            result_dict = final_state.get("result") or {}

        return self._dict_to_result(result_dict)

    # ------------------------------------------------------------------ #
    # Read cached result                                                  #
    # ------------------------------------------------------------------ #

    def get_latest(self, user_id: uuid.UUID) -> RecommendationResult | None:
        """
        Return the most recent cached recommendation for a user.

        Reads from the DB — no LLM call.  Used by GET /recommendations/me.

        Args:
            user_id: Target user UUID.

        Returns:
            Most recent ``RecommendationResult``, or ``None``.
        """
        rec = self._rec_repo.get_latest_for_user(user_id)
        if rec is None:
            return None

        product_ids = [
            uuid.UUID(p["product_id"]) if isinstance(p, dict) else uuid.UUID(str(p))
            for p in rec.recommended_products
        ]
        products = self._product_repo.get_by_ids(product_ids)
        product_map = {str(p.id): p for p in products}

        return self._orm_to_result(rec, product_map)

    # ------------------------------------------------------------------ #
    # Trigger evaluation                                                  #
    # ------------------------------------------------------------------ #

    def should_generate(self, user_id: uuid.UUID) -> TriggerStatus:
        """
        Evaluate trigger rules and return whether a new generation is warranted.

        Called by the event router after batch ingest to decide whether to
        kick off a recommendation run reactively.

        Rules evaluated (OR-logic — any one firing triggers generation):
          1. 20+ new events since last recommendation
          2. Repeated search query in the event window
          3. Purchase or wishlist event present
          4. User inactive for 10+ minutes

        Args:
            user_id: Target user UUID.

        Returns:
            ``TriggerStatus`` with ``should_trigger`` and ``rules_evaluated``.
        """
        from app.services.recommendation_trigger import RecommendationTrigger

        events = self._event_repo.get_recent_events(user_id, limit=200)
        last_rec = self._rec_repo.get_latest_for_user(user_id)

        last_generated_at = last_rec.generated_at if last_rec else None
        # Ensure tz-aware
        if last_generated_at and last_generated_at.tzinfo is None:
            last_generated_at = last_generated_at.replace(tzinfo=timezone.utc)

        # Count events since last recommendation (rule 1)
        events_since_last = (
            sum(1 for e in events if last_generated_at is None or (
                (e.created_at.replace(tzinfo=timezone.utc)
                 if e.created_at.tzinfo is None
                 else e.created_at) > last_generated_at
            ))
        )

        last_event_at = events[0].created_at if events else None

        trigger = RecommendationTrigger(
            events=events,
            events_since_last_reco=events_since_last,
            last_active_at=last_event_at,
        )
        return trigger.evaluate()

    # ------------------------------------------------------------------ #
    # Fast-path helpers                                                   #
    # ------------------------------------------------------------------ #

    def _thin_profile_result(self, user_id: uuid.UUID) -> RecommendationResult:
        """Persist and return a low-confidence result for thin profiles."""
        products_list, _ = self._product_repo.list_active(limit=5)
        recs = [{"product_id": str(p.id), "title": p.title} for p in products_list]

        rec = self._rec_repo.create(
            user_id=user_id,
            summary=(
                "We don't have enough activity data yet to personalise your feed. "
                "Here are some popular courses to get you started."
            ),
            reasoning=(
                "These are our top courses across all categories. "
                "Interact with more content for personalised recommendations."
            ),
            recommended_products=recs,
            confidence=0.1,
        )
        self._db.commit()

        product_map = {str(p.id): p for p in products_list}
        return self._orm_to_result(rec, product_map)

    def _no_products_result(self, user_id: uuid.UUID) -> RecommendationResult:
        """Persist and return an empty result when the catalogue is empty."""
        rec = self._rec_repo.create(
            user_id=user_id,
            summary="No products are currently available in the catalogue.",
            reasoning="The product catalogue is empty. Please add products first.",
            recommended_products=[],
            confidence=0.0,
        )
        self._db.commit()
        return self._orm_to_result(rec, {})

    # ------------------------------------------------------------------ #
    # Schema conversion                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _orm_to_result(rec: Any, product_map: dict) -> RecommendationResult:
        """Convert an ORM ``Recommendation`` + product map to a schema."""
        products_out: list[RecommendedProduct] = []
        for item in rec.recommended_products:
            pid = str(item.get("product_id", "")) if isinstance(item, dict) else str(item)
            p = product_map.get(pid)
            products_out.append(RecommendedProduct(
                product_id=uuid.UUID(pid) if pid else uuid.uuid4(),
                title=(p.title if p else (item.get("title", "Unknown") if isinstance(item, dict) else "Unknown")),
                category=p.category if p else None,
                difficulty=p.difficulty if p else None,
                tags=p.tags if p else [],
            ))

        return RecommendationResult(
            id=rec.id,
            user_id=rec.user_id,
            summary=rec.summary,
            reasoning=rec.reasoning,
            recommended_products=products_out,
            confidence=rec.confidence,
            generated_at=rec.generated_at,
        )

    @staticmethod
    def _dict_to_result(d: dict) -> RecommendationResult:
        """Convert a ``result`` state dict (from the graph) to a schema."""
        products_out = [
            RecommendedProduct(
                product_id=uuid.UUID(str(p.get("product_id", uuid.uuid4()))),
                title=p.get("title", ""),
                category=p.get("category"),
                difficulty=p.get("difficulty"),
                tags=p.get("tags") or [],
            )
            for p in (d.get("recommended_products") or [])
        ]

        generated_at = d.get("generated_at")
        if isinstance(generated_at, str):
            generated_at = datetime.fromisoformat(generated_at)
        elif generated_at is None:
            generated_at = datetime.now(tz=timezone.utc)

        return RecommendationResult(
            id=uuid.UUID(str(d.get("id", uuid.uuid4()))),
            user_id=uuid.UUID(str(d.get("user_id", uuid.uuid4()))),
            summary=d.get("summary", ""),
            reasoning=d.get("reasoning", ""),
            recommended_products=products_out,
            confidence=float(d.get("confidence", 0.0)),
            generated_at=generated_at,
        )
