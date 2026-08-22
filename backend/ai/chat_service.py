import logging
from typing import List, Dict
from uuid import uuid4
from datetime import datetime, timezone

from schemas.chat import ChatRequest
from ai.llm_client import LLMClient
from services.embedding_service import embedding_service
from services.db.qdrant_service import get_qdrant_service
from config.settings import settings

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self):
        self.llm_client = LLMClient()
        self.qdrant = get_qdrant_service()

    async def chat(self, request: ChatRequest):
        """Stateless RAG query for automation backend."""
        query_id = uuid4()
        session_id = request.session_id or str(uuid4())
        conversation_id = request.conversation_id or str(uuid4())

        logger.info(f"Received stateless chat request for conversation {conversation_id}")

        start_time = datetime.now(timezone.utc)
        
        # 1. Embed query
        query_vector = await embedding_service.generate_embedding(request.message, mode="query")
        
        # 2. Search Qdrant
        search_results = self.qdrant.search(
            query_vector=query_vector,
            tenant_id="default",  # We removed tenants
            k=10,
            embedding_id=settings.embedding_model,
            filters={},
            acl_filter=None,
        )

        context_chunks = [r.get("text") or r.get("content") for r in search_results if (r.get("text") or r.get("content"))]
        
        if not context_chunks:
            answer = "No relevant documents found. Please ingest some documents first."
            sources = []
        else:
            context = "\n\n---\n\n".join(context_chunks[:5])
            prompt = (
                "Answer the following question based only on the provided context. "
                "Be concise and accurate.\n\n"
                f"Context:\n{context}\n\n"
                f"Question: {request.message}"
            )

            try:
                answer = self.llm_client.generate_chat_response(prompt)
            except Exception as e:
                logger.error(f"LLM generation failed: {e}")
                answer = "Error communicating with LLM."

            sources = []
            for r in search_results[:5]:
                sources.append({
                    "chunk_id": str(r.get("chunk_id", "")),
                    "doc_id": str(r.get("doc_id", "")),
                    "text": (r.get("text") or r.get("content") or "")[:500],
                    "page": r.get("page", 1),
                    "score": float(r.get("score", 0.0)),
                    "metadata": {"doc_name": r.get("doc_name", "Unknown")}
                })

        total_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

        return {
            "data": {
                "session_id": session_id,
                "conversation_id": conversation_id,
                "message": {
                    "id": str(uuid4()),
                    "role": "assistant",
                    "content": answer,
                },
                "citations": [],
                "sources": sources,
                "trace_id": str(query_id),
                "trace_summary": {"total_ms": total_ms}
            }
        }
