import hashlib
import logging
import mimetypes
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from config.settings import settings
from repositories.document_repository import DocumentRepository
from repositories.trace_repository import TraceRepository
from worker.ingestion import (
    create_chunks,
    upsert_vectors,
)
from services.event_publisher import publish_event
from schemas.events import IngestedDocumentEvent
from schemas.document import DocumentResponse
from services.batch_ingestion_service import get_batch_ingestion_service
from celery import chain
from schemas.contracts import (
    Answer,
    Citation,
    Document as DocumentSchema,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    Retrieval,
    Support,
    Trace as TraceSchema,
)
from services.db.postgres_service import get_db
from services.db.qdrant_service import get_qdrant_service
from services.embedding_service import embedding_service
from services.storage.file_storage import get_file_storage
from sqlalchemy.orm import Session
from routes.auth import get_current_user
from models.base import DocumentACL, User
from utils.download_tokens import generate_download_token, validate_download_token
from utils.errors import InvalidDownloadTokenError
from services.request_context import (
    RequestContext,
    get_request_context,
    get_request_context_optional,
    require_admin,
    require_write_access,
)
from services.acl_service import (
    can_user_access_document,
    get_user_group_ids,
    build_qdrant_acl_filter,
)
from ai.routing_service import get_routing_service

logger = logging.getLogger(__name__)

router = APIRouter()
routing_service = get_routing_service()


def require_role(allowed_roles: List[str], user: User = Depends(get_current_user)):
    """
    Dependency to check if user has one of the allowed roles.

    Args:
        allowed_roles: List of allowed role names (e.g., ["admin", "user"])
        user: Current authenticated user (from JWT token)

    Returns:
        User object if role check passes

    Raises:
        HTTPException: 403 if user doesn't have required role
    """
    if not user.role or user.role.lower() not in [r.lower() for r in allowed_roles]:
        raise HTTPException(
            status_code=403,
            detail=f"Insufficient permissions. Required roles: {', '.join(allowed_roles)}",
        )
    return user


def require_user_role(user: User = Depends(get_current_user)):
    """Require user to have 'member' or 'admin' role (accepts legacy 'user')."""
    return require_role(["member", "user", "admin"], user)


def require_admin_role(user: User = Depends(get_current_user)):
    """Require user to have 'admin' role."""
    return require_role(["admin"], user)


class DeleteDocumentResponse(BaseModel):
    """Response for document deletion."""

    doc_id: UUID
    deleted: bool
    qdrant_deleted: bool
    file_deleted: bool


@router.get("/healthz", response_model=HealthResponse)
async def get_health():
    """Health check endpoint - no auth required"""
    return HealthResponse(status="ok", version="0.1.0", git_sha="abc123def456")


