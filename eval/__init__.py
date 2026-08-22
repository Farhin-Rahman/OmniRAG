"""
OmniRAG Offline Evaluation Package.

This package provides a production-grade evaluation pipeline for the OmniRAG RAG system,
including:
- Dataset management for golden test cases
- HTTP client for interacting with the OmniRAG API
- Metrics computation (retrieval, latency, and LLM-based via LLM-as-a-judge)
- MLflow integration for experiment tracking

Usage:
    python -m eval.runner --dataset eval/datasets/sample.jsonl --experiment omnirag_offline_eval

Environment Variables:
    EVAL_BACKEND_URL: Backend API URL (default: http://localhost:8081)
    EVAL_ACCESS_TOKEN: JWT access token for API calls
    MLFLOW_TRACKING_URI: MLflow tracking server URI (default: file:./mlruns)
    EVAL_EXPERIMENT_NAME: MLflow experiment name (default: omnirag_offline_eval)
    EVAL_LLM_MODEL: Model for LLM-based evaluation (optional, uses provider default)
    EVAL_LLM_PROVIDER: LLM provider for evaluation ('openrouter', 'vertex-ai', 'gemini', or None for auto)
    EVAL_ENABLE_LLM_EVAL: Enable LLM-based evaluation (default: false)
    OPENROUTER_API_KEY: OpenRouter API key (if using OpenRouter)
    GEMINI_API_KEY: Gemini API key (if using Gemini)
"""

__version__ = "0.1.0"
