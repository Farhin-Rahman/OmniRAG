"""Language detection utility for evaluation."""

import re
from typing import Literal


def detect_language(text: str) -> Literal["ar", "en", "bn", "other"]:
    """
    Detect language of text (simplified version for evaluation).
    
    Returns:
        Language code: 'ar' (Arabic), 'en' (English), 'bn' (Bengali), or 'other'
    """
    if not text or not text.strip():
        return "other"
    
    # Count Arabic letters
    arabic_letters = sum(1 for ch in text if '\u0600' <= ch <= '\u06FF')
    total_letters = sum(1 for ch in text if ch.isalpha())
    
    if total_letters == 0:
        return "other"
    
    arabic_ratio = arabic_letters / total_letters if total_letters > 0 else 0
    
    if arabic_ratio > 0.6:
        return "ar"
    
    # Check for Bengali
    bengali_letters = sum(1 for ch in text if '\u0980' <= ch <= '\u09FF')
    bengali_ratio = bengali_letters / total_letters if total_letters > 0 else 0
    
    if bengali_ratio > 0.3:
        return "bn"
    
    # Default to English if mostly ASCII
    ascii_ratio = sum(1 for ch in text if ch.isascii() and ch.isalpha()) / total_letters if total_letters > 0 else 0
    if ascii_ratio > 0.7:
        return "en"
    
    return "other"

