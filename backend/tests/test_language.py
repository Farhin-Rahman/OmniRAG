"""
Unit tests for language detection utilities.

Tests edge cases including:
- Pure English text
- Pure Arabic text
- Bengali text (should default to English)
- Mixed text with Arabic punctuation/digits (should NOT flip to Arabic)
- Empty strings
- Numbers only
"""

from utils.language import arabic_ratio, detect_language, normalize_text


class TestArabicRatio:
    """Tests for arabic_ratio function."""

    def test_empty_string(self):
        """Empty string should return 0.0."""
        assert arabic_ratio("") == 0.0

    def test_pure_english(self):
        """Pure English text should have 0.0 Arabic ratio."""
        text = "Hello world, this is a test."
        assert arabic_ratio(text) == 0.0

    def test_pure_arabic(self):
        """Pure Arabic text should have ~1.0 Arabic ratio."""
        text = "مرحبا بالعالم"  # "Hello world" in Arabic
        ratio = arabic_ratio(text)
        assert ratio > 0.9, f"Expected >0.9, got {ratio}"

    def test_mixed_mostly_english(self):
        """Mostly English text with some Arabic should have low ratio."""
        text = "Hello world مرحبا test"  # One Arabic word
        ratio = arabic_ratio(text)
        assert ratio < 0.5, f"Expected <0.5, got {ratio}"

    def test_mixed_mostly_arabic(self):
        """Mostly Arabic text with some English should have high ratio."""
        text = "مرحبا بالعالم Hello مرحبا"  # Mostly Arabic
        ratio = arabic_ratio(text)
        assert ratio > 0.6, f"Expected >0.6, got {ratio}"

    def test_arabic_punctuation_only_does_not_count(self):
        """Arabic punctuation (not letters) should not affect ratio."""
        # Arabic comma ، and Arabic-Indic digits ٠١٢ should not count as Arabic
        text = "Hello، world٠١٢"
        ratio = arabic_ratio(text)
        # The Arabic comma and digits are NOT letters, so ratio should be 0
        assert ratio == 0.0, f"Expected 0.0 (only English letters), got {ratio}"

    def test_numbers_only(self):
        """Numbers only should return 0.0 (no letters)."""
        text = "12345"
        assert arabic_ratio(text) == 0.0

    def test_whitespace_only(self):
        """Whitespace only should return 0.0."""
        text = "   \t\n"
        assert arabic_ratio(text) == 0.0


class TestDetectLanguage:
    """Tests for detect_language function."""

    def test_english_returns_en(self):
        """Pure English text should return 'en'."""
        text = "This is a test sentence in English."
        assert detect_language(text) == "en"

    def test_arabic_returns_ar(self):
        """Pure Arabic text should return 'ar'."""
        text = "هذا اختبار باللغة العربية"  # "This is a test in Arabic"
        assert detect_language(text) == "ar"

    def test_bengali_returns_en(self):
        """Bengali text should return 'en' (fallback)."""
        text = "এটি বাংলা ভাষায় একটি পরীক্ষা"  # "This is a test in Bengali"
        assert detect_language(text) == "en"

    def test_mixed_with_arabic_comma_stays_english(self):
        """English text with Arabic comma should NOT flip to Arabic."""
        # This was the bug - Arabic punctuation was triggering Arabic detection
        text = "Hello، world"  # Arabic comma ، in English text
        assert detect_language(text) == "en"

    def test_mixed_with_arabic_digits_stays_english(self):
        """English text with Arabic-Indic digits should NOT flip to Arabic."""
        text = "The value is ٤٢"  # Arabic-Indic digit 42
        assert detect_language(text) == "en"

    def test_threshold_boundary_below(self):
        """Text just below 60% Arabic should return 'en'."""
        # 3 English words + 1 Arabic word = ~25% Arabic
        text = "Hello world test مرحبا"
        assert detect_language(text) == "en"

    def test_threshold_boundary_above(self):
        """Text above 60% Arabic should return 'ar'."""
        # 3 Arabic words + 1 English word = ~75% Arabic
        text = "مرحبا العالم اختبار hello"
        assert detect_language(text) == "ar"

    def test_empty_string_returns_en(self):
        """Empty string should return 'en' (fallback)."""
        assert detect_language("") == "en"

    def test_custom_threshold(self):
        """Custom threshold parameter should be respected."""
        text = "Hello مرحبا"  # ~50% Arabic
        # With low threshold (0.3), should return 'ar'
        assert detect_language(text, threshold=0.3) == "ar"
        # With high threshold (0.7), should return 'en'
        assert detect_language(text, threshold=0.7) == "en"


class TestNormalizeText:
    """Tests for normalize_text function."""

    def test_collapse_whitespace(self):
        """Multiple spaces should collapse to single space."""
        text = "Hello    world"
        assert normalize_text(text) == "Hello world"

    def test_strip_leading_trailing(self):
        """Leading and trailing whitespace should be stripped."""
        text = "   Hello world   "
        assert normalize_text(text) == "Hello world"

    def test_newlines_become_spaces(self):
        """Newlines should become single spaces."""
        text = "Hello\n\nworld"
        assert normalize_text(text) == "Hello world"

    def test_tabs_become_spaces(self):
        """Tabs should become single spaces."""
        text = "Hello\t\tworld"
        assert normalize_text(text) == "Hello world"

    def test_empty_string(self):
        """Empty string should return empty string."""
        assert normalize_text("") == ""


# Integration tests that match real-world scenarios
class TestRealWorldScenarios:
    """Test cases based on actual user issues."""

    def test_english_with_arabic_ref_number(self):
        """English document referencing Arabic document numbers."""
        text = "Please refer to document ٢٠٢٣/١٢٣ for details."
        assert detect_language(text) == "en"

    def test_code_switching_mostly_english(self):
        """Code-switching text that is mostly English."""
        text = "The patient reported أعراض severe headaches and dizziness."
        # Even with one Arabic word, if mostly English, should return 'en'
        result = detect_language(text)
        assert result == "en", f"Expected 'en', got '{result}'"

    def test_code_switching_mostly_arabic(self):
        """Code-switching text that is mostly Arabic."""
        # Use text with more Arabic characters to ensure >60% Arabic ratio
        text = "المريض قال أنه يعاني من صداع شديد severe"
        result = detect_language(text)
        assert result == "ar", f"Expected 'ar', got '{result}'"
