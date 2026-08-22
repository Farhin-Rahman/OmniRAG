# OmniRAG RAG – Architecture

This is the source-of-truth overview of how the system is built today.

## Components
- **Backend (FastAPI)**: `backend/main.py` with routes:
  - `/ingest`, `/ingest/batch`, `/documents/{id}`, `/query`, `/traces/{id}`, `/healthz`.
  - `/chat` (alias `/api/chat/completions`) plus auth/conversations under `/api`.
- **Worker (Celery)**: `worker/celery_app.py` with tasks in `worker/ingestion.py`.
- **Vector DB**: Qdrant; collection sized by `settings.embedding_dim` (1024), cosine distance, payload indexes on tenant_id/embedding_id/doc_type/doc_id.
- **Database**: Postgres models in `models/base.py`; sessions in `services/db/postgres_service.py`.
- **ML Service**: `ml-service` FastAPI serving ONNX embeddings (`sayed0am/arabic-english-bge-m3`, 1024-d) and BGE reranker.
- **Frontend**: React/Vite consuming backend APIs (`frontend/src/lib/api-client.ts`).

## Configuration
- `config/settings.py`: embedding model id, embedding_dim=1024, qdrant host/port, rabbitmq URL, storage paths (`documents_dir`, `batch_input_dir`), feature flag `rerank_enabled`.
- ML service config: `ml-service/config.py` (port 8000, model id, embedding_dim=1024).

## Data Model (Postgres)
- **documents**: doc_id PK, sha256+tenant unique, mime, pages, source_uri, doc_name, doc_type, ingest_run_id, status (queued|processing|ready|error), version, embedding_id, tenant_id, created_at.
- **chunks**: chunk_id PK, doc_id FK, text, checksum, page, section, span JSON, layout JSON, overlap, vector_id, embedding_id, chunk_metadata JSON (language, confidence, chunk_type, kv, table grid, section_path).
- **traces**: trace_id PK, query_id, steps, tools_used, citations, agent_plan, version, tenant_id, created_at.
- Other tables (entities, relations, users, conversations, messages) exist but are not used in current RAG flow except conversations/messages for chat history.

## Storage
- Files saved under `settings.documents_dir` as `{doc_id}.{ext}` (ext from MIME). No per-tenant directory; isolation via doc_id/tenant in DB.

## Qdrant
- Collection initialized at startup (`QdrantService.initialize_qdrant_collection`).
- Search filters: tenant_id (required), embedding_id; optional doc_type/doc_ids.
- Payload stored: chunk_id, doc_id, tenant_id, text, page, section, embedding_id, doc_type, doc_name, chunk_type, kv_key/value.
- Delete by doc_id supported.

## Embeddings & Reranker
- Backend EmbeddingService calls ML service `/embeddings`; prepends BGE query instruction for queries.
- ML service embedding: ONNXRuntime CLS pooling, L2-normalized 1024-d; fallback SentenceTransformers optional (disabled by default).
- Reranker: BAAI/bge-reranker-v2-m3 CPU, sigmoid scores, batching; exposed via `/rerank`.

## Parsing & Chunking
- Parser: Docling (OCR disabled) with table structure on; fallback selective PaddleOCR + PyMuPDF when Docling is empty or times out; language detection via character stats. Set `PADDLEOCR_DISABLE=1` to skip PaddleOCR entirely and use PyMuPDF-only fallback if Paddle is unstable in the environment.
- Chunker: target ~800 tokens, max 1200, overlap ~150; groups by section; tables kept as single chunks with nearby labels; KV heuristic marks chunk_type=kv. chunk_metadata carries language/confidence/page range/section_path/table grid.

## Ingestion Pipeline
- `/ingest`: authenticate user; tenant derived from JWT `tid` claim; size check; SHA256 dedup per tenant; create Document (status queued), save file; publish event; Celery chain `create_chunks -> upsert_vectors`.
- `/ingest/batch`: scans `data/batch-input`, tracks processed files, queues same chain.
- `create_chunks`: delete existing vectors/chunks for doc, set status processing, parse+chunk, publish `ingest.chunks.v1`, attach chunk_ids.
- `upsert_vectors`: if no chunks → status error; otherwise embed chunks, upsert to Qdrant, set status ready, publish `index.vectors.v1`.

## Retrieval & Chat
- `/query`: embed query, Qdrant search (tenant+embedding filter, k default 10), dedup identical texts, naive Answer assembly, Trace saved.
- `/chat`: embed query, Qdrant search k=50, optional rerank, KV boosting, MMR-style chunk selection, prompt via YAML (`prompts/chat_prompt.yaml`) when available, LLM via OpenRouter/VertexAI, optional citation extraction via YAML prompt, messages persisted, Trace saved with the real trace_id.

## Multi-Tenancy
- Tenant context is derived from JWT `tid` claim (not headers); DB queries and Qdrant filters enforce tenant_id; file storage keyed by doc_id.

## Events
- RabbitMQ publisher emits `ingest.document.v1`, `ingest.chunks.v1`, `index.vectors.v1`. No consumers in this repo.

## Health & Ops
- Backend `/healthz`; ML service `/health`.
- See `docs/OPERATIONS.md` for commands, ports, troubleshooting.
