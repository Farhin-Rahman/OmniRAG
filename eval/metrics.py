"""
Metrics computation for OmniRAG Offline Evaluation.

Version: 2.0.0 - Industry-standard deterministic metrics.

This module provides functions and data structures for computing evaluation metrics:

1. **Retrieval Metrics** (document-level):
   - Recall@k, MRR@k, NDCG@k
   - Supports both exact (ID-based) and approximate (name-based) matching

2. **Answer Similarity Metrics** (deterministic, no LLM):
   - token_f1: Counter-based (multiset) token overlap
   - rouge_l: Optional ROUGE-L (behind flag)

3. **Citation Metrics** (conservative):
   - has_any_citation, total_citations

4. **Latency Metrics** (from trace steps):
   - Embedding, retrieval, LLM, end-to-end latencies

5. **LLM-based Quality Metrics** (optional, OFF by default):
   - Answer Relevance, Faithfulness via LLM-as-a-Judge

Example:
    from eval.metrics import compute_per_case_metrics, aggregate_metrics
    
    metrics = compute_per_case_metrics(
        test_case_id="test-1",
        golden_docs=["policy.pdf"],
        retrieved_sources=response.sources,
        query="What is the vacation policy?",
        answer=response.answer,
        http_latency_ms=response.http_latency_ms,
    )
"""

import logging
import math
import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from eval.client import Source

logger = logging.getLogger(__name__)


@dataclass
class PerCaseMetrics:
    """
    Metrics computed for a single evaluation test case.
    
    Attributes:
        id: Test case identifier.
        
        # Retrieval metrics
        doc_recall: Fraction of golden docs retrieved (name-based if approx).
        doc_precision: Fraction of retrieved docs in golden set.
        doc_f1: F1 combining precision and recall.
        mrr: Mean Reciprocal Rank.
        ndcg_at_k: Normalized Discounted Cumulative Gain.
        retrieval_metric_type: "exact" (ID-based) or "approx" (name-based).
        
        # Answer similarity (deterministic)
        token_f1: Counter-based token F1 score.
        rouge_l: ROUGE-L F1 score (optional).
        
        # Citation metrics
        has_any_citation: 1 if any citations, 0 otherwise.
        total_citations: Count of citations.
        
        # LLM-based (optional)
        answer_relevance: LLM-as-judge relevance (0-1).
        faithfulness: LLM-as-judge faithfulness (0-1).
        
        # Latency
        http_latency_ms: HTTP wall-clock latency.
        embedding_ms, retrieval_ms, llm_ms, e2e_ms: Trace latencies.
        
        # Debug info
        retrieved_doc_names, golden_doc_names: For debugging.
        error: Error message if evaluation failed.
    """
    id: str
    
    # Retrieval metrics
    doc_recall: Optional[float] = None
    doc_precision: Optional[float] = None
    doc_f1: Optional[float] = None
    mrr: Optional[float] = None
    ndcg_at_k: Optional[float] = None
    retrieval_metric_type: str = "none"  # "exact", "approx", or "none"
    
    # Answer similarity (deterministic)
    token_f1: Optional[float] = None
    rouge_l: Optional[float] = None
    
    # Citation metrics
    has_any_citation: Optional[int] = None
    total_citations: Optional[int] = None
    
    # LLM-based (optional)
    answer_relevance: Optional[float] = None
    faithfulness: Optional[float] = None
    
    # Latency
    http_latency_ms: Optional[float] = None
    embedding_ms: Optional[float] = None
    retrieval_ms: Optional[float] = None
    llm_ms: Optional[float] = None
    e2e_ms: Optional[float] = None
    
    # Debug info
    retrieved_doc_names: List[str] = field(default_factory=list)
    golden_doc_names: List[str] = field(default_factory=list)
    error: Optional[str] = None


