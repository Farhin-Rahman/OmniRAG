"""
Configuration for OmniRAG Offline Evaluation.

Version: 2.0.0 - Industry-standard reproducible evaluation harness.

This module provides configuration management via Pydantic settings,
supporting both environment variables and programmatic configuration.

Environment Variables:
    EVAL_BACKEND_URL: Backend API URL (default: http://localhost:8081)
    EVAL_ACCESS_TOKEN: JWT access token for API calls (required)
    MLFLOW_TRACKING_URI: MLflow tracking server URI (default: file:./mlruns)
    EVAL_EXPERIMENT_NAME: MLflow experiment name (default: omnirag_offline_eval)
    EVAL_LLM_MODEL: Model for LLM-based evaluation (optional, uses provider default)
    EVAL_LLM_PROVIDER: LLM provider for evaluation ('openrouter', 'vertex-ai', 'gemini', or None for auto)
    EVAL_ENABLE_LLM_EVAL: Enable LLM-based evaluation metrics (default: false)
    EVAL_REQUEST_TIMEOUT: HTTP request timeout in seconds (default: 120)
    OPENROUTER_API_KEY: OpenRouter API key (if using OpenRouter for evaluation)
    GEMINI_API_KEY: Gemini API key (if using Gemini for evaluation)

Example:
    from eval.config import EvalSettings
    
    # Load from environment
    settings = EvalSettings()
    
    # Or override programmatically
    settings = EvalSettings(
        backend_url="http://localhost:8081",
        access_token="your-jwt",
        experiment_name="my_experiment"
    )
"""

import hashlib
import json
import os
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

# =============================================================================
# Versioning Constants
# =============================================================================
EVAL_HARNESS_VERSION = "2.0.0"
EVAL_SCHEMA_VERSION = "v1"
DATASET_SCHEMA_VERSION = "v2"


# =============================================================================
# Canonical JSON Helpers (for deterministic hashing)
# =============================================================================
def canonical_json(obj: Any) -> str:
    """Canonical JSON for deterministic hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_sha256(obj: Any) -> str:
    """Compute SHA256 of canonical JSON representation."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


class EvalSettings(BaseModel):
    """
    Configuration settings for the evaluation pipeline.
    
    All settings can be loaded from environment variables or passed directly.
    Environment variables are prefixed with EVAL_ (except MLFLOW_TRACKING_URI).
    
    Attributes:
        backend_url: Base URL for the OmniRAG backend API.
        access_token: JWT access token used for API authentication.
        mlflow_tracking_uri: URI for MLflow tracking server or local file store.
        experiment_name: Name of the MLflow experiment to log runs to.
        llm_eval_model: Model identifier for LLM-based evaluation (optional).
        llm_eval_provider: LLM provider for evaluation ('openrouter', 'vertex-ai', 'gemini', or None for auto).
        enable_llm_eval: Whether to compute LLM-based evaluation metrics (answer relevance, faithfulness).
        request_timeout: HTTP request timeout in seconds.
    """
    
    backend_url: str = Field(
        default_factory=lambda: os.getenv("EVAL_BACKEND_URL", "http://localhost:8081"),
        description="Base URL for the OmniRAG backend API"
    )
    
    access_token: Optional[str] = Field(
        default_factory=lambda: os.getenv("EVAL_ACCESS_TOKEN"),
        description="JWT access token for authenticated API calls"
    )
    
    mlflow_tracking_uri: str = Field(
        default_factory=lambda: os.getenv("MLFLOW_TRACKING_URI", "file:./mlruns"),
        description="MLflow tracking server URI"
    )
    
    experiment_name: str = Field(
        default_factory=lambda: os.getenv("EVAL_EXPERIMENT_NAME", "omnirag_offline_eval"),
        description="MLflow experiment name"
    )
    
    llm_eval_model: Optional[str] = Field(
        default_factory=lambda: os.getenv("EVAL_LLM_MODEL"),
        description="Model for LLM-based evaluation (optional, uses provider default if not set)"
    )
    
    llm_eval_provider: Optional[str] = Field(
        default_factory=lambda: os.getenv("EVAL_LLM_PROVIDER"),
        description="LLM provider for evaluation ('openrouter', 'vertex-ai', 'gemini', or None for auto-detect)"
    )
    
    enable_llm_eval: bool = Field(
        default_factory=lambda: os.getenv("EVAL_ENABLE_LLM_EVAL", "false").lower() in ("true", "1", "yes"),
        description="Whether to enable LLM-based evaluation metrics (OFF by default)"
    )
    
    request_timeout: float = Field(
        default_factory=lambda: float(os.getenv("EVAL_REQUEST_TIMEOUT", "120")),
        description="HTTP request timeout in seconds"
    )
    
    # =========================================================================
    # Privacy & Size Controls (Phase C)
    # =========================================================================
    log_full_context: bool = Field(
        default_factory=lambda: os.getenv("EVAL_LOG_FULL_CONTEXT", "false").lower() == "true",
        description="Log full context text in artifacts (default: false for privacy)"
    )
    
    max_chunks_logged: int = Field(
        default_factory=lambda: int(os.getenv("EVAL_MAX_CHUNKS_LOGGED", "12")),
        description="Max retrieval chunks to log per example"
    )
    
    max_context_chars_per_chunk: int = Field(
        default_factory=lambda: int(os.getenv("EVAL_MAX_CONTEXT_CHARS", "2000")),
        description="Max characters per chunk in artifacts"
    )
    
    redact_artifacts: bool = Field(
        default_factory=lambda: os.getenv("EVAL_REDACT_ARTIFACTS", "true").lower() == "true",
        description="Apply PII redaction to artifacts"
    )
    
    compress_artifacts: bool = Field(
        default_factory=lambda: os.getenv("EVAL_COMPRESS_ARTIFACTS", "false").lower() == "true",
        description="Gzip compress large artifacts"
    )
    
    # =========================================================================
    # Metrics Controls
    # =========================================================================
    enable_rouge: bool = Field(
        default_factory=lambda: os.getenv("EVAL_ENABLE_ROUGE", "false").lower() == "true",
        description="Enable ROUGE-L metric (requires rouge-score package)"
    )

    @field_validator("access_token")
    @classmethod
    def normalize_access_token(cls, v: Optional[str]) -> Optional[str]:
        """Normalize access token to None if blank."""
        if not v:
            return None
        token = v.strip()
        return token or None

    @field_validator("backend_url")
    @classmethod
    def validate_backend_url(cls, v: str) -> str:
        """Ensure backend_url doesn't have a trailing slash."""
        return v.rstrip("/")

    model_config = {
        "extra": "ignore",
        "validate_default": True,
    }


def get_settings(**overrides) -> EvalSettings:
    """
    Factory function to create EvalSettings with optional overrides.
    
    Args:
        **overrides: Keyword arguments to override default/environment settings.
        
    Returns:
        EvalSettings instance with merged configuration.
        
    Example:
        settings = get_settings(experiment_name="custom_experiment")
    """
    return EvalSettings(**overrides)
