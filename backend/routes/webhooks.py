"""
Webhook endpoints for Make, n8n, Zapier, and other automation platforms.
"""

import hashlib
import logging
import os
from typing import Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Header, HTTPException, BackgroundTasks, File, UploadFile
from pydantic import BaseModel

from ai.llm_client import LLMClient
from config.settings import settings
from repositories.document_repository import DocumentRepository
from services.db.sqlite_service import get_db
from services.db.qdrant_service import get_qdrant_service
from services.embedding_service import embedding_service
from services.storage.file_storage import get_file_storage
from services.ingestion import process_document_background

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def _check_secret(secret: Optional[str]) -> None:
    webhook_secret = os.getenv("WEBHOOK_SECRET", "")
    if webhook_secret and secret != webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


class IngestUrlRequest(BaseModel):
    url: str
    doc_name: Optional[str] = None


class IngestUrlResponse(BaseModel):
    doc_id: str
    status: str
    doc_name: str


@router.post("/ingest-url", response_model=IngestUrlResponse, status_code=202)
async def ingest_from_url(
    body: IngestUrlRequest,
    background_tasks: BackgroundTasks,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
):
    """
    Download a file from a URL and queue it through the RAG ingestion pipeline.
    """
    _check_secret(x_webhook_secret)

    try:
        resp = httpx.get(body.url, timeout=30.0)
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to download file: {e}")

    content = resp.content
    filename = body.doc_name or body.url.split("/")[-1].split("?")[0] or "document.pdf"
    mime_type = resp.headers.get("Content-Type", "application/pdf").split(";")[0].strip()
    sha256_hash = hashlib.sha256(content).hexdigest()

    db = next(get_db())
    try:
        existing = DocumentRepository.get_by_sha256(db, sha256_hash)
        if existing:
            return IngestUrlResponse(
                doc_id=str(existing.doc_id),
                status=existing.status,
                doc_name=existing.doc_name,
            )

        document = DocumentRepository.create(
            session=db,
            sha256=sha256_hash,
            mime=mime_type,
            pages=0,
            source_uri=body.url,
            doc_name=filename,
            ingest_run_id=uuid4(),
            doc_type="pdf",
            embedding_id=settings.embedding_model,
            status="queued",
            version=1,
        )
        db.flush()

        get_file_storage().save_file(content, document.doc_id, mime_type)
        db.commit()

        background_tasks.add_task(process_document_background, str(document.doc_id))

        logger.info(f"Webhook queued document {document.doc_id} from {body.url}")
        return IngestUrlResponse(doc_id=str(document.doc_id), status="queued", doc_name=filename)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Webhook ingest failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ingest failed: {e}")
    finally:
        db.close()


@router.post("/upload-file", response_model=IngestUrlResponse, status_code=202)
async def upload_file(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
):
    """
    Upload a local file and queue it through the RAG ingestion pipeline.
    """
    _check_secret(x_webhook_secret)

    content = await file.read()
    filename = file.filename or "document.pdf"
    mime_type = file.content_type or "application/pdf"
    sha256_hash = hashlib.sha256(content).hexdigest()

    db = next(get_db())
    try:
        existing = DocumentRepository.get_by_sha256(db, sha256_hash)
        if existing:
            return IngestUrlResponse(
                doc_id=str(existing.doc_id),
                status=existing.status,
                doc_name=existing.doc_name,
            )

        document = DocumentRepository.create(
            session=db,
            sha256=sha256_hash,
            mime=mime_type,
            pages=0,
            source_uri=f"upload://{filename}",
            doc_name=filename,
            ingest_run_id=uuid4(),
            doc_type="pdf",
            embedding_id=settings.embedding_model,
            status="queued",
            version=1,
        )
        db.flush()

        get_file_storage().save_file(content, document.doc_id, mime_type)
        db.commit()

        background_tasks.add_task(process_document_background, str(document.doc_id))

        logger.info(f"Webhook queued uploaded document {document.doc_id}")
        return IngestUrlResponse(doc_id=str(document.doc_id), status="queued", doc_name=filename)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Webhook upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")
    finally:
        db.close()


class WebhookQueryRequest(BaseModel):
    question: str


class WebhookQueryResponse(BaseModel):
    answer: str
    sources: list[str]


@router.post("/query", response_model=WebhookQueryResponse)
async def webhook_query(
    body: WebhookQueryRequest,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
):
    """
    Run a RAG query and return an AI-generated answer as plain JSON.
    """
    _check_secret(x_webhook_secret)

    try:
        query_vector = await embedding_service.generate_embedding(body.question, mode="query")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {e}")

    results = get_qdrant_service().search(
        query_vector=query_vector,
        tenant_id="default",
        k=5,
        embedding_id=settings.embedding_model,
        filters={},
        acl_filter=None,
    )

    context_chunks = [r.get("text", "") for r in results if r.get("text")]
    source_ids = list({str(r.get("doc_id", "")) for r in results if r.get("doc_id")})

    if not context_chunks:
        return WebhookQueryResponse(
            answer="No relevant documents found. Ingest documents first.",
            sources=[],
        )

    context = "\n\n".join(context_chunks[:5])
    prompt = (
        "Answer the following question based only on the provided context. "
        "Be concise and accurate.\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {body.question}"
    )

    try:
        answer = LLMClient().generate_chat_response(prompt)
    except Exception as e:
        logger.error(f"LLM generation failed in query webhook: {e}")
        answer = context_chunks[0][:500]

    return WebhookQueryResponse(answer=answer, sources=source_ids)
