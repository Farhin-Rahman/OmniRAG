"""
Unit tests for LLM-based translation.

Mocks LLMClient.generate — no real network calls, no GROQ_API_KEY needed.
Focus is the parsing/fallback logic around the LLM call, not the LLM's
actual translation quality (that's exercised manually against the real
API, not in CI).
"""

from unittest.mock import MagicMock

from moderation.translate import translate_to_english


class TestTranslateToEnglish:
    def test_parses_valid_json_response(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = '{"detected_language": "es", "translated_text": "We need help rebuilding the school."}'
        result = translate_to_english(
            "Necesitamos ayuda para reconstruir la escuela.", llm=mock_llm
        )
        assert result == {
            "detected_language": "es",
            "translated_text": "We need help rebuilding the school.",
        }

    def test_english_passed_through(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = '{"detected_language": "en", "translated_text": "We need help rebuilding the school."}'
        result = translate_to_english(
            "We need help rebuilding the school.", llm=mock_llm
        )
        assert result["detected_language"] == "en"

    def test_malformed_json_falls_back_to_original_text(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "not valid json at all"
        original = "Necesitamos ayuda."
        result = translate_to_english(original, llm=mock_llm)
        assert result == {"detected_language": "unknown", "translated_text": original}

    def test_llm_exception_falls_back_to_original_text(self):
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = RuntimeError("Groq API timeout")
        original = "Necesitamos ayuda."
        result = translate_to_english(original, llm=mock_llm)
        assert result == {"detected_language": "unknown", "translated_text": original}

    def test_json_missing_translated_text_falls_back(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = '{"detected_language": "es"}'
        original = "Necesitamos ayuda."
        result = translate_to_english(original, llm=mock_llm)
        assert result == {"detected_language": "unknown", "translated_text": original}