# =============================================================================
# Text Normalization for Token F1
# =============================================================================
def normalize_text_for_f1(text: str) -> str:
    """Normalize text for token F1 comparison."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)  # Remove punctuation
    return ' '.join(text.split())  # Normalize whitespace


def compute_token_f1(predicted: str, expected: str) -> Optional[float]:
    """
    Counter-based (multiset) token F1 score.
    
    Handles duplicate tokens correctly. Empty strings are handled:
    - Both empty = 1.0 (perfect match)
    - One empty = 0.0 (no match)
    - Punctuation-only normalizes to empty
    """
    if not predicted and not expected:
        return 1.0
    if not predicted or not expected:
        return 0.0
    
    pred_norm = normalize_text_for_f1(predicted)
    exp_norm = normalize_text_for_f1(expected)
    
    if not pred_norm and not exp_norm:
        return 1.0  # Both became empty after normalization
    if not pred_norm or not exp_norm:
        return 0.0
    
    pred_tokens = Counter(pred_norm.split())
    exp_tokens = Counter(exp_norm.split())
    
    # Multiset intersection
    common = sum((pred_tokens & exp_tokens).values())
    precision = common / sum(pred_tokens.values()) if pred_tokens else 0.0
    recall = common / sum(exp_tokens.values()) if exp_tokens else 0.0
    
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def compute_rouge_l(predicted: str, expected: str) -> Optional[float]:
    """
    Compute ROUGE-L F1 score (optional, requires rouge-score package).
    
    Returns None if package not available.
    """
    if not predicted or not expected:
        return None
    try:
        from rouge_score import rouge_scorer
        scorer = rouge_scorer.RougeScorer(['rougeL'], use_stemmer=True)
        scores = scorer.score(expected, predicted)
        return scores['rougeL'].fmeasure
    except ImportError:
        logger.debug("rouge-score not installed, skipping ROUGE-L")
        return None
    except Exception as e:
        logger.warning(f"ROUGE-L computation failed: {e}")
        return None


# =============================================================================
# Ranking Metrics (MRR, NDCG)
# =============================================================================
def compute_mrr(golden_set: set, retrieved_list: List[str]) -> float:
    """
    Mean Reciprocal Rank.
    
    Returns 1/rank of first relevant result, or 0 if none found.
    """
    for i, doc in enumerate(retrieved_list, 1):
        if doc in golden_set:
            return 1.0 / i
    return 0.0


def compute_ndcg(golden_set: set, retrieved_list: List[str], k: int = 10) -> float:
    """
    Normalized Discounted Cumulative Gain at k.
    
    Uses binary relevance (1 if in golden, 0 otherwise).
    """
    retrieved_k = retrieved_list[:k]
    relevances = [1.0 if doc in golden_set else 0.0 for doc in retrieved_k]
    
    # DCG
    dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances))
    
    # Ideal DCG (all relevant first)
    ideal_count = min(len(golden_set), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))
    
    return dcg / idcg if idcg > 0 else 0.0


# =============================================================================
# Citation Metrics (Conservative)
# =============================================================================
def extract_compact_citations(citations: List[Dict]) -> List[Dict]:
    """
    Extract only essential citation fields (no full text).
    
    Returns compact citations with: doc_id, doc_name, page, span, chunk_id, confidence.
    """
    return [
        {
            "doc_id": c.get("doc_id"),
            "doc_name": c.get("doc_name") or c.get("document_name"),
            "page": c.get("page"),
            "span": c.get("span"),
            "chunk_id": c.get("chunk_id"),
            "confidence": c.get("confidence"),
        }
        for c in (citations or [])
    ]


def compute_citation_metrics(citations: List[Dict]) -> Dict[str, Any]:
    """
    Conservative citation metrics using structured data.
    
    Does NOT rely on bracket detection in text.
    """
    return {
        "has_any_citation": 1 if citations else 0,
        "total_citations": len(citations or []),
    }


# =============================================================================
# Document Name Normalization
# =============================================================================
def normalize_doc_name(name: str) -> str:
    """
    Normalize document name for comparison.
    
    Strips whitespace, removes file extensions, and converts to lowercase
    for case-insensitive matching.
    """
    if not name:
        return ""
    
    # Remove file extensions (.pdf, .docx, etc.)
    name = re.sub(r'\.(pdf|docx?|txt|md|html?)$', '', name, flags=re.IGNORECASE)
    
    # Remove underscores
    name = name.replace('_', ' ')
    
    # Remove special characters except spaces (keep Arabic characters)
    name = re.sub(r'[^\w\s]', ' ', name, flags=re.UNICODE)
    
    # Normalize: strip, lowercase, remove extra spaces
    name = re.sub(r'\s+', ' ', name.strip().lower())
    
    return name


def extract_english_words(text: str) -> set:
    """Extract significant English words (3+ chars, no numbers) from text."""
    words = set()
    for word in text.split():
        if word.isascii() and len(word) >= 3 and not word.isdigit():
            words.add(word.lower())
    return words


def words_match_fuzzy(word1: str, word2: str) -> bool:
    """Check if two words match fuzzily (handles plurals, stems)."""
    if word1 == word2:
        return True
    
    min_len = min(len(word1), len(word2))
    if min_len >= 3:
        prefix_len = int(min_len * 0.8)
        if word1[:prefix_len] == word2[:prefix_len]:
            return True
    
    return False


# =============================================================================
# Retrieval Metrics (Unified)
# =============================================================================
def compute_retrieval_metrics(
    golden_docs: Optional[List[str]],
    golden_doc_ids: Optional[List[str]],
    retrieved_sources: List[Source],
) -> Tuple[Dict[str, float], str]:
    """
    Compute retrieval metrics with approx_ prefix when using names.
    
    Args:
        golden_docs: Expected doc names (approximate matching).
        golden_doc_ids: Expected doc IDs (exact matching, preferred).
        retrieved_sources: Sources returned by RAG.
        
    Returns:
        Tuple of (metrics_dict, metric_type).
        metric_type is "exact" if using IDs, "approx" if using names, "none" if no golden.
    """
    # Extract retrieved
    retrieved_names = list({s.doc_name for s in retrieved_sources if s.doc_name})
    retrieved_ids = [s.doc_id for s in retrieved_sources if s.doc_id]
    
    if golden_doc_ids:
        # Exact matching by ID
        golden_set = set(golden_doc_ids)
        retrieved_list = retrieved_ids
        metric_type = "exact"
        prefix = ""
    elif golden_docs:
        # Approximate matching by normalized name
        golden_set = {normalize_doc_name(d) for d in golden_docs}
        retrieved_list = [normalize_doc_name(d) for d in retrieved_names]
        metric_type = "approx"
        prefix = "approx_"
    else:
        return {}, "none"
    
    if not golden_set:
        return {}, "none"
    
    # Compute fuzzy matches for name-based
    if metric_type == "approx":
        true_positives = 0
        for golden in golden_set:
            golden_words = extract_english_words(golden)
            if not golden_words:
                # No English words, try exact match
                if golden in retrieved_list:
                    true_positives += 1
                continue
            
            for retrieved in retrieved_list:
                # Check exact match first
                if golden == retrieved:
                    true_positives += 1
                    break
                
                # Check fuzzy word match
                retrieved_words = extract_english_words(retrieved)
                if not retrieved_words:
                    continue
                
                matched = sum(1 for gw in golden_words 
                             for rw in retrieved_words 
                             if words_match_fuzzy(gw, rw))
                if matched >= max(1, len(golden_words) * 0.4):
                    true_positives += 1
                    break
    else:
        # Exact ID matching
        true_positives = len(golden_set & set(retrieved_list))
    
    # Recall
    recall = true_positives / len(golden_set) if golden_set else 0.0
    
    # Precision
    precision = true_positives / len(retrieved_list) if retrieved_list else 0.0
    
    # F1
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    
    # MRR and NDCG (use normalized list for approx)
    match_set = golden_set if metric_type == "exact" else golden_set
    match_list = retrieved_list
    
    mrr = compute_mrr(match_set, match_list)
    ndcg = compute_ndcg(match_set, match_list)
    
    return {
        f"{prefix}doc_recall": recall,
        f"{prefix}doc_precision": precision,
        f"{prefix}doc_f1": f1,
        f"{prefix}mrr": mrr,
        f"{prefix}ndcg_at_k": ndcg,
    }, metric_type


def compute_retrieval_metrics_legacy(
    golden_docs: Optional[List[str]],
    retrieved_sources: List[Source],
) -> Tuple[Optional[float], Optional[float], Optional[float], List[str]]:
    """
    Legacy retrieval metrics (backward compatibility).
    
    Returns (recall, precision, f1, retrieved_doc_names).
    """
    metrics, _ = compute_retrieval_metrics(golden_docs, None, retrieved_sources)
    retrieved_names = list({s.doc_name for s in retrieved_sources if s.doc_name})
    
    if not metrics:
        return None, None, None, retrieved_names
    
    # Extract values (might have approx_ prefix)
    recall = metrics.get("doc_recall") or metrics.get("approx_doc_recall")
    precision = metrics.get("doc_precision") or metrics.get("approx_doc_precision")
    f1 = metrics.get("doc_f1") or metrics.get("approx_doc_f1")
    
    return recall, precision, f1, retrieved_names


# =============================================================================
# Latency Metrics
# =============================================================================
def extract_latency_from_trace(
    trace_data: Optional[Dict[str, Any]],
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    Extract latency metrics from trace steps.
    
    Returns (embedding_ms, retrieval_ms, llm_ms, e2e_ms).
    """
    if not trace_data:
        return None, None, None, None
    
    steps = trace_data.get("steps", [])
    if not steps:
        return None, None, None, None
    
    embedding_ms: Optional[float] = None
    retrieval_ms: Optional[float] = None
    llm_ms: Optional[float] = None
    e2e_ms: Optional[float] = None
    
    for step in steps:
        step_name = step.get("step", "")
        lat_ms = step.get("lat_ms")
        
        if lat_ms is None:
            continue
        
        lat_ms = float(lat_ms)
        
        if step_name == "query_embedding_generated":
            embedding_ms = lat_ms
        elif step_name in ("vector_search_completed", "qdrant_search"):
            retrieval_ms = lat_ms
        elif step_name == "llm_response_generated":
            llm_ms = lat_ms
        elif step_name == "messages_persisted":
            e2e_ms = lat_ms
    
    return embedding_ms, retrieval_ms, llm_ms, e2e_ms


