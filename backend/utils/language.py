"""
Lightweight language utilities for chunking and retrieval.

We don't depend on heavyweight language-id libraries because ingestion runs
inside the worker containers with limited resources. Instead we rely on simple
Unicode-range heuristics that work well enough to distinguish Arabic text from
Latin scripts.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

logger = logging.getLogger(__name__)

# Arabic characters live inside a handful of Unicode blocks. Keeping the ranges
# here avoids importing regex libraries with Unicode scripts support.
ARABIC_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)


def _is_arabic_char(char: str) -> bool:
    """Return True if the codepoint falls inside the Arabic Unicode blocks."""
    code_point = ord(char)
    return any(start <= code_point <= end for start, end in ARABIC_RANGES)


def arabic_ratio(text: str) -> float:
    """
    Compute the percentage of Arabic letters (not punctuation/digits) in a string.

    Empty strings return 0.0 to avoid division-by-zero and to keep downstream
    heuristics simple.

    Only counts Arabic letters (isalpha() + Arabic), not Arabic punctuation or digits,
    to avoid false positives from Arabic comma/digits mixed with English text.
    """
    if not text:
        return 0.0

    # Only count Arabic letters (not punctuation/digits)
    arabic_letters = sum(1 for ch in text if _is_arabic_char(ch) and ch.isalpha())
    total_letters = sum(1 for ch in text if ch.isalpha())

    if total_letters == 0:
        return 0.0

    return arabic_letters / total_letters


def detect_language(text: str, threshold: float = 0.6) -> Literal["ar", "en"]:
    """
    Heuristic language detection used both for chunking and querying.

    The threshold defaults to 60% Arabic letters (increased from 20%) to prevent
    false positives from Arabic punctuation/digits mixed with English text.
    Only Arabic letters (not punctuation/digits) are counted.

    The function currently returns either "ar" (Arabic) or "en" (fallback for
    everything else). We keep the API simple so we can extend it later without
    touching every caller.
    """
    ratio = arabic_ratio(text)
    if ratio >= threshold:
        logger.debug(
            f"Language detected as Arabic: ratio={ratio:.2f} >= threshold={threshold}"
        )
        return "ar"
    logger.debug(
        f"Language detected as English: ratio={ratio:.2f} < threshold={threshold}"
    )
    return "en"


WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """
    Collapse repeated whitespace so chunk lengths become more predictable.

    This is helpful before we measure character counts for chunk splitting.
    """
    if not text:
        return ""
    return WHITESPACE_RE.sub(" ", text).strip()
