"""
app/services/workflow/nodes.py
--------------------------------
Every node in the recommendation LangGraph workflow.

Each node is a plain callable ``(state, deps) → partial_state``.
They are DB-free by design: all repository/service objects are
injected via the ``WorkflowDeps`` dataclass so nodes remain testable
in isolation without a running database.

Node catalogue
~~~~~~~~~~~~~~
load_profile          Build BehaviorProfile from the user's event history.
build_query           Translate the profile into a vector-search query string.
retrieve_products     Run vector similarity search; fall back to DB listing.
evaluate_quality      Decide if the retrieval set is "good" or "poor".
refine_query          Rewrite the query when quality is "poor".
generate_recommendation  Call the LLM and parse/validate the response.
validate_products     Strip hallucinated product IDs from the LLM output.
store_recommendation  Persist the final result to the database.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.repositories.product_repository import ProductRepository
from app.repositories.recommendation_repository import RecommendationRepository
from app.services.behavior_analyzer import BehaviorAnalyzer
from app.services.workflow.state import RecommendationState

logger = get_logger(__name__)

# ------------------------------------------------------------------ #
# Constants                                                           #
# ------------------------------------------------------------------ #

# Retrieval is "good" when we have at least this many candidates
_MIN_CANDIDATES = 3

# Maximum refinement attempts before forcing generation anyway
MAX_RETRIEVAL_ATTEMPTS = 2

# ------------------------------------------------------------------ #
# Prompt templates                                                    #
# ------------------------------------------------------------------ #

_SYSTEM_PROMPT = """\
You are an AI learning recommendation expert.
Your sole job is to recommend courses from the supplied product list.
NEVER invent, fabricate, or modify product details.
ALWAYS use the exact product_id values provided.
Respond ONLY with valid JSON — no markdown fences, no extra text.
"""

_USER_PROMPT_TEMPLATE = """\
## Behavior Profile
{profile}

## Available Products (use ONLY these)
{products}

## Task
Generate a personalised recommendation for this learner.

Respond with a JSON object that has EXACTLY these keys:
{{
  "summary":    "<1–2 sentence personalised story about the learner>",
  "reasoning":  "<2–3 sentences explaining why these specific courses fit>",
  "recommended_products": [
    {{"product_id": "<uuid>", "title": "<exact title from list>"}},
    ... (up to 5 items, ordered best-first)
  ],
  "confidence": <float between 0.0 and 1.0>
}}

