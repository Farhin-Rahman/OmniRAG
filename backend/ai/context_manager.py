"""Context and token budget management for RAG."""

import logging
from typing import List, Dict, Any
from collections import defaultdict

logger = logging.getLogger(__name__)


class ContextBudgetManager:
    """Manages context budget for LLM prompts with MMR diversification."""

    def __init__(self, max_tokens: int = 4000, chars_per_token: float = 4.0):
        """
        Initialize context budget manager.

        Args:
            max_tokens: Maximum tokens for context
            chars_per_token: Average characters per token (approximation)
        """
        self.max_tokens = max_tokens
        self.chars_per_token = chars_per_token
        self.max_chars = int(max_tokens * chars_per_token)

    def select_diverse_chunks(
        self,
        chunks: List[Dict[str, Any]],
        query: str,
        lambda_param: float = 0.5,
        per_doc_limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Select diverse chunks using Maximum Marginal Relevance (MMR).

        Args:
            chunks: List of chunk dictionaries with 'text', 'score', 'doc_id'
            query: Original query
            lambda_param: Balance between relevance (1.0) and diversity (0.0)
            per_doc_limit: Maximum chunks per document

        Returns:
            Selected diverse chunks within budget
        """
        if not chunks:
            return []

        # Sort by relevance score
        sorted_chunks = sorted(chunks, key=lambda x: x.get("score", 0), reverse=True)

        selected = []
        selected_texts = []
        char_count = 0
        doc_counts = defaultdict(int)

        for chunk in sorted_chunks:
            doc_id = chunk.get("doc_id")
            chunk_text = chunk.get("text", "")
            chunk_len = len(chunk_text)

            # Check budget constraints
            if char_count + chunk_len > self.max_chars:
                logger.info(
                    f"Context budget reached: {char_count}/{self.max_chars} chars"
                )
                break

            # Check per-document limit
            if doc_counts[doc_id] >= per_doc_limit:
                continue

            # Calculate MMR score if we have selected chunks
            if selected_texts:
                relevance = chunk.get("score", 0)
                max_sim = self._max_similarity(chunk_text, selected_texts)
                mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim
            else:
                mmr_score = chunk.get("score", 0)

            # Add chunk if it passes MMR threshold
            if not selected or mmr_score > 0.3:  # threshold
                selected.append(chunk)
                selected_texts.append(chunk_text)
                char_count += chunk_len
                doc_counts[doc_id] += 1

        logger.info(
            f"Selected {len(selected)} chunks from {len(doc_counts)} documents, "
            f"total chars: {char_count}"
        )
        return selected

    def _max_similarity(self, text: str, selected_texts: List[str]) -> float:
        """
        Simple text similarity based on word overlap.
        In production, use proper embeddings.
        """
        words1 = set(text.lower().split())
        max_sim = 0.0

        for selected in selected_texts:
            words2 = set(selected.lower().split())
            if len(words1) == 0 or len(words2) == 0:
                continue
            intersection = len(words1 & words2)
            union = len(words1 | words2)
            similarity = intersection / union if union > 0 else 0
            max_sim = max(max_sim, similarity)

        return max_sim

    def budget_for_history(
        self, history: List[Dict[str, str]], reserve_chars: int = 2000
    ) -> List[Dict[str, str]]:
        """
        Trim conversation history to fit within budget.

        Args:
            history: Conversation history
            reserve_chars: Characters to reserve for context and response

        Returns:
            Trimmed history that fits budget
        """
        available = self.max_chars - reserve_chars

        # Start from most recent messages
        selected = []
        char_count = 0

        for msg in reversed(history):
            msg_len = len(msg.get("content", ""))
            if char_count + msg_len > available:
                break
            selected.append(msg)
            char_count += msg_len

        return list(reversed(selected))
