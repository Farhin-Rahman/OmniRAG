"""
System configuration API routes.

Provides runtime configuration snapshot for MLflow logging and debugging.
All values reflect actual runtime state, not guesses.
"""

import hashlib
import logging
import os
import subprocess
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from config.settings import settings
from services.request_context import RequestContext, get_request_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["System"])


def _get_git_sha() -> Optional[str]:
    """Get current git commit SHA, or None if unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=os.path.dirname(os.path.dirname(__file__)),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _get_prompt_hash() -> Optional[str]:
    """Get SHA256 hash of the chat prompt template."""
    try:
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "ai",
            "prompts",
            "chat_prompt.yaml",
        )
        if os.path.exists(prompt_path):
            with open(prompt_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:
        pass
    return None


def _value_or_provider_default(value: Optional[Any]) -> Any:
    """Return value or 'provider_default' if None."""
    return value if value is not None else "provider_default"


def _resolve_llm_provider_label() -> str:
    """Resolve the preferred LLM provider label for config snapshots."""
    preference = (settings.llm_provider_preference or "auto").strip().lower()
    if preference.startswith("vertex"):
        return "vertex-ai"
    if preference.startswith("openrouter"):
        return "openrouter"
    if preference.startswith("ollama") or preference == "local":
        return "ollama"
    return "openrouter" if settings.openrouter_api_key else "vertex-ai"


class RetrievalConfig(BaseModel):
    """Retrieval configuration snapshot."""

    embedding_model: str
    embedding_dim: int
    dense_k: int
    rerank_enabled: bool
    rerank_top_n: int
    per_doc_limit: int
    mmr_enabled: bool
    mmr_lambda: float


class GenerationConfig(BaseModel):
    """Generation configuration snapshot."""

    model: str
    provider: str
    api_base: str
    temperature: Any  # float or "provider_default"
    top_p: Any  # float or "provider_default"
    max_tokens: int
    timeout_seconds: int


class PromptConfig(BaseModel):
    """Prompt configuration snapshot."""

    prompt_sha256: Optional[str]
    citation_extraction_enabled: bool


class InfraConfig(BaseModel):
    """Infrastructure configuration snapshot."""

    git_sha: Optional[str]
    app_env: str
    ml_service_url: str
    ml_service_timeout: float
    qdrant_collection: str


class SystemConfigResponse(BaseModel):
    """Full system configuration snapshot."""

    retrieval: RetrievalConfig
    generation: GenerationConfig
    prompt: PromptConfig
    infra: InfraConfig


@router.get("/config", response_model=SystemConfigResponse)
async def get_system_config(
    _ctx: RequestContext = Depends(get_request_context),
) -> SystemConfigResponse:
    """
    Get current runtime configuration snapshot.

    Returns actual values used by the system, not defaults.
    Useful for MLflow logging to ensure reproducibility.

    Values that are not explicitly set return "provider_default".
    """
    return SystemConfigResponse(
        retrieval=RetrievalConfig(
            embedding_model=settings.embedding_model,
            embedding_dim=settings.embedding_dim,
            dense_k=settings.dense_k,
            rerank_enabled=settings.rerank_enabled,
            rerank_top_n=settings.rerank_top_n,
            per_doc_limit=settings.per_doc_limit,
            mmr_enabled=settings.mmr_enabled,
            mmr_lambda=settings.mmr_lambda,
        ),
        generation=GenerationConfig(
            model=settings.llm_model,
            provider=_resolve_llm_provider_label(),
            api_base=settings.llm_api_base,
            temperature=_value_or_provider_default(settings.llm_temperature),
            top_p=_value_or_provider_default(settings.llm_top_p),
            max_tokens=settings.llm_max_tokens,
            timeout_seconds=settings.llm_timeout,
        ),
        prompt=PromptConfig(
            prompt_sha256=_get_prompt_hash(),
            citation_extraction_enabled=settings.citation_extraction_enabled,
        ),
        infra=InfraConfig(
            git_sha=_get_git_sha(),
            app_env=settings.app_env,
            ml_service_url=settings.ml_service_url,
            ml_service_timeout=settings.ml_service_timeout,
            qdrant_collection=settings.qdrant_chunk_collection,
        ),
    )


@router.get("/health")
async def system_health() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}
