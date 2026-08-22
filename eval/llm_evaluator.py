"""
LLM-as-a-Judge Evaluator for OmniRAG RAG System.

This module provides LLM-based evaluation metrics (answer relevance and faithfulness)
using the same LLM providers already configured in the backend (OpenRouter, Vertex AI, Gemini).

The evaluator uses well-designed prompts to get reliable scores from LLMs,
integrated directly with MLflow for experiment tracking.

Example:
    from eval.llm_evaluator import LLMEvaluator
    
    evaluator = LLMEvaluator()
    relevance_score = evaluator.evaluate_relevance(
        query="What is the vacation policy?",
        answer="Employees get 20 days of vacation per year..."
    )
    faithfulness_score = evaluator.evaluate_faithfulness(
        answer="Employees get 20 days...",
        context=["Policy document: Employees receive 20 vacation days..."]
    )
"""

import logging
import os
import re
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class LLMEvaluator:
    """
    LLM-as-a-judge evaluator using existing LLM client infrastructure.
    
    This evaluator uses the same LLM providers (OpenRouter, Vertex AI, Gemini)
    that are already configured in the backend, avoiding additional dependencies.
    
    The evaluator uses structured prompts to get reliable 0-1 scores for:
    - Answer Relevance: How well does the answer address the query?
    - Faithfulness: Is the answer grounded in the provided context?
    """
    
    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.0,
    ):
        """
        Initialize LLM evaluator.
        
        Args:
            provider: LLM provider ('openrouter', 'vertex-ai', or None for auto-detect).
            model: Model name (optional, uses default from provider).
            temperature: Temperature for evaluation (default 0.0 for consistency).
        """
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self._llm_client = None
        
    def _get_llm_client(self):
        """
        Get or create LLM client instance.
        
        Uses lazy initialization and caches the client for performance.
        If provider is explicitly set to 'gemini', use fallback client directly.
        Otherwise, try backend client first, then fallback.
        """
        if self._llm_client is None:
            # If provider is explicitly set to 'gemini', use fallback client directly
            # (backend client may auto-detect OpenRouter first)
            if self.provider and self.provider.lower() == "gemini":
                logger.debug("Provider explicitly set to 'gemini', using fallback client (direct API calls)")
                self._llm_client = self._create_fallback_client()
            else:
                # Try to use backend LLM client first (better integration)
                backend_client = self._try_backend_client()
                if backend_client:
                    self._llm_client = backend_client
                else:
                    # Fallback: use direct API calls
                    logger.debug("Using fallback LLM client (direct API calls)")
                    self._llm_client = self._create_fallback_client()
        
        return self._llm_client
    
    def _try_backend_client(self):
        """Try to initialize backend LLM client, return None if unavailable."""
        try:
            import sys
            from pathlib import Path
            
            # Add backend to path if not already there
            backend_path = Path(__file__).parent.parent / "backend"
            if backend_path.exists() and str(backend_path) not in sys.path:
                sys.path.insert(0, str(backend_path))
            
            from ai.llm_client import LLMClient
            
            # Initialize client with specified provider or auto-detect
            client = LLMClient(provider=self.provider)
            logger.debug(f"Initialized LLM evaluator with backend client: {client.provider_name}")
            return client
            
        except ImportError:
            # Backend not available - this is fine, we'll use fallback
            logger.debug("Backend LLM client not available, will use fallback")
            return None
        except Exception as e:
            logger.warning(f"Failed to initialize backend LLM client: {e}, using fallback")
            return None
    
    def _create_fallback_client(self):
        """Create a fallback client using direct API calls."""
        return FallbackLLMClient(provider=self.provider, model=self.model)
    
    def _call_llm(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """
        Call LLM with prompt and return response.
        
        Args:
            prompt: User prompt.
            system_instruction: Optional system instruction.
            
        Returns:
            LLM response text.
        """
        client = self._get_llm_client()
        
        try:
            # Call generate - both backend client and FallbackLLMClient handle model internally
            # Backend client uses provider_name, FallbackLLMClient uses provider
            # Both are already configured with the correct model in their __init__
            response = client.generate(
                prompt=prompt,
                system_instruction=system_instruction,
                temperature=self.temperature,
                max_tokens=500,  # Evaluation responses should be short
            )
            return response.strip()
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise
    
    def _parse_score(self, response: str, metric_name: str) -> Optional[float]:
        """
        Parse a 0-1 score from LLM response.
        
        Looks for patterns like:
        - "Score: 0.85"
        - "1.0" or "1.00"
        - "0.75"
        - "85%" -> 0.85
        - "8.5/10" -> 0.85
        
        Args:
            response: LLM response text.
            metric_name: Name of metric (for logging).
            
        Returns:
            Parsed score (0-1) or None if parsing failed.
        """
        # Clean the response - remove extra whitespace
        response_clean = response.strip()
        
        # Try to extract number from response
        # Order matters: check for 1.0 first, then other patterns
        # Pattern 1: Look for 1.0 or 1.00 explicitly (must check first to avoid matching "0" from "1.0")
        if re.search(r'\b1\.0+\b', response_clean):
            logger.debug(f"Parsed {metric_name} score: 1.0 from response: {response_clean[:100]}")
            return 1.0
        
        # Pattern 2: Look for percentage
        percent_match = re.search(r'(\d+(?:\.\d+)?)%', response_clean)
        if percent_match:
            try:
                score = float(percent_match.group(1)) / 100.0
                score = max(0.0, min(1.0, score))
                logger.debug(f"Parsed {metric_name} score: {score} from percentage in response: {response_clean[:100]}")
                return score
            except ValueError:
                pass
        
        # Pattern 3: Look for fraction like "8.5/10"
        fraction_match = re.search(r'(\d+(?:\.\d+)?)/10\b', response_clean)
        if fraction_match:
            try:
                score = float(fraction_match.group(1)) / 10.0
                score = max(0.0, min(1.0, score))
                logger.debug(f"Parsed {metric_name} score: {score} from fraction in response: {response_clean[:100]}")
                return score
            except ValueError:
                pass
        
        # Pattern 4: Look for decimal numbers 0.0 to 1.0 (but not starting with 1.0 which we already handled)
        # Match: 0.0, 0.1, 0.85, .9, etc. but not 1.0 (already handled)
        decimal_match = re.search(r'\b(0\.\d+|\.\d+)\b', response_clean)
        if decimal_match:
            try:
                score = float(decimal_match.group(1))
                score = max(0.0, min(1.0, score))
                logger.debug(f"Parsed {metric_name} score: {score} from decimal in response: {response_clean[:100]}")
                return score
            except ValueError:
                pass
        
        # Pattern 5: Look for integer 0 or 1 (less common but possible)
        if re.search(r'\b0\b', response_clean) and not re.search(r'\b0\.\d', response_clean):
            logger.debug(f"Parsed {metric_name} score: 0.0 from integer 0 in response: {response_clean[:100]}")
            return 0.0
        
        logger.warning(f"Could not parse {metric_name} score from response: {response_clean[:200]}")
        return None
    
    def evaluate_relevance(
        self,
        query: str,
        answer: str,
    ) -> Optional[float]:
        """
        Evaluate answer relevance to the query.
        
        Uses LLM-as-a-judge to score how well the answer addresses the query
        on a scale of 0-1, where:
        - 1.0: Answer perfectly addresses the query
        - 0.5: Answer partially addresses the query
        - 0.0: Answer does not address the query
        
        Args:
            query: Original user query.
            answer: Generated answer from RAG system.
            
        Returns:
            Relevance score (0-1) or None if evaluation failed.
        """
        if not query or not answer:
            logger.warning("Query or answer is empty, skipping relevance evaluation")
            return None
        
        system_instruction = """You are an expert evaluator assessing answer quality for a RAG (Retrieval-Augmented Generation) system.

Your task is to evaluate how well an answer addresses a user's query. Provide a score from 0.0 to 1.0 where:
- 1.0: The answer perfectly and completely addresses the query
- 0.8-0.9: The answer addresses the query well with minor gaps
- 0.6-0.7: The answer partially addresses the query but misses important aspects
- 0.4-0.5: The answer is somewhat related but doesn't fully address the query
- 0.0-0.3: The answer does not address the query or is irrelevant

IMPORTANT: Respond with ONLY a decimal number between 0.0 and 1.0 (e.g., "0.85" or "1.0"), nothing else. No explanation, no text, just the number."""

        prompt = f"""Query: {query}

Answer: {answer}

Score (0.0-1.0):"""
        
        try:
            response = self._call_llm(prompt, system_instruction)
            score = self._parse_score(response, "relevance")
            return score
        except Exception as e:
            logger.error(f"Failed to evaluate relevance: {e}")
            return None
    
    def evaluate_faithfulness(
        self,
        answer: str,
        context: List[str],
    ) -> Optional[float]:
        """
        Evaluate answer faithfulness to the provided context.
        
        Uses LLM-as-a-judge to score how well the answer is grounded in the
        provided context on a scale of 0-1, where:
        - 1.0: Answer is fully supported by context
        - 0.5: Answer is partially supported by context
        - 0.0: Answer contains unsupported claims or contradicts context
        
        Args:
            answer: Generated answer from RAG system.
            context: List of context strings (retrieved chunks).
            
        Returns:
            Faithfulness score (0-1) or None if evaluation failed.
        """
        if not answer:
            logger.warning("Answer is empty, skipping faithfulness evaluation")
            return None
        
        if not context:
            logger.warning("No context provided, skipping faithfulness evaluation")
            return None
        
        # Combine context chunks
        context_text = "\n\n".join([f"[Context {i+1}]\n{chunk}" for i, chunk in enumerate(context[:5])])  # Limit to 5 chunks for token efficiency
        
        system_instruction = """You are an expert evaluator assessing answer faithfulness for a RAG (Retrieval-Augmented Generation) system.

Your task is to evaluate how well an answer is grounded in the provided context. Provide a score from 0.0 to 1.0 where:
- 1.0: All claims in the answer are fully supported by the context
- 0.8-0.9: Most claims are supported, minor unsupported details
- 0.6-0.7: Some claims are supported, but significant unsupported content
- 0.4-0.5: Answer contains substantial unsupported claims
- 0.0-0.3: Answer contradicts context or contains mostly unsupported claims

IMPORTANT: Respond with ONLY a decimal number between 0.0 and 1.0 (e.g., "0.85" or "1.0"), nothing else. No explanation, no text, just the number."""

        prompt = f"""Context:
{context_text}

Answer: {answer}

Score (0.0-1.0):"""
        
        try:
            response = self._call_llm(prompt, system_instruction)
            score = self._parse_score(response, "faithfulness")
            return score
        except Exception as e:
            logger.error(f"Failed to evaluate faithfulness: {e}")
            return None


class FallbackLLMClient:
    """
    Fallback LLM client using direct API calls when backend client is unavailable.
    
    This allows the evaluator to work standalone without importing backend code.
    """
    
    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
        self.provider = provider or self._detect_provider()
        self.model = model or self._get_default_model()
        self.api_key = self._get_api_key()
        
    def _detect_provider(self) -> str:
        """Auto-detect available provider."""
        if os.getenv("OPENROUTER_API_KEY"):
            return "openrouter"
        elif os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
            return "gemini"
        elif os.getenv("GOOGLE_CLOUD_PROJECT"):
            return "vertex"
        return "openrouter"  # Default
    
    def _get_default_model(self) -> str:
        """Get default model for provider."""
        if self.provider == "gemini":
            # Prefer 1.5-pro for widest compatibility on v1/v1beta; allow override.
            return os.getenv("EVAL_LLM_MODEL", "gemini-1.5-pro")
        elif self.provider == "openrouter":
            return os.getenv("EVAL_LLM_MODEL", "google/gemini-flash-1.5")
        return "gemini-1.5-pro"
    
    def _get_api_key(self) -> Optional[str]:
        """Get API key for provider."""
        if self.provider == "openrouter":
            return os.getenv("OPENROUTER_API_KEY")
        elif self.provider == "gemini":
            return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        return None
    
    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> str:
        """Generate response using direct API calls."""
        if self.provider == "openrouter":
            return self._call_openrouter(prompt, system_instruction, temperature, max_tokens, **kwargs)
        elif self.provider == "gemini":
            return self._call_gemini(prompt, system_instruction, temperature, max_tokens)
        else:
            raise RuntimeError(f"Unsupported provider: {self.provider}")
    
    def _call_openrouter(
        self,
        prompt: str,
        system_instruction: Optional[str],
        temperature: float,
        max_tokens: Optional[int],
        **kwargs,
    ) -> str:
        """Call OpenRouter API directly."""
        import json
        import requests
        
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})
        
        model = kwargs.get("model") or self.model
        
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens or 500,
            },
            timeout=60,
        )
        
        if response.status_code != 200:
            raise RuntimeError(f"OpenRouter API error: {response.status_code} - {response.text}")
        
        return response.json()["choices"][0]["message"]["content"]
    
    def _call_gemini(
        self,
        prompt: str,
        system_instruction: Optional[str],
        temperature: float,
        max_tokens: Optional[int],
    ) -> str:
        """
        Call Gemini API using REST API v1 directly (industry standard, stable, supports all models).
        
        This uses the official REST API v1 endpoint which is stable and production-ready.
        Works with all Gemini models without SDK version issues.
        """
        import requests
        
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY not set")
        
        # Choose candidate models - use ACTUAL available models from API
        # Verified available models: gemini-2.5-flash, gemini-2.5-pro (v1)
        user_model = self.model or os.getenv("EVAL_LLM_MODEL") or "gemini-2.5-flash"
        # Normalize (strip leading "models/")
        if user_model.startswith("models/"):
            user_model = user_model.replace("models/", "")

        candidate_models = []
        # Try user-provided first
        candidate_models.append(user_model)
        # Add ACTUAL available models as fallbacks (verified via API)
        for m in [
            "gemini-2.5-flash",      # Fast, cost-effective (v1 available)
            "gemini-2.5-pro",       # More capable (v1 available)
            "gemini-2.0-flash",      # Alternative (v1 available)
            "gemini-2.0-flash-001",  # Specific version (v1 available)
        ]:
            if m not in candidate_models:
                candidate_models.append(m)

        # Endpoints to try per model (v1 preferred, then v1beta fallback)
        api_versions = [
            ("v1", "https://generativelanguage.googleapis.com/v1/models/{model}:generateContent"),
            ("v1beta", "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"),
        ]
        
        headers = {
            "Content-Type": "application/json",
        }
        
        # Build contents array
        contents = []

        # Combine system instruction and prompt
        full_text = prompt
        if system_instruction:
            full_text = f"{system_instruction}\n\n{prompt}"

        contents.append({
            "role": "user",
            "parts": [{"text": full_text}]
        })

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens or 500,
            }
        }

        # API key in query parameter (standard REST API pattern)
        params = {"key": self.api_key}

        last_error = None

        for model_name in candidate_models:
            for api_version, url_template in api_versions:
                url = url_template.format(model=model_name)
                try:
                    response = requests.post(
                        url,
                        json=payload,
                        headers=headers,
                        params=params,
                        timeout=60,
                    )
                    response.raise_for_status()

                    data = response.json()

                    # Extract text from response
                    if "candidates" in data and len(data["candidates"]) > 0:
                        candidate = data["candidates"][0]
                        if "content" in candidate and "parts" in candidate["content"]:
                            parts = candidate["content"]["parts"]
                            if len(parts) > 0 and "text" in parts[0]:
                                return parts[0]["text"]

                    # Unexpected shape; treat as failure and continue to next
                    last_error = f"Unexpected response for {model_name} ({api_version}): {data}"
                except requests.exceptions.HTTPError as e:
                    # 404 -> try next api version / model
                    try:
                        error_data = e.response.json()
                        if "error" in error_data and "message" in error_data["error"]:
                            last_error = f"{api_version}/{model_name}: {error_data['error']['message']}"
                        else:
                            last_error = f"{api_version}/{model_name}: HTTP {e.response.status_code}"
                    except Exception:
                        last_error = f"{api_version}/{model_name}: HTTP {e.response.status_code}"
                    continue
                except requests.exceptions.RequestException as e:
                    last_error = f"{api_version}/{model_name}: {e}"
                    continue

        raise RuntimeError(f"Gemini API error: {last_error or 'No successful response'}")

