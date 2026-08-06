"""app/security/prompt_sanitizer.py — Normalize and sanitize user-supplied text."""
from __future__ import annotations
import re, html

_MAX_LENGTH = 2000
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class PromptSanitizer:
    """Clean user text before it enters any prompt or DB column."""

    @staticmethod
    def sanitize(text: str, max_length: int = _MAX_LENGTH) -> str:
        # 1. Unescape HTML entities, strip tags
        text = html.unescape(text)
        text = re.sub(r"<[^>]+>", " ", text)
        # 2. Remove control characters
        text = _CONTROL_RE.sub("", text)
        # 3. Normalize whitespace
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()
        # 4. Truncate
        if len(text) > max_length:
            text = text[:max_length]
        return text