Rules:
- Only include products from the provided list.
- Rank by relevance to the behavior profile.
- Return at most 5 products.
- confidence = 1.0 means you are certain; 0.0 means the profile is too thin.
"""

# ------------------------------------------------------------------ #
# Dependency container                                                #
# ------------------------------------------------------------------ #

@dataclass
class WorkflowDeps:
    """
    All external dependencies injected into workflow nodes.

    Keeping these in one place means nodes don't import ``get_db`` or
    global singletons — they receive everything they need at call time.
    """

    analyzer: BehaviorAnalyzer
    product_repo: ProductRepository
    rec_repo: RecommendationRepository
    db: Any                   # SQLAlchemy Session — only ``store`` node uses it


# ------------------------------------------------------------------ #
# Node: load_profile                                                  #
# ------------------------------------------------------------------ #

def load_profile(state: RecommendationState, deps: WorkflowDeps) -> dict:
    """
    Node 1 — Build the user's BehaviorProfile.

    Reads from EventRepository + ProductRepository via BehaviorAnalyzer.
    Serialises the profile to a plain dict so state stays JSON-safe.

    Returns:
        ``{"profile": <dict>}``
    """
    user_id: uuid.UUID = state["user_id"]
    logger.info("workflow:load_profile user_id=%s", user_id)

    profile = deps.analyzer.build_profile(user_id)

    return {
        "profile": {
            "primary_categories": profile.primary_categories,
            "favorite_tags":      profile.favorite_tags,
            "top_searches":       profile.top_searches,
            "search_frequency":   profile.search_frequency,
            "engagement_score":   profile.engagement_score,
            "learning_level":     profile.learning_level,
            "recent_activity_summary": profile.recent_activity_summary,
            "total_events_analysed":   profile.total_events_analysed,
            "last_active_at":     (
                profile.last_active_at.isoformat()
                if profile.last_active_at else None
            ),
        }
    }


# ------------------------------------------------------------------ #
# Node: build_query                                                   #
# ------------------------------------------------------------------ #

def build_query(state: RecommendationState, deps: WorkflowDeps) -> dict:
    """
    Node 2 — Translate the BehaviorProfile into a retrieval query string.

    The query is a pipe-delimited string of the user's top interests.
    Falls back to a generic query when the profile is empty.

    Returns:
        ``{"retrieval_query": <str>}``
    """
    profile: dict = state.get("profile") or {}
    logger.debug("workflow:build_query profile_keys=%s", list(profile.keys()))

    parts: list[str] = []

    cats = profile.get("primary_categories") or []
    if cats:
        parts.append("categories: " + ", ".join(cats[:3]))

    tags = profile.get("favorite_tags") or []
    if tags:
        parts.append("topics: " + ", ".join(tags[:5]))

    searches = profile.get("top_searches") or []
    if searches:
        parts.append("searches: " + ", ".join(searches[:3]))

    level = profile.get("learning_level", "unknown")
    if level and level != "unknown":
        parts.append(f"level: {level}")

    query = " | ".join(parts) if parts else "learning courses"
    logger.debug("workflow:build_query query=%r", query)

    return {"retrieval_query": query, "retrieval_attempts": 0}


# ------------------------------------------------------------------ #
# Node: retrieve_products                                             #
# ------------------------------------------------------------------ #

def retrieve_products(state: RecommendationState, deps: WorkflowDeps) -> dict:
    """
    Node 3 — Run vector similarity search for the retrieval query.

    Falls back to a DB listing when Qdrant is unavailable.
    Increments ``retrieval_attempts`` each time it runs.

    Returns:
        ``{"candidates": <dict pid→product_dict>, "retrieval_attempts": <int>}``
    """
    query: str = state.get("retrieval_query") or "learning courses"
    max_products: int = state.get("max_products") or 20
    attempts: int = (state.get("retrieval_attempts") or 0) + 1

    logger.info(
        "workflow:retrieve_products attempt=%d query=%r", attempts, query
    )

    product_map: dict[str, dict] = {}

    try:
        from app.services.embedding_service import EmbeddingService
        from app.services.vector_service import VectorService, _get_qdrant_client

        vector = EmbeddingService().embed_query(query)
        ids = VectorService(_get_qdrant_client()).search(vector, limit=max_products)

        if ids:
            products = deps.product_repo.get_by_ids(ids)
            product_map = {str(p.id): _product_to_dict(p) for p in products}
    except Exception as exc:
        logger.warning("workflow:retrieve_products vector search failed. error=%s", exc)

    # Fallback to DB listing if vector search returned nothing
    if not product_map:
        fallback, _ = deps.product_repo.list_active(limit=max_products)
        product_map = {str(p.id): _product_to_dict(p) for p in fallback}
        logger.info("workflow:retrieve_products using DB fallback. count=%d", len(product_map))

    return {
        "candidates": product_map,
        "retrieval_attempts": attempts,
    }


# ------------------------------------------------------------------ #
# Node: evaluate_quality                                              #
# ------------------------------------------------------------------ #

def evaluate_quality(state: RecommendationState, deps: WorkflowDeps) -> dict:
    """
    Node 4 — Decide whether the retrieval set is good enough.

    Criteria (all must pass):
    - At least MIN_CANDIDATES products returned.
    - At least one product category overlaps with the user's interests.

    Returns:
        ``{"retrieval_quality": "good" | "poor"}``
    """
    candidates: dict = state.get("candidates") or {}
    profile: dict = state.get("profile") or {}
    user_cats = set(profile.get("primary_categories") or [])
    user_tags = set(profile.get("favorite_tags") or [])

    if len(candidates) < _MIN_CANDIDATES:
        logger.debug("workflow:evaluate_quality poor — too few candidates (%d)", len(candidates))
        return {"retrieval_quality": "poor"}

    # Check overlap — if the profile has no interests yet, accept anything
    if not user_cats and not user_tags:
        return {"retrieval_quality": "good"}

    candidate_cats = {
        p.get("category") for p in candidates.values() if p.get("category")
    }
    candidate_tags: set[str] = set()
    for p in candidates.values():
        candidate_tags.update(p.get("tags") or [])

    overlap = bool(
        (user_cats & candidate_cats) or (user_tags & candidate_tags)
    )
    quality = "good" if overlap else "poor"
    logger.debug(
        "workflow:evaluate_quality quality=%s overlap=%s", quality, overlap
    )
    return {"retrieval_quality": quality}


# ------------------------------------------------------------------ #
# Node: refine_query                                                  #
# ------------------------------------------------------------------ #

def refine_query(state: RecommendationState, deps: WorkflowDeps) -> dict:
    """
    Node 5 (conditional) — Broaden the query when quality is "poor".

    Strategy: drop category filters, keep only the raw search terms and
    learning level.  This intentionally widens the retrieval net.

    Returns:
        ``{"retrieval_query": <str>}``
    """
    profile: dict = state.get("profile") or {}
    searches = profile.get("top_searches") or []
    level    = profile.get("learning_level", "unknown")

    parts: list[str] = []
    if searches:
        parts.append("topics: " + ", ".join(searches[:5]))
    if level and level != "unknown":
        parts.append(f"level: {level}")

    # Ultimate fallback when the profile is completely empty
    refined = " | ".join(parts) if parts else "popular online courses"
    logger.info("workflow:refine_query refined_query=%r", refined)

    return {"retrieval_query": refined}


# ------------------------------------------------------------------ #
# Node: generate_recommendation                                       #
# ------------------------------------------------------------------ #

def generate_recommendation(
    state: RecommendationState, deps: WorkflowDeps
) -> dict:
    """
    Node 6 — Call the Mesh/OpenAI-compatible LLM and capture raw output.

    Uses ``settings.LLM_BASE_URL`` and ``settings.LLM_API_KEY`` so all
    calls are routed through the configured provider (Mesh API).

    Returns:
        ``{"llm_raw": <str>}`` on success.
        ``{"error": <str>}`` on LLM failure — downstream nodes handle it.
    """
    profile: dict     = state.get("profile") or {}
    candidates: dict  = state.get("candidates") or {}

    if not candidates:
        return {"error": "no_candidates"}

    # Format prompt
    profile_text = (
        f"Categories: {', '.join(profile.get('primary_categories') or []) or 'none'}\n"
        f"Tags: {', '.join(profile.get('favorite_tags') or []) or 'none'}\n"
        f"Searches: {', '.join(profile.get('top_searches') or []) or 'none'}\n"
        f"Engagement score: {profile.get('engagement_score', 0.0):.2f}\n"
        f"Learning level: {profile.get('learning_level', 'unknown')}\n"
        f"Recent activity: {profile.get('recent_activity_summary', 'none')}"
    )

    products_text = "\n".join(
        f"- id: {pid} | title: {p.get('title', '')} "
        f"| category: {p.get('category') or 'n/a'} "
        f"| difficulty: {p.get('difficulty') or 'n/a'} "
        f"| tags: {', '.join(p.get('tags') or [])}"
        for pid, p in candidates.items()
    )

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        profile=profile_text,
        products=products_text,
    )

    logger.info(
        "workflow:generate_recommendation calling LLM. model=%s candidates=%d",
        settings.LLM_MODEL,
        len(candidates),
    )

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.LLM_API_KEY or "no-key",
            base_url=settings.LLM_BASE_URL or None,
        )
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=1024,
        )
        raw = response.choices[0].message.content or ""
        logger.debug("workflow:generate_recommendation raw_len=%d", len(raw))
        return {"llm_raw": raw}

    except Exception as exc:
        logger.error("workflow:generate_recommendation LLM call failed. error=%s", exc)
        return {"error": f"llm_error:{exc}"}


# ------------------------------------------------------------------ #
# Node: validate_products                                             #
# ------------------------------------------------------------------ #

def validate_products(
    state: RecommendationState, deps: WorkflowDeps
) -> dict:
    """
    Node 7 — Parse the LLM JSON and strip any hallucinated product IDs.

    This is the safety gate: the LLM is instructed never to invent IDs,
    but we verify every ID against the ``candidates`` dict anyway.

    Returns:
        ``{"parsed": <dict>}`` with validated product list and confidence.
    """
    raw: str          = state.get("llm_raw") or ""
    candidates: dict  = state.get("candidates") or {}

    # Strip markdown fences if the model added them despite instructions
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(
            ln for ln in lines if not ln.strip().startswith("```")
        ).strip()

    try:
        data: dict = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error(
            "workflow:validate_products JSON parse failed. raw=%r error=%s",
            raw[:300], exc,
        )
        # Fall back to top-N from candidates list
        data = {}

    # Validate and filter product IDs
    valid: list[dict] = []
    for item in data.get("recommended_products") or []:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("product_id", ""))
        if pid in candidates:
            valid.append({
                "product_id": pid,
                "title": item.get("title") or candidates[pid].get("title", ""),
            })
        else:
            logger.warning(
                "workflow:validate_products hallucinated product_id=%r — dropped", pid
            )

    # If LLM hallucinated every ID, fall back to top candidates
    if not valid and candidates:
        logger.warning(
            "workflow:validate_products no valid IDs from LLM — using top candidates"
        )
        valid = [
            {"product_id": pid, "title": p.get("title", "")}
            for pid, p in list(candidates.items())[:5]
        ]

    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = round(max(0.0, min(1.0, confidence)), 4)

    # Penalise if we had to fall back
    if not data.get("recommended_products"):
        confidence = min(confidence, 0.3)

    parsed = {
        "summary":               str(data.get("summary", ""))[:2000],
        "reasoning":             str(data.get("reasoning", ""))[:2000],
        "recommended_products":  valid[:5],
        "confidence":            confidence,
    }

    logger.info(
        "workflow:validate_products valid_products=%d confidence=%.4f",
        len(valid), confidence,
    )
    return {"parsed": parsed}


# ------------------------------------------------------------------ #
# Node: store_recommendation                                          #
# ------------------------------------------------------------------ #

def store_recommendation(
    state: RecommendationState, deps: WorkflowDeps
) -> dict:
    """
    Node 8 — Persist the recommendation to the database.

    Handles both the happy path (``parsed`` is set) and error fallback
    (``error`` is set from an upstream failure).

    Commits the transaction — this is the only node that writes to the DB.

    Returns:
        ``{"result": <recommendation dict>}``
    """
    user_id: uuid.UUID = state["user_id"]
    parsed: dict       = state.get("parsed") or {}
    error: str | None  = state.get("error")
    candidates: dict   = state.get("candidates") or {}

    if error or not parsed:
        # Graceful degradation — store a low-confidence fallback
        logger.warning(
            "workflow:store_recommendation using fallback. user_id=%s error=%s",
            user_id, error,
        )
        top_products = [
            {"product_id": pid, "title": p.get("title", "")}
            for pid, p in list(candidates.items())[:5]
        ]
        summary = (
            "We encountered a temporary issue generating your personalised feed. "
            "Here are some courses you might enjoy."
        )
        reasoning = error or "Recommendation generation failed."
        confidence = 0.05
    else:
        top_products = parsed.get("recommended_products", [])
        summary      = parsed.get("summary", "")
        reasoning    = parsed.get("reasoning", "")
        confidence   = parsed.get("confidence", 0.5)

    rec = deps.rec_repo.create(
        user_id=user_id,
        summary=summary,
        reasoning=reasoning,
        recommended_products=top_products,
        confidence=confidence,
    )
    deps.db.commit()

    logger.info(
        "workflow:store_recommendation persisted. id=%s user_id=%s confidence=%.4f",
        rec.id, user_id, rec.confidence,
    )

    # Re-hydrate product details for the response
    pid_list = [
        uuid.UUID(p["product_id"]) for p in top_products if p.get("product_id")
    ]
    product_orm = deps.product_repo.get_by_ids(pid_list)
    product_map = {str(p.id): p for p in product_orm}

    reco_products = []
    for item in top_products:
        pid = item.get("product_id", "")
        orm_p = product_map.get(pid)
        reco_products.append({
            "product_id": pid,
            "title":      orm_p.title      if orm_p else item.get("title", ""),
            "category":   orm_p.category   if orm_p else None,
            "difficulty": orm_p.difficulty if orm_p else None,
            "tags":       orm_p.tags       if orm_p else [],
        })

    result = {
        "id":                    str(rec.id),
        "user_id":               str(rec.user_id),
        "summary":               rec.summary,
        "reasoning":             rec.reasoning,
        "recommended_products":  reco_products,
        "confidence":            rec.confidence,
        "generated_at":          rec.generated_at.isoformat(),
    }

    return {"result": result}


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _product_to_dict(p: Any) -> dict:
    """Serialise a Product ORM object to a plain dict for the state bag."""
    return {
        "title":      p.title,
        "category":   p.category,
        "difficulty": p.difficulty,
        "tags":       list(p.tags or []),
        "is_active":  p.is_active,
    }
