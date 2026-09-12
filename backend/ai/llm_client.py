"""
LLM client abstraction for supporting Ollama.
"""

import logging
import os
import json
import time
from typing import Iterator, Optional

import httpx
from config.settings import settings

logger = logging.getLogger(__name__)


class OllamaClient:
    """Ollama local LLM client — free, no API key or internet required."""

    def __init__(self):
        self.base_url = os.getenv("OLLAMA_BASE_URL", settings.ollama_base_url).rstrip(
            "/"
        )
        self.default_model = os.getenv("OLLAMA_MODEL", settings.ollama_model)

    @property
    def provider_name(self) -> str:
        return "ollama"

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        **kwargs,
    ) -> str:
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        request_data: dict = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": False,
        }
        # Ollama's native /api/chat expects generation params nested under
        # "options" (num_predict, not max_tokens) — a top-level max_tokens/
        # temperature is silently ignored, not an error, so this was an
        # easy bug to miss: every call ran uncapped regardless of what was
        # passed here.
        options: dict = {}
        if max_tokens:
            options["num_predict"] = max_tokens
        if temperature is not None:
            options["temperature"] = temperature
        if options:
            request_data["options"] = options

        start_time = time.time()
        try:
            response = httpx.post(
                url=f"{self.base_url}/api/chat",  # Note: using /api/chat instead of OpenAI compatibility to ensure ollama local api.
                headers={"Content-Type": "application/json"},
                content=json.dumps(request_data),
                timeout=settings.llm_timeout,
            )
            elapsed_ms = int((time.time() - start_time) * 1000)

            if response.status_code == 200:
                logger.info(f"Ollama LLM response: {elapsed_ms}ms status=200")
                return response.json()["message"]["content"]

            logger.error(
                f"Ollama API error: {elapsed_ms}ms status={response.status_code} - {response.text}"
            )
            raise RuntimeError(f"Ollama API error: {response.status_code}")
        except httpx.TimeoutException:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Ollama LLM timeout: {elapsed_ms}ms")
            raise RuntimeError(f"Ollama API timeout after {settings.llm_timeout}s")
        except httpx.RequestError as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Ollama LLM network error: {elapsed_ms}ms - {e}")
            raise RuntimeError(f"Ollama API network error: {e}")

    def is_available(self) -> bool:
        return bool(self.base_url and self.default_model)

    def generate_stream(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        **kwargs,
    ) -> Iterator[str]:
        """Yield response text incrementally as Ollama produces it (NDJSON stream)."""
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        request_data: dict = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": True,
        }
        options: dict = {}
        if max_tokens:
            options["num_predict"] = max_tokens
        if temperature is not None:
            options["temperature"] = temperature
        if options:
            request_data["options"] = options

        start_time = time.time()
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/api/chat",
                headers={"Content-Type": "application/json"},
                content=json.dumps(request_data),
                timeout=settings.llm_timeout,
            ) as response:
                if response.status_code != 200:
                    body = response.read()
                    raise RuntimeError(
                        f"Ollama API error: {response.status_code} - {body}"
                    )

                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    piece = chunk.get("message", {}).get("content", "")
                    if piece:
                        yield piece
                    if chunk.get("done"):
                        break

            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.info(f"Ollama LLM stream complete: {elapsed_ms}ms")
        except httpx.TimeoutException:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Ollama LLM stream timeout: {elapsed_ms}ms")
            raise RuntimeError(f"Ollama API timeout after {settings.llm_timeout}s")
        except httpx.RequestError as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Ollama LLM stream network error: {elapsed_ms}ms - {e}")
            raise RuntimeError(f"Ollama API network error: {e}")


# Process-wide token counter for Groq calls. Not thread-safe (an
# undercount under concurrency is harmless) — it exists so an offline run
# like the moderation eval can report real token usage and cost. Live
# request paths don't read it.
_groq_usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


def get_groq_usage() -> dict:
    return dict(_groq_usage)


def reset_groq_usage() -> None:
    _groq_usage.update(calls=0, prompt_tokens=0, completion_tokens=0)


