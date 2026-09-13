"""
Embedding service. Prefers Google's Gemini embedding API (hosted, free
tier) when GEMINI_API_KEY is set, falling back to local Ollama otherwise —
same preference pattern as ai/llm_client.py's Groq-over-Ollama choice.
Ollama has no hosted equivalent, so deployments that can't run it locally
need this to embed anything at all.
"""

import logging
import os
import httpx
from typing import List, Union

from config.settings import settings

logger = logging.getLogger(__name__)

GEMINI_EMBED_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-embedding-001:embedContent"
)
# gemini-embedding-001 defaults to 3072 dims and supports Matryoshka
# truncation via outputDimensionality — pinned to 768 to match the
# existing Qdrant collection (originally sized for Ollama's nomic-embed-text).
GEMINI_OUTPUT_DIMENSIONALITY = 768


class EmbeddingService:
    def __init__(self):
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", settings.gemini_api_key)
        self.base_url = os.getenv("OLLAMA_BASE_URL", settings.ollama_base_url).rstrip(
            "/"
        )
        # We can use the main model or a specific embedding model (e.g. nomic-embed-text)
        self.default_model = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")

    async def generate_embedding(
        self,
        text: Union[str, List[str]],
        mode: str | None = None,
        trace_id: str | None = None,
        session_id: str | None = None,
    ) -> Union[List[float], List[List[float]]]:
        """
        Generate embedding(s) for text, via Gemini if configured, else Ollama.
        """
        if isinstance(text, str):
            if not text.strip():
                return [0.0] * 1024  # fallback dim, Ollama nomic is usually 768
            return self._embed(text)

        # If it's a list, process them
        results = []
        for t in text:
            if not t.strip():
                results.append([0.0] * 1024)
            else:
                results.append(self._embed(t))
        return results

    def _embed(self, prompt: str) -> List[float]:
        if self.gemini_api_key:
            return self._call_gemini(prompt)
        return self._call_ollama(prompt)

    def _call_gemini(self, prompt: str) -> List[float]:
        try:
            response = httpx.post(
                url=f"{GEMINI_EMBED_URL}?key={self.gemini_api_key}",
                json={
                    "content": {"parts": [{"text": prompt}]},
                    "outputDimensionality": GEMINI_OUTPUT_DIMENSIONALITY,
                },
                timeout=30.0,
            )
            if response.status_code == 200:
                return response.json().get("embedding", {}).get("values", [])
            logger.error(
                f"Gemini embedding API error: {response.status_code} - {response.text}"
            )
            raise RuntimeError(f"Gemini embedding API error: {response.status_code}")
        except Exception as e:
            logger.error(f"Gemini embedding network error: {e}")
            raise RuntimeError(f"Gemini embedding network error: {e}")

    def _call_ollama(self, prompt: str) -> List[float]:
        request_data = {
            "model": self.default_model,
            "prompt": prompt,
        }
        try:
            response = httpx.post(
                url=f"{self.base_url}/api/embeddings",
                json=request_data,
                timeout=30.0,
            )
            if response.status_code == 200:
                return response.json().get("embedding", [])
            logger.error(f"Ollama API error: {response.status_code} - {response.text}")
            raise RuntimeError(f"Ollama API error: {response.status_code}")
        except Exception as e:
            logger.error(f"Ollama network error: {e}")
            raise RuntimeError(f"Ollama network error: {e}")


embedding_service = EmbeddingService()