@router.post("/ingest", response_model=DocumentSchema, status_code=201)
async def ingest_document(
    file: UploadFile = File(...),
    doc_name: Optional[str] = Form(None),
    doc_type: Optional[str] = Form(None),
    source_uri: Optional[str] = Form(None),
    ctx: RequestContext = Depends(require_write_access),  # Members+ can ingest
    db: Session = Depends(get_db),
):
    """
    Ingest a document - persists to database and returns Document with status=queued.

    Requires write access (admin or member role).

    This endpoint:
    1. Validates authentication and tenant from JWT
    2. Computes SHA256 hash of file content
    3. Checks for duplicate via SHA256
    4. Creates Document record in database
    5. Returns persisted document (file content stored separately)
    """

    # Check file size limit (100MB)
    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB in bytes
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)  # Reset to beginning

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File size ({file_size / 1024 / 1024:.2f}MB) exceeds maximum allowed size ({MAX_FILE_SIZE / 1024 / 1024}MB)",
        )

    # Read file content and compute hash
    content = await file.read()
    sha256_hash = hashlib.sha256(content).hexdigest()
    tenant_uuid = ctx.tenant_id  # From JWT via RequestContext

    # Check for duplicate document
    existing_doc = DocumentRepository.get_by_sha256(db, sha256_hash, tenant_uuid)
    if existing_doc:
        # Verify file still exists
        file_storage = get_file_storage()
        if file_storage.file_exists(existing_doc.doc_id, existing_doc.mime):
            # Return existing document (deduplication)
            db.commit()
            return DocumentSchema(
                doc_id=existing_doc.doc_id,
                sha256=existing_doc.sha256,
                mime=existing_doc.mime,
                pages=existing_doc.pages,
                source_uri=existing_doc.source_uri,
                doc_name=existing_doc.doc_name,
                ingest_run_id=existing_doc.ingest_run_id,
                doc_type=existing_doc.doc_type,
                status=existing_doc.status,
                version=existing_doc.version,
                created_at=existing_doc.created_at,
                tenant_id=existing_doc.tenant_id,
                embedding_id=existing_doc.embedding_id,
            )
        else:
            # File is missing, log warning but continue with new ingestion
            logger.warning(
                f"File missing for document {existing_doc.doc_id}, re-ingesting"
            )

    # Create new document in database
    ingest_run_id = uuid4()
    mime_type = file.content_type or "application/octet-stream"

    try:
        # Create document but don't commit yet
        document = DocumentRepository.create(
            session=db,
            sha256=sha256_hash,
            mime=mime_type,
            pages=0,
            source_uri=source_uri or f"upload://{file.filename}",
            doc_name=doc_name or file.filename or "unknown",
            ingest_run_id=ingest_run_id,
            doc_type=doc_type or "pdf",
            tenant_id=tenant_uuid,
            embedding_id=settings.embedding_model,
            status="queued",
            version=1,
        )

        # Flush to get doc_id without committing
        db.flush()

        # Save file to storage
        file_storage = get_file_storage()
        file_path = file_storage.save_file(content, document.doc_id, mime_type)
        logger.info(f"Saved file for document {document.doc_id} at {file_path}")

        # Commit only if file save succeeded
        db.commit()

    except Exception as e:
        logger.error(f"Failed to save document or file: {e}")
        db.rollback()
        raise

    # Trigger ingestion pipeline asynchronously
    try:
        # Publish the initial event
        event = IngestedDocumentEvent(
            doc_id=document.doc_id,
            sha256=document.sha256,
            pages=document.pages,
            tenant_id=document.tenant_id,
            ingest_run_id=document.ingest_run_id,
        )
        publish_event("ingest.document.v1", event)

        # Create and dispatch the processing chain
        document_response = DocumentResponse.model_validate(document)
        document_data = document_response.model_dump()
        processing_chain = chain(
            create_chunks.s(document_data=document_data),
            upsert_vectors.s(),
        )
        chain_id = processing_chain.apply_async()

        logger.info(
            f"Dispatched processing chain {chain_id} for document ID: {document.doc_id}"
        )
    except Exception as e:
        logger.error(
            f"Failed to trigger ingestion pipeline for document {document.doc_id}: {e}"
        )
        # Don't fail the main request - pipeline can be retried later

    # Return persisted document as schema
    return DocumentSchema(
        doc_id=document.doc_id,
        sha256=document.sha256,
        mime=document.mime,
        pages=document.pages,
        source_uri=document.source_uri,
        doc_name=document.doc_name,
        ingest_run_id=document.ingest_run_id,
        doc_type=document.doc_type,
        status=document.status,
        version=document.version,
        created_at=document.created_at,
        tenant_id=document.tenant_id,
        embedding_id=document.embedding_id,
    )


@router.post("/upload/temp")
async def upload_temp_file(
    file: UploadFile = File(...),
    ctx: RequestContext = Depends(require_write_access),  # Members+ can upload
):
    """
    Upload a temporary file scoped to the authenticated user within a tenant.

    This does NOT index or ingest the document; it simply stores it for later review.

    Security: Files are stored in temp/{tenant_id}/{user_id}/ ensuring per-user isolation.
    Only the same authenticated user can later access their temp files.
    """
    content = await file.read()
    file_storage = get_file_storage()

    # Store in tenant+user scoped path for proper isolation
    # Path: temp/{tenant_id}/{user_id}/{filename}
    saved_path = file_storage.save_temp_file(
        ctx.user_id,  # Use authenticated user's ID
        file.filename or "upload.bin",
        content,
        file.content_type or "application/octet-stream",
        tenant_id=str(ctx.tenant_id),  # Pass tenant for path scoping
    )
    return {
        "message": "Temp file saved",
        "path": saved_path,
        "user_id": str(ctx.user_id),
        "tenant_id": str(ctx.tenant_id),
    }


