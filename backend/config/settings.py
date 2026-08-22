import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


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

    # SharePoint / Microsoft Graph Configuration
    sharepoint_client_id: str = ""
    sharepoint_client_secret: str = ""
    sharepoint_tenant_id: str = ""
    sharepoint_site_id: str = ""

    # ML Service Configuration
    ml_service_url: str = os.getenv("ML_SERVICE_URL", "http://ml-service:8000")
    ml_service_timeout: float = float(os.getenv("ML_SERVICE_TIMEOUT", "10.0"))

    # Retrieval Configuration (for MLflow config snapshot)
    dense_k: int = int(os.getenv("DENSE_K", "50"))
    per_doc_limit: int = int(os.getenv("PER_DOC_LIMIT", "3"))

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
