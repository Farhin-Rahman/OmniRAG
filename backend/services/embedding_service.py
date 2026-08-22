"""
Embedding service using local Ollama.
"""

import logging
import os
import time
import httpx
from typing import List, Union

from config.settings import settings

logger = logging.getLogger(__name__)

class EmbeddingService:
    def __init__(self):
        self.base_url = os.getenv("OLLAMA_BASE_URL", settings.ollama_base_url).rstrip("/")
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
        Generate embedding(s) for text using local Ollama.
        """
        if isinstance(text, str):
            if not text.strip():
                return [0.0] * 1024 # fallback dim, Ollama nomic is usually 768
            return self._call_ollama(text)
            
        # If it's a list, process them
        results = []
        for t in text:
            if not t.strip():
                results.append([0.0] * 1024)
            else:
                results.append(self._call_ollama(t))
        return results

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