@router.post("/ingest/batch")
async def ingest_batch(
    ctx: RequestContext = Depends(require_write_access),  # Members+ can batch ingest
    db: Session = Depends(get_db),
):
    """
    Process all new files from the batch-input directory.

    Requires write access (admin or member role).

    Files should be placed in: data/batch-input/ (at project root)
    The service will automatically:
    - Scan for new PDF/DOCX files
    - Skip already processed files (tracked in batch-processed.json)
    - Process each file through the ingestion pipeline
    - Return a summary of processed/failed files

    Returns:
        JSONResponse with processing results including:
        - processed: number of successfully queued documents
        - failed: number of files that failed to process
        - skipped: number of already processed files
        - details: list of file processing results
    """

    try:
        batch_service = get_batch_ingestion_service()
        results = batch_service.process_batch(str(ctx.tenant_id), db)

        logger.info(f"Batch processing completed for tenant {ctx.tenant_id}: {results}")

        # Convert any UUID objects to strings for JSON serialization
        def convert_uuids_to_strings(obj):
            if isinstance(obj, dict):
                return {k: convert_uuids_to_strings(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_uuids_to_strings(item) for item in obj]
            elif isinstance(obj, UUID):
                return str(obj)
            else:
                return obj

        # Ensure all UUID objects in results are converted to strings
        serializable_results = convert_uuids_to_strings(results)

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Batch processing completed",
                "summary": {
                    "processed": serializable_results["processed"],
                    "failed": serializable_results["failed"],
                    "skipped": serializable_results["skipped"],
                    "total_found": serializable_results["total_found"],
                },
                "details": serializable_results["details"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    except Exception as e:
        error_msg = f"Batch processing failed: {str(e)}"
        logger.error(error_msg, exc_info=True)

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": error_msg,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )


class DocumentListResponse(BaseModel):
    """Response model for document list endpoint."""

    documents: List[DocumentSchema]
    total: int
    limit: int
    offset: int


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
    doc_type: Optional[str] = None,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """
    List documents accessible to the current user.

    Applies tenant isolation and ACL filtering:
    - Returns only documents in user's tenant
    - Returns public docs (no ACL) + docs user has explicit access to

    Query params:
        limit: Max results (default: 100)
        offset: Skip results (default: 0)
        status: Filter by status ('queued', 'processing', 'ready', 'error')
        doc_type: Filter by document type
    """
    from services.acl_service import get_accessible_doc_ids

    # Get accessible doc IDs for this user
    accessible_ids = get_accessible_doc_ids(ctx.user_id, ctx.tenant_id, db, "read")

    # Query documents for tenant
    all_docs = DocumentRepository.list_by_tenant(
        db, ctx.tenant_id, limit=1000, offset=0, status=status, doc_type=doc_type
    )

    # Filter by ACL
    if accessible_ids is not None:
        # Filter in Python (for smaller tenants)
        filtered_docs = [doc for doc in all_docs if doc.doc_id in accessible_ids]
    else:
        # For large tenants, filter each doc individually (less efficient)
        # In production, this should use Qdrant or optimized query
        from services.acl_service import can_user_access_document

        filtered_docs = [
            doc
            for doc in all_docs
            if can_user_access_document(
                ctx.user_id, doc.doc_id, ctx.tenant_id, db, "read"
            )
        ]

    # Apply pagination
    total = len(filtered_docs)
    paginated_docs = filtered_docs[offset : offset + limit]

    # Convert to schema
    documents = [
        DocumentSchema(
            doc_id=doc.doc_id,
            sha256=doc.sha256,
            mime=doc.mime,
            pages=doc.pages,
            source_uri=doc.source_uri,
            doc_name=doc.doc_name,
            ingest_run_id=doc.ingest_run_id,
            doc_type=doc.doc_type,
            status=doc.status,
            version=doc.version,
            created_at=doc.created_at,
            tenant_id=doc.tenant_id,
            embedding_id=doc.embedding_id,
        )
        for doc in paginated_docs
    ]

    return DocumentListResponse(
        documents=documents,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/documents/{doc_id}", response_model=DocumentSchema)
async def get_document(
    doc_id: UUID,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """
    Get document by ID with tenant isolation and ACL enforcement.

    Requires authentication. Returns 404 if document not found.
    Returns 403 if user doesn't have access (ACL restricted).
    """
    # Query document with tenant isolation
    document = DocumentRepository.get_by_id(db, doc_id, ctx.tenant_id)

    if not document:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    # ACL enforcement
    if not can_user_access_document(ctx.user_id, doc_id, ctx.tenant_id, db, "read"):
        raise HTTPException(status_code=403, detail="Access denied to this document")

    # Return document as schema
    return DocumentSchema(
        doc_id=document.doc_id,
        sha256=document.sha256,
        mime=document.mime,
        pages=document.pages,
        source_uri=document.source_uri,
        doc_name=document.doc_name,
        ingest_run_id=document.ingest_run_id,
        doc_type=document.doc_type,
        status=document.status,
        version=document.version,
        created_at=document.created_at,
        tenant_id=document.tenant_id,
        embedding_id=document.embedding_id,
    )


class DownloadUrlResponse(BaseModel):
    url: str
    filename: str
    mime: str


@router.get("/documents/{doc_id}/download-url", response_model=DownloadUrlResponse)
async def get_download_url(
    doc_id: UUID,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """
    Get a tokenized download URL for a document.

    Requires authentication. Returns a time-limited signed URL.
    Enforces ACL - returns 403 if user cannot access document.
    """
    # Lookup document with tenant isolation
    document = DocumentRepository.get_by_id(db, doc_id, ctx.tenant_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    # ACL enforcement
    if not can_user_access_document(ctx.user_id, doc_id, ctx.tenant_id, db, "read"):
        raise HTTPException(status_code=403, detail="Access denied to this document")

    token = generate_download_token(
        doc_id,
        document.tenant_id,
        user_id=ctx.user_id,
        expiry_minutes=settings.download_token_expiry_minutes,
    )
    return DownloadUrlResponse(
        url=f"/documents/{doc_id}/file?token={token}",
        filename=document.doc_name,
        mime=document.mime,
    )


@router.get("/documents/{doc_id}/file")
async def get_document_file(
    doc_id: UUID,
    token: Optional[str] = None,
    ctx: Optional[RequestContext] = Depends(get_request_context_optional),
    db: Session = Depends(get_db),
    view: Optional[str] = None,  # "inline" or "download"
):
    """
    Serve the document file with tenant isolation and ACL enforcement.

    Requires authentication or a valid download token.
    - Supports local storage (default) and HTTP/HTTPS source URIs via redirect.
    - Returns 404 if the document or file is missing.
    - Returns 403 if user doesn't have access (ACL restricted).
    """
    if token:
        claims = validate_download_token(token, expected_doc_id=doc_id)
        if not claims:
            raise InvalidDownloadTokenError()

        token_tenant_id = claims["tenant_id"]
        token_user_id = claims.get("user_id")

        document = DocumentRepository.get_by_id(db, doc_id, token_tenant_id)
        if not document:
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

        if token_user_id:
            if not can_user_access_document(
                token_user_id, doc_id, token_tenant_id, db, "read"
            ):
                raise HTTPException(
                    status_code=403, detail="Access denied to this document"
                )
        else:
            acl_count = (
                db.query(DocumentACL).filter(DocumentACL.doc_id == doc_id).count()
            )
            if acl_count != 0:
                raise HTTPException(
                    status_code=403, detail="Access denied to this document"
                )
    else:
        if not ctx:
            raise HTTPException(
                status_code=401, detail="Missing or invalid authorization token"
            )

        # Strict tenant isolation - no fallback bypass
        document = DocumentRepository.get_by_id(db, doc_id, ctx.tenant_id)
        if not document:
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

        # ACL enforcement
        if not can_user_access_document(ctx.user_id, doc_id, ctx.tenant_id, db, "read"):
            raise HTTPException(
                status_code=403, detail="Access denied to this document"
            )

    source_uri = document.source_uri or ""

    # If source is an external HTTP/HTTPS link (including SharePoint), redirect
    if source_uri.startswith(("http://", "https://")):
        # Check if it's SharePoint (placeholder for future SharePoint proxy)
        if "sharepoint.com" in source_uri.lower() or "sharepoint" in source_uri.lower():
            # Future: Route through SharePoint proxy with authentication
            # For now, redirect directly (may require authentication)
            logger.info(f"Redirecting to SharePoint URL: {source_uri}")
            return RedirectResponse(url=source_uri, status_code=302)
        return RedirectResponse(url=source_uri, status_code=302)

    # Otherwise, serve from local storage
    file_storage = get_file_storage()

    # Ensure file exists
    if not file_storage.file_exists(document.doc_id, document.mime):
        raise HTTPException(
            status_code=404,
            detail=f"File not found for document {doc_id}",
        )

    # Resolve the file path and mime type
    file_path = Path(file_storage._get_file_path(document.doc_id, document.mime))
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if not mime_type:
        mime_type = document.mime

    # Content disposition
    disposition = "attachment" if view == "download" else "inline"
    safe_filename = urllib.parse.quote(
        (document.doc_name or "document").encode("utf-8")
    )

    return FileResponse(
        path=str(file_path),
        media_type=mime_type,
        filename=document.doc_name,
        headers={
            "Content-Disposition": f"{disposition}; filename=\"{document.doc_name}\"; filename*=UTF-8''{safe_filename}",
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/documents/{doc_id}", response_model=DeleteDocumentResponse)
async def delete_document(
    doc_id: UUID,
    ctx: RequestContext = Depends(require_admin),  # Admin-only for delete
    db: Session = Depends(get_db),
):
    """
    Delete a document and its artifacts (Postgres, Qdrant, file storage).

    Requires admin role. Uses unified deletion service.
    Idempotent: calling delete twice succeeds.
    """
    # Use unified deletion service
    from services.document_deletion import delete_document_everywhere

    try:
        result = delete_document_everywhere(
            db=db,
            doc_id=doc_id,
            tenant_id=ctx.tenant_id,
            idempotent=True,  # Allow idempotent deletes
        )

        return DeleteDocumentResponse(
            doc_id=doc_id,
            deleted=result["deleted"],
            qdrant_deleted=result["qdrant_deleted"],
            file_deleted=result["file_deleted"],
        )
    except ValueError:
        # Document not found
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    except Exception as exc:
        logger.error("Failed to delete document %s: %s", doc_id, exc, exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to delete document: {str(exc)}"
        ) from exc


@router.post("/query", response_model=QueryResponse)
async def query_documents(
    query: QueryRequest,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """
    Query documents with RAG and ACL enforcement.

    Requires authentication. Restricted documents are never cited.

    Strategy:
    1) Try C4AI ReActAgent (stream answer), record trace.
    2) On any failure, fall back to basic retrieval with trace recording.

    Tracing is always recorded. Citations/entities/relations included when available.
    """
    query_id = uuid4()
    trace_id = None  # will fill after TraceRepository.create
    # Tenant comes from JWT via RequestContext
    tenant_uuid = ctx.tenant_id
    start_time = datetime.now(timezone.utc)

    def safe_uuid(val) -> UUID:
        try:
            return UUID(str(val))
        except Exception:
            return uuid4()

    # Get user's groups for ACL filtering
    user_group_ids = list(get_user_group_ids(ctx.user_id, db))

    # Build ACL-aware Qdrant filter
    acl_filter = build_qdrant_acl_filter(ctx.user_id, ctx.tenant_id, user_group_ids)

    # -------- Retrieval path --------
    agent_ok = False
    answer_obj: Optional[Answer] = None
    retrieval_meta = Retrieval(dense=True, sparse=False, graph_hops=0)
    steps = [
        {"t": start_time.isoformat(), "step": "query_received", "lat_ms": 0},
    ]
    citations_for_trace = []

    # Vector search using Qdrant with ACL filter
    try:
        embed_start = datetime.now(timezone.utc)
        query_vector = await embedding_service.generate_embedding(query.q, mode="query")
        steps.append(
            {
                "t": datetime.now(timezone.utc).isoformat(),
                "step": "query_embedding_generated",
                "lat_ms": int(
                    (datetime.now(timezone.utc) - embed_start).total_seconds() * 1000
                ),
            }
        )

        route_result = routing_service.route(query.q, query_vector)
        steps.append(
            {
                "t": datetime.now(timezone.utc).isoformat(),
                "step": "routing_decision",
                "route": route_result.get("name"),
                "route_handler": route_result.get("handler"),
                "route_score": route_result.get("score"),
            }
        )
        handler = route_result.get("handler") or "doc_rag"

        if handler in {"block", "chitchat", "faq", "fallback"}:
            answer_obj = Answer(
                text="This request does not require document retrieval.",
                citations=[],
                support=Support(entities=[], relations=[]),
                confidence=0.6,
            )
            retrieval_meta = Retrieval(dense=False, sparse=False, graph_hops=0)
            end_time = datetime.now(timezone.utc)
            steps.append(
                {
                    "t": end_time.isoformat(),
                    "step": "response_ready",
                    "lat_ms": int((end_time - start_time).total_seconds() * 1000),
                }
            )
            trace = TraceRepository.create(
                session=db,
                query_id=query_id,
                steps=steps,
                tools_used=["routing"],
                citations=[],
                agent_plan={"variant": "routing_only", "swarm": False},
                tenant_id=tenant_uuid,
            )
            db.commit()
            trace_id = trace.trace_id

            return QueryResponse(
                query_id=query_id,
                answers=[answer_obj],
                retrieval=retrieval_meta,
                trace_id=trace_id,
            )

        search_start = datetime.now(timezone.utc)
        qdrant_service = get_qdrant_service()
        search_results = qdrant_service.search(
            query_vector=query_vector,
            tenant_id=str(tenant_uuid),
            k=query.k or 10,
            embedding_id=settings.embedding_model,
            filters=query.filters or {},
            acl_filter=acl_filter,
        )

        steps.append(
            {
                "t": datetime.now(timezone.utc).isoformat(),
                "step": "chunk_retrieval",
                "lat_ms": int(
                    (datetime.now(timezone.utc) - search_start).total_seconds() * 1000
                ),
                "k": len(search_results),
            }
        )

        if search_results:
            seen_text = set()
            citations = []
            answer_texts = []
            for i, result in enumerate(search_results[: query.k or 3]):
                span = [0, len(result.get("text") or "") or 100]
                text = result.get("text") or result.get("content") or ""
                # Skip duplicate chunks with identical text hashes
                text_hash = (
                    hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None
                )
                if text_hash and text_hash in seen_text:
                    continue
                if text_hash:
                    seen_text.add(text_hash)

                citations.append(
                    Citation(
                        doc_id=safe_uuid(result.get("doc_id")),
                        chunk_id=safe_uuid(result.get("chunk_id")),
                        page=result.get("page") or 1,
                        span=span,
                        evidence_id=f"ev_{i:03d}",
                    )
                )
                answer_texts.append(text[:200] if len(text) > 200 else text)

            answer_obj = Answer(
                text=" ".join(answer_texts) or "No relevant content found.",
                citations=citations,
                support=Support(entities=[], relations=[]),
                confidence=0.65 if answer_texts else 0.1,
            )

            citations_for_trace.extend(
                {
                    "sentence_ix": 0,
                    "chunk_id": str(cit.chunk_id),
                    "page": cit.page,
                    "span": cit.span,
                }
                for cit in citations
            )
        else:
            placeholder_cit = Citation(
                doc_id=uuid4(),
                chunk_id=uuid4(),
                page=1,
                span=[0, 100],
                evidence_id="ev_placeholder",
            )
            answer_obj = Answer(
                text="No documents have been fully processed yet. Please ingest and process documents first.",
                citations=[placeholder_cit],
                support=Support(entities=[], relations=[]),
                confidence=0.1,
            )
            citations_for_trace.append(
                {
                    "sentence_ix": 0,
                    "chunk_id": str(placeholder_cit.chunk_id),
                    "page": placeholder_cit.page,
                    "span": placeholder_cit.span,
                }
            )
    except Exception as e:
        logger.error(f"Vector retrieval failed: {e}", exc_info=True)
        placeholder_cit = Citation(
            doc_id=uuid4(),
            chunk_id=uuid4(),
            page=1,
            span=[0, 100],
            evidence_id="ev_error",
        )
        answer_obj = Answer(
            text="Retrieval failed. Please try again.",
            citations=[placeholder_cit],
            support=Support(entities=[], relations=[]),
            confidence=0.1,
        )

    # -------- Trace recording (common) --------
    end_time = datetime.now(timezone.utc)
    steps.append(
        {
            "t": end_time.isoformat(),
            "step": "response_ready",
            "lat_ms": int((end_time - start_time).total_seconds() * 1000),
        }
    )

    trace = TraceRepository.create(
        session=db,
        query_id=query_id,
        steps=steps,
        tools_used=(
            ["c4ai_react_agent"]
            if agent_ok
            else ["document_repository", "chunk_repository"]
        ),
        citations=citations_for_trace,
        agent_plan={
            "variant": "c4ai_react" if agent_ok else "basic_retrieval",
            "swarm": False,
        },
        tenant_id=tenant_uuid,
    )
    db.commit()
    trace_id = trace.trace_id

    return QueryResponse(
        query_id=query_id,
        answers=[answer_obj],
        retrieval=retrieval_meta,
        trace_id=trace_id,
    )


@router.get("/traces/{trace_id}", response_model=TraceSchema)
async def get_trace(
    trace_id: UUID,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """
    Get trace by ID with tenant isolation and ACL-safe citations.

    Requires authentication.
    Returns full execution trace including steps, tools used, and citations.
    Returns 404 if trace not found or contains restricted citations (fail-closed).
    """
    # Query trace with tenant isolation
    trace = TraceRepository.get_by_id(db, trace_id, ctx.tenant_id)

    if not trace:
        raise HTTPException(status_code=404, detail=f"Trace {trace_id} not found")

    # ACL fail-closed: If trace has citations, verify user can access ALL cited docs
    # If any cited doc is restricted, return 404 to prevent information leakage
    if trace.citations:
        for citation in trace.citations:
            cited_doc_id = citation.get("doc_id")
            if cited_doc_id:
                try:
                    cited_uuid = UUID(str(cited_doc_id))
                    if not can_user_access_document(
                        ctx.user_id, cited_uuid, ctx.tenant_id, db, "read"
                    ):
                        logger.warning(
                            f"User {ctx.user_id} denied access to trace {trace_id}: "
                            f"restricted citation {cited_doc_id}"
                        )
                        raise HTTPException(
                            status_code=404,
                            detail=f"Trace {trace_id} not found",  # Fail-closed: don't reveal restricted content
                        )
                except (ValueError, TypeError):
                    pass  # Skip invalid doc_id values

    # Return trace as schema
    return TraceSchema(
        trace_id=trace.trace_id,
        query_id=trace.query_id,
        steps=trace.steps,
        tools_used=trace.tools_used,
        citations=trace.citations,
        agent_plan=trace.agent_plan,
        version=trace.version,
    )