class GroqClient:
    """Groq API client — hosted, fast (custom inference hardware), free tier.

    Used in preference to Ollama when GROQ_API_KEY is set: local CPU
    inference is too slow for latency-sensitive paths like the live voice
    agent (10+ seconds per response), where Groq responds in under a
    second. OpenAI-compatible chat completions API.
    """

    BASE_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY", settings.groq_api_key)
        self.default_model = os.getenv("GROQ_MODEL", settings.groq_model)

    @property
    def provider_name(self) -> str:
        return "groq"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        **kwargs,
    ) -> str:
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        request_data: dict = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": False,
        }
        if max_tokens:
            request_data["max_tokens"] = max_tokens
        if temperature is not None:
            request_data["temperature"] = temperature

        start_time = time.time()
        try:
            response = httpx.post(
                url=self.BASE_URL,
                headers=self._headers(),
                content=json.dumps(request_data),
                timeout=settings.llm_timeout,
            )
            elapsed_ms = int((time.time() - start_time) * 1000)

            if response.status_code == 200:
                logger.info(f"Groq LLM response: {elapsed_ms}ms status=200")
                data = response.json()
                usage = data.get("usage") or {}
                _groq_usage["calls"] += 1
                _groq_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
                _groq_usage["completion_tokens"] += usage.get("completion_tokens", 0)
                return data["choices"][0]["message"]["content"]

            logger.error(
                f"Groq API error: {elapsed_ms}ms status={response.status_code} - {response.text}"
            )
            raise RuntimeError(f"Groq API error: {response.status_code}")
        except httpx.TimeoutException:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Groq LLM timeout: {elapsed_ms}ms")
            raise RuntimeError(f"Groq API timeout after {settings.llm_timeout}s")
        except httpx.RequestError as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Groq LLM network error: {elapsed_ms}ms - {e}")
            raise RuntimeError(f"Groq API network error: {e}")

    def is_available(self) -> bool:
        return bool(self.api_key and self.default_model)

    def generate_stream(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        **kwargs,
    ) -> Iterator[str]:
        """Yield response text incrementally (SSE stream)."""
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        request_data: dict = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": True,
        }
        if max_tokens:
            request_data["max_tokens"] = max_tokens
        if temperature is not None:
            request_data["temperature"] = temperature

        start_time = time.time()
        try:
            with httpx.stream(
                "POST",
                self.BASE_URL,
                headers=self._headers(),
                content=json.dumps(request_data),
                timeout=settings.llm_timeout,
            ) as response:
                if response.status_code != 200:
                    body = response.read()
                    raise RuntimeError(
                        f"Groq API error: {response.status_code} - {body}"
                    )

                for line in response.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    payload = line[len("data: ") :]
                    if payload.strip() == "[DONE]":
                        break
                    chunk = json.loads(payload)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    piece = delta.get("content", "")
                    if piece:
                        yield piece

            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.info(f"Groq LLM stream complete: {elapsed_ms}ms")
        except httpx.TimeoutException:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Groq LLM stream timeout: {elapsed_ms}ms")
            raise RuntimeError(f"Groq API timeout after {settings.llm_timeout}s")
        except httpx.RequestError as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Groq LLM stream network error: {elapsed_ms}ms - {e}")
            raise RuntimeError(f"Groq API network error: {e}")


class LLMClient:
    """Main LLM client — prefers Groq (fast, hosted) when configured,
    falls back to Ollama (free, local, slower) otherwise."""

    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
        groq = GroqClient()
        if groq.is_available():
            # `model` overrides the Groq model for this client only (a fresh
            # GroqClient per LLMClient, so no shared state). Deliberately not
            # applied to the Ollama fallback: a Groq model id like
            # "openai/gpt-oss-20b" isn't a local Ollama model, so falling
            # back to Ollama's own default is the right degradation.
            if model:
                groq.default_model = model
            self.provider = groq
        else:
            self.provider = OllamaClient()

    def generate_chat_response(
        self, prompt: str, system_instruction: Optional[str] = None, **kwargs
    ) -> str:
        return self.provider.generate(
            prompt=prompt, system_instruction=system_instruction, **kwargs
        )

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs,
    ) -> str:
        return self.provider.generate(
            prompt=prompt,
            system_instruction=system_instruction,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

    def generate_stream(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        **kwargs,
    ) -> Iterator[str]:
        yield from self.provider.generate_stream(
            prompt=prompt,
            system_instruction=system_instruction,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

    @property
    def provider_name(self) -> str:
        return self.provider.provider_name

    def is_available(self) -> bool:
        return self.provider.is_available()
