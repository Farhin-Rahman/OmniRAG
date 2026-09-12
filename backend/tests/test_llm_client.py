"""Unit tests for LLMClient provider selection and the per-client model override."""

from ai.llm_client import GroqClient, LLMClient, OllamaClient


class TestModelOverride:
    def test_groq_model_override_applies_when_groq_active(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        client = LLMClient(model="openai/gpt-oss-20b")
        assert isinstance(client.provider, GroqClient)
        assert client.provider.default_model == "openai/gpt-oss-20b"

    def test_no_override_keeps_groq_default(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        monkeypatch.setenv("GROQ_MODEL", "some-default-model")
        client = LLMClient()
        assert isinstance(client.provider, GroqClient)
        assert client.provider.default_model == "some-default-model"

    def test_override_ignored_on_ollama_fallback(self, monkeypatch):
        # No Groq key -> falls back to Ollama, and a Groq model id must not
        # be forced onto it (it isn't a local Ollama model).
        monkeypatch.setenv("GROQ_API_KEY", "")
        monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:1.5b")
        client = LLMClient(model="openai/gpt-oss-20b")
        assert isinstance(client.provider, OllamaClient)
        assert client.provider.default_model == "qwen2.5:1.5b"
