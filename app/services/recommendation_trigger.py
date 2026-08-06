"""
app/services/recommendation_trigger.py
----------------------------------------
Stateless trigger evaluator — answers: should we generate a new
recommendation for this user right now?

Responsibility
~~~~~~~~~~~~~~
Evaluate four independent rules against the user's current event state.
Any single rule firing is sufficient (OR-logic).  All rule results are
returned in ``TriggerStatus.rules_evaluated`` for observability.

Rules
~~~~~
1. ``new_events_threshold``
   ≥ 20 new events have arrived since the last recommendation was generated.
   Prevents the LLM from running on every single event while still
   catching meaningful accumulations of activity.

2. ``repeated_search``
   The user has submitted the same search query more than once in the
   analysis window.  Repeated searches signal unfulfilled intent — the
   user is looking for something and hasn't found it yet.

3. ``purchase_or_wishlist``
   The user has at least one PURCHASE or WISHLIST event in the window.
   These are the strongest intent signals and should always trigger
   a fresh recommendation.

4. ``inactivity_reengagement``
   The user was previously active but has been silent for ≥ 10 minutes.
   Used for re-engagement: surface something new to bring them back.

Design notes
~~~~~~~~~~~~
- DB-free: all inputs are plain Python objects (events list + scalars).
- All thresholds are configurable at construction for A/B testing.
- Adding a new rule is a one-method addition; ``evaluate()`` collects them
  automatically via the ``_RULES`` list.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from app.models.event import EventType, UserEvent
from app.schemas.behavior import TriggerStatus
from app.services.interest_extractor import InterestExtractor

# ------------------------------------------------------------------ #
# Default thresholds (override at construction time for tests / A/B) #
# ------------------------------------------------------------------ #
_DEFAULT_NEW_EVENTS_THRESHOLD  = 20
_DEFAULT_INACTIVITY_MINUTES    = 10


class RecommendationTrigger:
    """
    Evaluates trigger rules and returns a ``TriggerStatus``.

    Args:
        events:                 Recent events for the user (analysis window).
        events_since_last_reco: Count of new events since the last rec was generated.
        last_active_at:         Timestamp of the user's most recent event, or None.
        new_events_threshold:   Rule-1 threshold (default 20).
        inactivity_minutes:     Rule-4 threshold in minutes (default 10).
    """

    def __init__(
        self,
        events: list[UserEvent],
        events_since_last_reco: int,
        last_active_at: datetime | None,
        new_events_threshold: int = _DEFAULT_NEW_EVENTS_THRESHOLD,
        inactivity_minutes: int   = _DEFAULT_INACTIVITY_MINUTES,
    ) -> None:
        self._events                 = events
        self._events_since_last_reco = events_since_last_reco
        self._last_active_at         = last_active_at
        self._new_events_threshold   = new_events_threshold
        self._inactivity_minutes     = inactivity_minutes

        # Compute repeated searches once (shared by rule 2)
        self._interest = InterestExtractor(events, {})

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def evaluate(self) -> TriggerStatus:
        """
        Evaluate all rules and return a ``TriggerStatus``.

        Returns:
            ``TriggerStatus`` with:
            - ``should_trigger`` — True if any rule fired.
            - ``reason``         — Name of the first rule that fired, or "none".
            - ``rules_evaluated`` — Full map of rule → bool for observability.
        """
        rules: dict[str, bool] = {
            "new_events_threshold":   self._rule_new_events(),
            "repeated_search":        self._rule_repeated_search(),
            "purchase_or_wishlist":   self._rule_purchase_or_wishlist(),
            "inactivity_reengagement": self._rule_inactivity(),
        }

        fired = [name for name, hit in rules.items() if hit]
        return TriggerStatus(
            should_trigger=bool(fired),
            reason=fired[0] if fired else "none",
            rules_evaluated=rules,
        )

    # ------------------------------------------------------------------ #
    # Rules                                                               #
    # ------------------------------------------------------------------ #

    def _rule_new_events(self) -> bool:
        """
        Rule 1: ≥ NEW_EVENTS_THRESHOLD new events since last recommendation.

        Batches small amounts of activity together so the LLM is not called
        on every individual click — only when a meaningful amount of fresh
        signal has accumulated.
        """
        return self._events_since_last_reco >= self._new_events_threshold

    def _rule_repeated_search(self) -> bool:
        """
        Rule 2: user has submitted the same search query more than once.

        Repeated searches indicate the user is actively looking for
        something specific that they haven't found in the catalogue yet.
        """
        return bool(self._interest.repeated_searches())

    def _rule_purchase_or_wishlist(self) -> bool:
        """
        Rule 3: at least one PURCHASE or WISHLIST event in the window.

        These are the highest-intent signals in the event stream and
        always warrant a fresh personalised recommendation.
        """
        high_intent = {EventType.PURCHASE, EventType.WISHLIST}
        return any(e.event_type in high_intent for e in self._events)

    def _rule_inactivity(self) -> bool:
        """
        Rule 4: user has been silent for ≥ INACTIVITY_MINUTES minutes.

        Detects a natural session break — the user has stopped interacting.
        Serving a recommendation now catches them before they leave entirely.
        Only fires when we have a last-active timestamp and the user has
        historical events (avoids triggering for brand-new users).
        """
        if self._last_active_at is None or not self._events:
            return False

        last = self._last_active_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)

        cutoff = datetime.now(tz=timezone.utc) - timedelta(
            minutes=self._inactivity_minutes
        )
        return last < cutoff
