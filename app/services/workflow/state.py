"""
app/services/workflow/state.py
--------------------------------
LangGraph state definition for the recommendation workflow.

Every node in the graph receives the full ``RecommendationState`` dict
and returns a partial dict with only the keys it mutated.  LangGraph
merges the returned partial back into the running state automatically.

Design rules
~~~~~~~~~~~~
- Keep all fields Optional so nodes can be skipped cleanly.
- Use plain Python types — no ORM objects here (they can't be pickled
  by LangGraph's checkpointer if one is added later).
- ``retrieval_attempts`` drives the refinement loop guard so we never
  spin more than MAX_RETRIEVAL_ATTEMPTS times.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from typing_extensions import TypedDict


class RecommendationState(TypedDict, total=False):
    """
    Mutable state bag that flows through every graph node.

    Fields
    ~~~~~~
    user_id
        UUID of the user being processed.  Set at graph entry.

    max_products
        How many candidates to retrieve.  Set at graph entry.

    profile
        ``BehaviorProfile`` schema — populated by ``load_profile`` node.
        Serialised as a dict to keep state JSON-serialisable.

    retrieval_query
        Free-text query string used for vector similarity search.
        Built by ``build_query`` node; rewritten by ``refine_query`` node.

    candidates
        Dict mapping product UUID str → product detail dict.
        Populated by ``retrieve_products`` node.

    retrieval_attempts
        Counter incremented each time ``retrieve_products`` runs.
        Guards the refinement loop.

    retrieval_quality
        ``"good"`` or ``"poor"`` — set by ``evaluate_quality`` node.

    llm_raw
        Raw string from the LLM — stored for debugging.

    parsed
        Dict with keys: summary, reasoning, recommended_products, confidence.
        Set by ``generate_recommendation`` node after LLM + validation.

    result
        Final ``RecommendationResult`` schema dict — set by ``store`` node.

    error
        If set, an upstream node encountered a non-recoverable error.
        The ``store`` node checks this and persists a fallback row.
    """

    user_id: uuid.UUID
    max_products: int

    # ---- behavior layer ----
    profile: Optional[dict[str, Any]]

    # ---- retrieval layer ----
    retrieval_query: Optional[str]
    candidates: Optional[dict[str, Any]]           # pid_str → product dict
    retrieval_attempts: int
    retrieval_quality: Optional[str]               # "good" | "poor"

    # ---- generation layer ----
    llm_raw: Optional[str]
    parsed: Optional[dict[str, Any]]

    # ---- output ----
    result: Optional[dict[str, Any]]
    error: Optional[str]
