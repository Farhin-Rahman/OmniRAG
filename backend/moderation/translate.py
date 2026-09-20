"""
Multilingual translation for campaign moderation.

LLM-based (reuses ai.llm_client.LLMClient / GroqClient), not a dedicated
translation model — no new dependency, no per-language model downloads,
just the same fast, already-proven inference path the rest of this
project uses. A global crowdfunding platform serves many countries; campaigns
can arrive in any language, and both the rule engine (English keyword matching) and the
risk-assessment LLM call work best on English text, so everything gets
translated to English before those run.
"""

import logging
from typing import Optional

from ai.llm_client import LLMClient
from config.settings import settings
from moderation.json_extract import extract_json_object

logger = logging.getLogger(__name__)

_DETECT_TRANSLATE_PROMPT = """Detect the language of the following text and translate it to English. Respond with ONLY compact JSON, no prose, no markdown fences.

Schema: {{"detected_language": "<ISO 639-1 code>", "translated_text": "<English translation>"}}

If the text is already in English, detected_language should be "en" and translated_text should be the text unchanged.

Text:
\"\"\"{text}\"\"\"

JSON:"""


def translate_to_english(text: str, llm: Optional[LLMClient] = None) -> dict:
    """Detect language and translate to English in one call.

    Returns {"detected_language": ..., "translated_text": ...}. Falls back
    to treating the text as English-as-is if the call or JSON parsing
    fails — a translation hiccup shouldn't block the whole moderation
    pipeline, it should just degrade to processing the original text.
    """
    llm = llm or LLMClient(model=settings.moderation_llm_model)
    prompt = _DETECT_TRANSLATE_PROMPT.format(text=text)

    try:
        # Generous floor: MODERATION_LLM_MODEL is a reasoning model whose
        # hidden reasoning eats into the token budget before the JSON
        # (translated_text) is produced. Too tight and the response comes
        # back empty.
        raw = llm.generate(
            prompt, temperature=0.0, max_tokens=max(1500, len(text.split()) * 4)
        )
        result = extract_json_object(raw)
        if result and "translated_text" in result:
            return {
                "detected_language": result.get("detected_language", "unknown"),
                "translated_text": result["translated_text"],
            }
    except Exception as e:
        logger.warning(f"Translation failed, using original text as-is: {e}")

    return {"detected_language": "unknown", "translated_text": text}
