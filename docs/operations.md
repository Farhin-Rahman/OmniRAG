# Operations & Troubleshooting

## Services & Ports (Docker defaults)
- Backend API: `http://localhost:8081`
- ML service: `http://localhost:18000`
- Frontend: `http://localhost:5174`
- Qdrant: `http://localhost:6335`
- Postgres: `localhost:5433`
- RabbitMQ: `amqp://guest:guest@localhost:5672/`

## Local Dev Ports (running services directly)
- Backend API: `http://localhost:8080`
- ML service: `http://localhost:8000`
- Frontend: `http://localhost:5173`
- Qdrant: `http://localhost:6333`
- Postgres: `localhost:5432`

## Database Setup
- Initialize database (first time): `cd backend && uv run alembic upgrade head`
- Generate tenant ID for testing: `python -c "import uuid; print(str(uuid.uuid4()))"`

## Common Commands
- Start stack: `docker compose up -d --build`
- Tail logs: `docker compose logs -f backend worker ml-service frontend`
- Run backend tests: `cd backend && uv run pytest`
- Frontend lint/build: `cd frontend && npm run lint && npm run build`

## Ingestion
- Single upload: `POST /api/ingest` with `Authorization: Bearer <access_token>` (multipart file).
- Batch: drop PDFs/DOCX in `data/batch-input/` then call `POST /api/ingest/batch`.
- Files are stored under `DOCUMENTS_DIR` (env), keyed by `doc_id`.
- Tenant isolation uses the JWT `tid` claim; do not send `x-tenant-id`.

### Ingestion Examples
```bash
# Sign in and capture access token (JWT includes tenant_id as "tid")
curl -X POST http://localhost:8081/api/auth/signin \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"SecurePass123!"}'

# Single file upload
curl -X POST http://localhost:8081/api/ingest \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -F "file=@document.pdf"

# Batch ingestion
# First, place files in data/batch-input/
curl -X POST http://localhost:8081/api/ingest/batch \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

## Health Checks
- Backend: `/healthz`
- ML service: `/health`

## Docling model downloads (online/offline)
- By default the worker runs **online**, downloading Docling models into the shared `model_cache` volume when first needed.
- Set `HF_HUB_OFFLINE=1` in `.env` **after** you have pre-fetched models into the cache to force offline behavior.
- If you have a preseeded path, set `DOCLING_ARTIFACTS_PATH` to that directory; leave it blank to let Docling manage its own cache location.

## PaddleOCR fallback
- PaddleOCR is used only in fallback parsing paths (when Docling is empty or selective OCR is needed).
- If PaddleOCR is crashing or unavailable in your environment, set `PADDLEOCR_DISABLE=1` in `.env` (or the worker service env) and restart the worker; the parser will skip PaddleOCR and rely on PyMuPDF-only fallback instead.

## Dependency Management (uv)

### Add/Update dependencies
```bash
# Backend
cd backend
uv add <package>                  # Add to main dependencies
uv add --group dev <package>      # Add to dev dependencies
uv add --group ci <package>       # Add to CI dependencies
uv lock                          # Update lockfile

# ML Service
cd ml-service
uv add <package>
uv lock
```

### Install dependencies
```bash
# Development
uv sync --group dev              # Backend with dev deps
uv sync                          # ML service

# Production
uv sync --frozen --no-dev        # Uses lockfile, no dev deps

# CI
uv sync --group ci --frozen      # CI dependencies only
```
