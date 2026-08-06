"""
app/security/prompt_sanitizer.py
----------------------------------
Sanitizes user-supplied text before it is embedded in an LLM prompt
or stored in the database.

Why sanitize?
~~~~~~~~~~~~~
LLMs are sensitive to what's in their input. Malformed, excessively long,
or specially crafted text can:
  - Confuse the model and produce poor recommendations
  - Bloat the prompt and waste tokens (which costs money/time)
  - Carry hidden HTML/script content that breaks rendering

This sanitizer normalises text to a clean, safe, standard form without
changing the actual meaning of the content.

What it does (in order)
~~~~~~~~~~~~~~~~~~~~~~~~
1. Unescape HTML entities  — "&amp;" → "&", "&lt;" → "<"
2. Strip HTML tags          — "<b>hello</b>" → "hello"
3. Remove control chars     — invisible ASCII characters that confuse parsers
4. Normalise whitespace     — collapse multiple spaces, limit blank lines
5. Truncate                 — cap at max_length to avoid huge prompts

Usage
~~~~~
    from app.security.prompt_sanitizer import PromptSanitizer

    clean = PromptSanitizer.sanitize(user_input)
    # Now safe to embed in an LLM prompt or store in the DB
"""

from __future__ import annotations

import html
import re

# Maximum number of characters allowed in a sanitised prompt
_MAX_LENGTH = 2000

# Regex matching invisible/non-printable ASCII control characters.
# These are safe to strip — they serve no purpose in user text.
# Excludes: \t (tab=0x09), \n (newline=0x0a), \r (carriage return=0x0d)
# Includes: NUL, SOH, STX, ETX, EOT, ENQ, ACK, BEL, BS (0x00–0x08)
#           VT, FF (0x0b, 0x0c), SO–US (0x0e–0x1f), DEL (0x7f)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class PromptSanitizer:
    """
    Stateless utility class for cleaning user-supplied text.

    All methods are static — no instance needed::

        clean_text = PromptSanitizer.sanitize(raw_user_input)
    """

    @staticmethod
    def sanitize(text: str, max_length: int = _MAX_LENGTH) -> str:
        """
        Clean and normalise a text string for safe use in prompts or storage.

        Steps applied (in order):
        1. Unescape HTML entities and strip HTML tags
        2. Remove invisible control characters
        3. Collapse multiple spaces/tabs into one
        4. Collapse 3+ consecutive newlines into 2
        5. Strip leading/trailing whitespace
        6. Truncate to max_length characters

        Args:
            text:       Raw string from user input.
            max_length: Maximum allowed length. Defaults to 2000 chars.

        Returns:
            Sanitised string, safe for prompt embedding and DB storage.

        Examples:
            >>> PromptSanitizer.sanitize("<b>Hello</b>  world  ")
            "Hello world"

            >>> PromptSanitizer.sanitize("x" * 5000)
            # → 2000 characters max
        """
        # Step 1a: Convert HTML entities like &amp; back to their characters
        text = html.unescape(text)

        # Step 1b: Remove all HTML/XML tags (anything between < and >)
        text = re.sub(r"<[^>]+>", " ", text)

        # Step 2: Strip invisible control characters (non-printable ASCII)
        text = _CONTROL_RE.sub("", text)

        # Step 3: Collapse runs of spaces/tabs to a single space
        text = re.sub(r"[ \t]+", " ", text)

        # Step 4: Collapse 3 or more consecutive blank lines to just 2
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Step 5: Remove leading/trailing whitespace
        text = text.strip()

        # Step 6: Hard truncate to max_length (avoids bloating prompts)
        if len(text) > max_length:
            text = text[:max_length]

        return text
