"""app/security/prompt_guard.py — Detect prompt-injection patterns."""
from __future__ import annotations
import re
from app.core.logging import get_logger

logger = get_logger(__name__)

_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"ignore\s+(previous|all|above|prior)\s+instruction",
        r"reveal\s+(system\s+prompt|api\s+key|secret|password|token)",
        r"you\s+are\s+now\s+a?\s*(different|new|another)\s+(ai|assistant|model)",
        r"bypass\s+(instruction|filter|restriction|safety|guard)",
        r"developer\s+mode",
        r"jailbreak",
        r"do\s+anything\s+now",
        r"act\s+as\s+(if\s+you\s+are|an?\s+unrestricted)",
        r"forget\s+(all\s+)?(previous\s+)?instruction",
        r"disregard\s+(all\s+)?(previous\s+)?instruction",
    ]
]


class PromptGuard:
    """Lightweight injection detector — rejects suspicious prompts."""

    @staticmethod
    def check(text: str) -> tuple[bool, str]:
        """
        Return (safe, reason). safe=True means the text passed all checks.
        """
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(text):
                reason = f"Rejected: prompt injection pattern detected ({pattern.pattern[:40]})"
                logger.warning("prompt_guard blocked input. pattern=%s", pattern.pattern[:60])
                return False, reason
        return True, "ok"
