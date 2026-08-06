"""
app/services/workflow/graph.py
--------------------------------
Assembles and compiles the recommendation LangGraph workflow.

Graph topology
~~~~~~~~~~~~~~

    START
      │
      ▼
    load_profile
      │
      ▼
    build_query
      │
      ▼
    retrieve_products ◄──────────────────────────────┐
      │                                               │
      ▼                                               │
    evaluate_quality                                  │
      │                                               │
      ├── "good" ──────────────────────────────────►  │  (skips refinement)
      │                                               │
      └── "poor" ──► refine_query ──────────────────►─┘
                     (only if attempts < MAX)
                     else falls through to generate

      ▼
    generate_recommendation
      │
      ▼
    validate_products
      │
      ▼
    store_recommendation
      │
      ▼
    END

Conditional edges
~~~~~~~~~~~~~~~~~
``_route_after_quality``
    Called after ``evaluate_quality``.
    - "good"            → ``generate_recommendation``
    - "poor" + attempts < MAX_RETRIEVAL_ATTEMPTS → ``refine_query``
    - "poor" + exhausted → ``generate_recommendation`` (best-effort)

The graph is compiled once at module import and reused across requests.
Inject ``WorkflowDeps`` into each node via ``functools.partial`` before
handing the graph to LangGraph — this keeps nodes stateless.
"""

from __future__ import annotations

import functools
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from app.services.workflow.nodes import (
    MAX_RETRIEVAL_ATTEMPTS,
    WorkflowDeps,
    build_query,
    evaluate_quality,
    generate_recommendation,
    load_profile,
    refine_query,
    retrieve_products,
    store_recommendation,
    validate_products,
)
from app.services.workflow.state import RecommendationState


# ------------------------------------------------------------------ #
# Routing logic                                                       #
# ------------------------------------------------------------------ #

def _route_after_quality(state: RecommendationState) -> str:
    """
    Decide the next node after ``evaluate_quality``.

    Returns:
        Node name string consumed by LangGraph's conditional_edges.
    """
    quality:  str = state.get("retrieval_quality") or "poor"
    attempts: int = state.get("retrieval_attempts") or 0

    if quality == "good":
        return "generate_recommendation"

    if attempts < MAX_RETRIEVAL_ATTEMPTS:
        return "refine_query"

    # Retrieval is still poor but we've exhausted retries — generate anyway
    return "generate_recommendation"


# ------------------------------------------------------------------ #
# Graph factory                                                       #
# ------------------------------------------------------------------ #

def build_graph(deps: WorkflowDeps) -> Any:
    """
    Construct and compile the recommendation workflow graph.

    Each node is wrapped with ``functools.partial`` to inject ``deps``,
    producing a unary ``(state) → partial_state`` callable as LangGraph
    expects.

    Args:
        deps: ``WorkflowDeps`` instance containing all injected services.

    Returns:
        A compiled ``CompiledGraph`` ready to invoke with an initial state.
    """
    def _bind(fn: Callable) -> Callable:
        """Bind deps as the second positional argument."""
        return functools.partial(fn, deps=deps)

    graph = StateGraph(RecommendationState)

    # ---- Register nodes ----
    graph.add_node("load_profile",              _bind(load_profile))
    graph.add_node("build_query",               _bind(build_query))
    graph.add_node("retrieve_products",         _bind(retrieve_products))
    graph.add_node("evaluate_quality",          _bind(evaluate_quality))
    graph.add_node("refine_query",              _bind(refine_query))
    graph.add_node("generate_recommendation",   _bind(generate_recommendation))
    graph.add_node("validate_products",         _bind(validate_products))
    graph.add_node("store_recommendation",      _bind(store_recommendation))

    # ---- Static edges ----
    graph.add_edge(START,                   "load_profile")
    graph.add_edge("load_profile",          "build_query")
    graph.add_edge("build_query",           "retrieve_products")
    graph.add_edge("retrieve_products",     "evaluate_quality")

    # ---- Conditional edges (retrieval loop) ----
    graph.add_conditional_edges(
        "evaluate_quality",
        _route_after_quality,
        {
            "refine_query":           "refine_query",
            "generate_recommendation": "generate_recommendation",
        },
    )

    # refine_query loops back to retrieve
    graph.add_edge("refine_query",          "retrieve_products")

    # ---- Generation path ----
    graph.add_edge("generate_recommendation", "validate_products")
    graph.add_edge("validate_products",       "store_recommendation")
    graph.add_edge("store_recommendation",    END)

    return graph.compile()