# =============================================================================
# LLM-based Metrics (Optional)
# =============================================================================
def compute_llm_metrics(
    query: str,
    answer: str,
    context: List[str],
    golden_answer: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Compute LLM-based quality metrics using LLM-as-a-judge.
    
    Returns (answer_relevance, faithfulness).
    """
    try:
        from eval.llm_evaluator import LLMEvaluator
    except ImportError as e:
        logger.warning(f"LLM evaluator not available: {e}")
        return None, None
    
    if not query or not answer:
        return None, None
    
    try:
        import os
        model_name = model or os.getenv("EVAL_LLM_MODEL")
        
        evaluator = LLMEvaluator(
            provider=provider,
            model=model_name,
            temperature=0.0,
        )
        
        answer_relevance = evaluator.evaluate_relevance(query=query, answer=answer)
        faithfulness = None
        if context:
            faithfulness = evaluator.evaluate_faithfulness(answer=answer, context=context)
        
        return answer_relevance, faithfulness
        
    except Exception as e:
        logger.error(f"LLM metrics computation failed: {e}")
        return None, None


# =============================================================================
# Per-Case Metrics Computation
# =============================================================================
def compute_per_case_metrics(
    test_case_id: str,
    golden_docs: Optional[List[str]],
    retrieved_sources: List[Source],
    query: str,
    answer: str,
    http_latency_ms: float,
    trace_data: Optional[Dict[str, Any]] = None,
    golden_answer: Optional[str] = None,
    golden_doc_ids: Optional[List[str]] = None,
    citations: Optional[List[Dict]] = None,
    enable_llm_eval: bool = False,
    enable_rouge: bool = False,
    llm_eval_model: Optional[str] = None,
    llm_eval_provider: Optional[str] = None,
) -> PerCaseMetrics:
    """
    Compute all metrics for a single test case.
    """
    # Retrieval metrics
    retrieval_metrics, metric_type = compute_retrieval_metrics(
        golden_docs, golden_doc_ids, retrieved_sources
    )
    
    # Extract values based on prefix
    prefix = "approx_" if metric_type == "approx" else ""
    doc_recall = retrieval_metrics.get(f"{prefix}doc_recall")
    doc_precision = retrieval_metrics.get(f"{prefix}doc_precision")
    doc_f1 = retrieval_metrics.get(f"{prefix}doc_f1")
    mrr = retrieval_metrics.get(f"{prefix}mrr")
    ndcg = retrieval_metrics.get(f"{prefix}ndcg_at_k")
    
    # Latency from trace
    embedding_ms, retrieval_ms, llm_ms, e2e_ms = extract_latency_from_trace(trace_data)
    
    # Token F1 (deterministic)
    token_f1_score = compute_token_f1(answer, golden_answer) if golden_answer else None
    
    # ROUGE-L (optional)
    rouge_l_score = None
    if enable_rouge and golden_answer:
        rouge_l_score = compute_rouge_l(answer, golden_answer)
    
    # Citation metrics
    citation_metrics = compute_citation_metrics(citations or [])
    
    # LLM metrics (optional)
    answer_relevance: Optional[float] = None
    faithfulness: Optional[float] = None
    if enable_llm_eval:
        context = [s.text for s in retrieved_sources if s.text]
        answer_relevance, faithfulness = compute_llm_metrics(
            query=query,
            answer=answer,
            context=context,
            golden_answer=golden_answer,
            model=llm_eval_model,
            provider=llm_eval_provider,
        )
    
    retrieved_names = list({s.doc_name for s in retrieved_sources if s.doc_name})
    
    return PerCaseMetrics(
        id=test_case_id,
        doc_recall=doc_recall,
        doc_precision=doc_precision,
        doc_f1=doc_f1,
        mrr=mrr,
        ndcg_at_k=ndcg,
        retrieval_metric_type=metric_type,
        token_f1=token_f1_score,
        rouge_l=rouge_l_score,
        has_any_citation=citation_metrics["has_any_citation"],
        total_citations=citation_metrics["total_citations"],
        answer_relevance=answer_relevance,
        faithfulness=faithfulness,
        http_latency_ms=http_latency_ms,
        embedding_ms=embedding_ms,
        retrieval_ms=retrieval_ms,
        llm_ms=llm_ms,
        e2e_ms=e2e_ms,
        retrieved_doc_names=retrieved_names,
        golden_doc_names=golden_docs or [],
    )


# =============================================================================
# Percentile Calculation
# =============================================================================
def percentile(values: List[float], p: float) -> float:
    """Compute the p-th percentile of a list of values."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    k = (len(sorted_values) - 1) * (p / 100)
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_values) else f
    if f == c:
        return sorted_values[f]
    return sorted_values[f] * (c - k) + sorted_values[c] * (k - f)


