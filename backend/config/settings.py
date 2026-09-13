import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "OmniRAG Automation API"
    app_env: str = "development"

    database_url: str = "sqlite:///./data/omnirag.db"

    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_uri: str = "http://qdrant:6333"
    qdrant_collection: str = "chunks"

    qdrant_chunk_collection_prefix: str = "chunks"
    qdrant_doc_collection_prefix: str = "docs"

    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768

    blob_storage_dir: str = "data/blob_storage"
    documents_dir: str = "data/documents"  # Configurable document storage path

    # Batch Ingestion Configuration
    batch_input_dir: str = "data/batch-input"
    batch_tracking_file: str = "data/batch-processed.json"

    # AI/Agent Configuration - Ollama (local, free)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    llm_model: str = "qwen2.5:7b"
    llm_timeout: int = 120
    llm_max_tokens: int = 4096
    llm_provider_preference: str = "ollama"

    # Groq (hosted, fast) — used instead of Ollama when GROQ_API_KEY is set.
    # Local CPU inference is too slow for latency-sensitive paths like the
    # live voice agent; Groq's inference hardware responds in under a second.
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

    # Gemini (hosted, free tier) — used for embeddings instead of Ollama when
    # GEMINI_API_KEY is set. Ollama has no hosted equivalent, so deployments
    # that can't run it locally (no GPU/CPU budget for it) need a hosted
    # embedding provider; Gemini's text-embedding-004 is free-tier and
    # outputs 768 dims by default, matching the existing Qdrant collection.
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    # Trust & Safety moderation runs its own model choice: unlike the voice
    # agent (fast, direct-answer, latency-bound), risk assessment benefits
    # from a reasoning model and isn't latency-sensitive. Offline eval
    # (moderation/eval) showed the default voice model scoring every case
    # at 0.5. Only applied when the active provider is Groq.
    moderation_llm_model: str = os.getenv("MODERATION_LLM_MODEL", "openai/gpt-oss-20b")

    # ML Service Configuration
    ml_service_url: str = os.getenv("ML_SERVICE_URL", "http://ml-service:8000")
    ml_service_timeout: float = float(os.getenv("ML_SERVICE_TIMEOUT", "10.0"))

    # Retrieval Configuration (for MLflow config snapshot)
    dense_k: int = int(os.getenv("DENSE_K", "50"))
    per_doc_limit: int = int(os.getenv("PER_DOC_LIMIT", "3"))

    # Voice Agent (Retell custom-LLM) Configuration
    n8n_booking_webhook_url: str = os.getenv("N8N_BOOKING_WEBHOOK_URL", "")
    voice_websocket_secret: str = os.getenv("VOICE_WEBSOCKET_SECRET", "")
    # Platform API key (Settings > API Keys in Retell dashboard) — distinct
    # from the Custom LLM websocket URL/secret above. Used server-side only,
    # to start web-call sessions on behalf of the OmniRAG frontend.
    retell_api_key: str = os.getenv("RETELL_API_KEY", "")
    retell_agent_id: str = os.getenv("RETELL_AGENT_ID", "")

    # Firebase Auth — service account JSON lives at backend/gcp-service-account.json
    # (gitignored, never committed). Override the path via env if needed.
    firebase_service_account_path: str = os.getenv(
        "FIREBASE_SERVICE_ACCOUNT_PATH", "gcp-service-account.json"
    )

    # Slack Incoming Webhook for moderation alerts (hard-blocks, escalations).
    # Optional — unset means notifications are silently skipped.
    slack_webhook_url: str = os.getenv("SLACK_WEBHOOK_URL", "")

    @property
    def qdrant_chunk_collection(self) -> str:
        safe_model_name = self.embedding_model.replace("/", "_").replace("-", "_")
        return f"{self.qdrant_chunk_collection_prefix}_{safe_model_name}"

    @property
    def qdrant_doc_collection(self) -> str:
        safe_model_name = self.embedding_model.replace("/", "_").replace("-", "_")
        return f"{self.qdrant_doc_collection_prefix}_{safe_model_name}"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
    )


settings = Settings()
