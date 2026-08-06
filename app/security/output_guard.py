"""app/security/output_guard.py — Validate LLM recommendation output."""
from __future__ import annotations
import uuid
from app.core.logging import get_logger

logger = get_logger(__name__)
_MAX_RECOMMENDATIONS = 5


class OutputGuard:
    """Validate recommendation output before storing or serving it."""

    @staticmethod
    def validate(
        parsed: dict,
        valid_product_ids: set[str],
    ) -> tuple[bool, str, dict]:
        """
        Validate parsed LLM output.

        Returns (ok, reason, cleaned_parsed).
        ok=True means the output is safe to store.
        """
        # 1. Confidence range
        confidence = parsed.get("confidence", 0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            return False, "confidence is not a number", parsed

        if not (0.0 <= confidence <= 1.0):
            parsed["confidence"] = max(0.0, min(1.0, confidence))

        # 2. Recommended products exist and are not duplicates
        products: list[dict] = parsed.get("recommended_products", [])
        seen_ids: set[str] = set()
        clean: list[dict] = []

        for item in products:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("product_id", ""))
            if not pid:
                continue
            if pid in seen_ids:
                logger.warning("output_guard: duplicate product_id %s removed", pid)
                continue
            if valid_product_ids and pid not in valid_product_ids:
                logger.warning("output_guard: unknown product_id %s removed", pid)
                continue
            seen_ids.add(pid)
            clean.append(item)

        # 3. Max count
        clean = clean[:_MAX_RECOMMENDATIONS]

        if not clean and valid_product_ids:
            return False, "no valid products in output", parsed

        parsed["recommended_products"] = clean
        return True, "ok", parsed