# =============================================================================
# Metrics Aggregation
# =============================================================================
def aggregate_metrics(metrics_list: List[PerCaseMetrics]) -> Dict[str, float]:
    """
    Aggregate metrics across all test cases.
    
    Computes mean values for each metric and percentiles for latency.
    """
    if not metrics_list:
        return {"total_cases": 0}
    
    def collect_values(attr: str) -> List[float]:
        return [getattr(m, attr) for m in metrics_list if getattr(m, attr) is not None]
    
    result: Dict[str, float] = {}
    
    # Retrieval metrics
    for metric_name in ["doc_recall", "doc_precision", "doc_f1", "mrr", "ndcg_at_k"]:
        values = collect_values(metric_name)
        if values:
            result[f"mean_{metric_name}"] = statistics.mean(values)
    
    # Answer similarity
    for metric_name in ["token_f1", "rouge_l"]:
        values = collect_values(metric_name)
        if values:
            result[f"mean_{metric_name}"] = statistics.mean(values)
    
    # LLM metrics
    for metric_name in ["answer_relevance", "faithfulness"]:
        values = collect_values(metric_name)
        if values:
            result[f"mean_{metric_name}"] = statistics.mean(values)
    
    # Citation metrics
    citations = collect_values("has_any_citation")
    if citations:
        result["citation_rate"] = sum(citations) / len(citations)
    
    # Latency with percentiles (all stages)
    for metric_name in ["http_latency_ms", "e2e_ms", "embedding_ms", "retrieval_ms", "llm_ms"]:
        values = collect_values(metric_name)
        if values:
            result[f"mean_{metric_name}"] = statistics.mean(values)
            result[f"p50_{metric_name}"] = percentile(values, 50)
            result[f"p90_{metric_name}"] = percentile(values, 90)
            if metric_name in ["http_latency_ms", "e2e_ms"]:
                result[f"p95_{metric_name}"] = percentile(values, 95)
    
    # Counts
    result["total_cases"] = float(len(metrics_list))
    result["cases_with_errors"] = float(sum(1 for m in metrics_list if m.error))
    result["cases_with_golden_docs"] = float(sum(1 for m in metrics_list if m.golden_doc_names))
    
    return result


