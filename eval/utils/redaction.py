"""
Basic PII redaction for evaluation artifacts.

Covers:
- Email addresses
- Long digit sequences (8+ digits, e.g., IDs, SSNs)
- US phone formats + generic international (7+ digits with separators)

Note: This is minimal protection. For stricter requirements, use dedicated PII tools.
"""

import re
from typing import Optional

# Pattern definitions at module level
EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')

# Long digit sequences (8+ digits) - match BEFORE phones to avoid partial replacements
DIGIT_SEQ_PATTERN = re.compile(r'\b\d{8,}\b')

# Phone patterns
PHONE_PATTERN = re.compile(
    r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'  # US format
    r'|\+?\d[\d\s\-().]{6,}\d'  # Generic international
)


def redact_text(text: Optional[str]) -> Optional[str]:
    """
    Redact PII from text.
    
    Order of operations:
    1. Return early if text is empty/None
    2. Replace emails with [EMAIL]
    3. Replace long digit sequences (8+) with [ID] (before phones!)
    4. Replace phones with [PHONE]
    
    Args:
        text: Input text to redact.
        
    Returns:
        Text with PII replaced by placeholders, or None/empty if input was None/empty.
    """
    if not text:
        return text
    
    # 1. Replace emails
    text = EMAIL_PATTERN.sub("[EMAIL]", text)
    
    # 2. Replace long digit sequences BEFORE phones (important order!)
    text = DIGIT_SEQ_PATTERN.sub("[ID]", text)
    
    # 3. Replace phone numbers
    text = PHONE_PATTERN.sub("[PHONE]", text)
    
    return text


def redact_list(texts: list) -> list:
    """Redact PII from a list of texts."""
    return [redact_text(t) for t in texts]
