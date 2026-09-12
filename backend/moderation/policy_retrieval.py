"""Policy-grounded retrieval for campaign risk assessment.

Embeds a campaign's text, retrieves the most relevant Trust & Safety
policy passages from Qdrant, and formats them for the risk-assessment
prompt — the same embedding/Qdrant infrastructure the RAG chat feature
uses (services/embedding_service.py, services/db/qdrant_service.py),
pointed at a separate `policy_docs` collection instead of ingested
documents. This is what makes the risk assessment cite actual policy
instead of the model's general sense of "seems risky."

Ingestion is a one-time setup step, not part of the request path:

    python -m moderation.policy_retrieval

(run inside the backend container, or anywhere QDRANT_HOST/OLLAMA_BASE_URL
resolve — see README).
"""

import logging
import re
from pathlib import Path

from qdrant_client import models

from services.db.qdrant_service import QdrantService, get_qdrant_service
from services.embedding_service import embedding_service

logger = logging.getLogger(__name__)

POLICY_COLLECTION = "policy_docs"
POLICY_DOCS_DIR = Path(__file__).parent / "policy_docs"


def _chunk_markdown(text: str, source: str) -> list[dict]:
    """One chunk per '##' section — small, coherent, retrievable units."""
    sections = re.split(r"\n(?=## )", text.strip())
    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        title_match = re.match(r"^#+\s*(.+)", section)
        title = title_match.group(1) if title_match else source
        chunks.append({"title": title, "text": section, "source": source})
    return chunks


def _embed(text: str) -> list[float]:
    # generate_embedding is declared async but its implementation
    # (_call_ollama) is fully synchronous — the moderation pipeline is
    # synchronous throughout (graph.py never awaits), running inside a
    # FastAPI request's already-active event loop, where asyncio.run()
    # would raise. Calling the sync implementation directly avoids that.
    return embedding_service._call_ollama(text)


def ingest_policy_docs() -> int:
    """Chunk, embed, and upsert every policy doc into the policy_docs
    Qdrant collection. Safe to re-run — deterministic IDs, upsert."""
    QdrantService().create_collection_if_not_exists(POLICY_COLLECTION)

    all_chunks: list[dict] = []
    for path in sorted(POLICY_DOCS_DIR.glob("*.md")):
        all_chunks.extend(_chunk_markdown(path.read_text(encoding="utf-8"), path.stem))

    points = [
        models.PointStruct(id=i, vector=_embed(chunk["text"]), payload=chunk)
        for i, chunk in enumerate(all_chunks)
    ]

    get_qdrant_service().client.upsert(collection_name=POLICY_COLLECTION, points=points)
    logger.info(f"Ingested {len(points)} policy chunks into '{POLICY_COLLECTION}'")
    return len(points)


def retrieve_policy_context(campaign_text: str, k: int = 3) -> str:
    """Top-k most relevant policy passages for this campaign, formatted
    for the risk-assessment prompt. Empty string (not an exception) on
    any failure — grounding is an enhancement the pipeline degrades
    gracefully without, not a hard dependency."""
    try:
        vector = _embed(campaign_text)
        hits = get_qdrant_service().client.query_points(
            collection_name=POLICY_COLLECTION,
            query=vector,
            limit=k,
            with_payload=True,
        )
        points = getattr(hits, "points", []) or []
        if not points:
            return ""
        return "\n\n".join(
            f"[{p.payload.get('title', 'policy')}] {p.payload.get('text', '')}"
            for p in points
        )
    except Exception as e:
        logger.warning(f"Policy retrieval failed, continuing without grounding: {e}")
        return ""


if __name__ == "__main__":
    n = ingest_policy_docs()
    print(f"Ingested {n} policy chunks into '{POLICY_COLLECTION}'.")