# =============================================================================
# Failure Score Computation
# =============================================================================
def compute_failure_score(metrics: PerCaseMetrics) -> Tuple[float, List[str]]:
    """
    Compute failure score with clear rules.
    
    Returns (score, reason_codes).
    """
    score = 0.0
    reasons = []
    
    if metrics.error:
        score += 2.0
        reasons.append("error")
    
    if metrics.doc_recall is not None:
        score += (1.0 - metrics.doc_recall)
    else:
        score += 0.25
        reasons.append("missing_doc_recall")
    
    if metrics.token_f1 is not None:
        score += (1.0 - metrics.token_f1)
    else:
        score += 0.25
        reasons.append("missing_token_f1")
    
    return score, reasons


# =============================================================================
# Serialization
# =============================================================================
def metrics_to_dict(metrics: PerCaseMetrics) -> Dict[str, Any]:
    """Convert PerCaseMetrics to a dict for JSON/CSV serialization."""
    return {
        "id": metrics.id,
        "doc_recall": metrics.doc_recall,
        "doc_precision": metrics.doc_precision,
        "doc_f1": metrics.doc_f1,
        "mrr": metrics.mrr,
        "ndcg_at_k": metrics.ndcg_at_k,
        "retrieval_metric_type": metrics.retrieval_metric_type,
        "token_f1": metrics.token_f1,
        "rouge_l": metrics.rouge_l,
        "has_any_citation": metrics.has_any_citation,
        "total_citations": metrics.total_citations,
        "answer_relevance": metrics.answer_relevance,
        "faithfulness": metrics.faithfulness,
        "http_latency_ms": metrics.http_latency_ms,
        "embedding_ms": metrics.embedding_ms,
        "retrieval_ms": metrics.retrieval_ms,
        "llm_ms": metrics.llm_ms,
        "e2e_ms": metrics.e2e_ms,
        "retrieved_doc_names": metrics.retrieved_doc_names,
        "golden_doc_names": metrics.golden_doc_names,
        "error": metrics.error,
    }
