# OmniRAG

Internal document compliance assistant with RAG-powered Q&A.

## Overview

OmniRAG enables organizations to query their internal documents using natural language. It ingests documents from SharePoint, processes them with OCR and chunking, and provides accurate answers with source citations.

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Frontend  │────▶│   Backend   │────▶│  ML Service │
│   (React)   │     │  (FastAPI)  │     │  (FastAPI)  │
└─────────────┘     └──────┬──────┘     └─────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │ Postgres │    │  Qdrant  │    │ RabbitMQ │
    │  (Data)  │    │ (Vectors)│    │  (Queue) │
    └──────────┘    └──────────┘    └──────────┘
```

## SharePoint Sync

OmniRAG maintains a one-way synchronization with a configured SharePoint Document Library.

### Workflow

1.  **Trigger**: Sync is triggered via the Frontend (calling `POST /api/sync`) or can be run as a standalone CLI script.
2.  **Execution**: The backend dispatches a background task (`SharePointService`) which ensures only one sync runs per tenant at a time.
3.  **Delta Query**: The system uses **Microsoft Graph API Delta Query** to fetch only changed files since the last run.
4.  **State Management**: A local state file (`sync_state_{tenant_id}.json`) persists the `deltaLink` and a mapping of SharePoint Item IDs to local paths.

### Change Handling

-   **New/Modified Files**:
    -   Downloaded to a local cache directory (`documents/`).
    -   Processed by the `BatchIngestionService` (hashing, OCR, embedding).
    -   Updates are atomic; database records are only committed on successful ingestion.
-   **Deletions**:
    -   If a file is removed from SharePoint, the delta query returns a deletion marker.
    -   The system identifies the file via the state mapping.
    -   The file is removed from the local filesystem, PostgreSQL, and the Vector Database (Qdrant).

## Tech Stack

| Component | Technology |
|-----------|------------|
| Frontend | React, TypeScript, Tailwind CSS |
| Backend | Python 3.11, FastAPI, SQLAlchemy |
| ML Service | Sentence Transformers, Cross-Encoder |
| Vector DB | Qdrant |
| Database | PostgreSQL 15 |
| Queue | RabbitMQ |

## Docker Services

The system is composed of several Docker containers orchestrated via `docker-compose`:

| Service | Container Name | Description |
|---------|----------------|-------------|
| **Frontend** | `omnirag-frontend` | React-based user interface served via Vite (dev) or Nginx (prod). |
| **Backend** | `omnirag-backend-python` | Core FastAPI application handling API requests, business logic, and database interactions. |
| **Worker** | `omnirag-worker` | Celery worker for processing background tasks (e.g., document ingestion, OCR). |
| **ML Service** | `omnirag-ml-service` | Dedicated service for hosting heavy ML models (embeddings, re-ranking) to isolate resource usage. |
| **PostgreSQL** | `omnirag-postgres` | Relational database for storing application data, users, and document metadata. |
| **Qdrant** | `omnirag-qdrant` | Vector database for storing and querying document embeddings. |
| **RabbitMQ** | `omnirag-rabbitmq` | Message broker for task queue management between Backend and Worker. |
| **Model Warmup** | `omnirag-model-warmup` | Utility container (profile: `warmup`) to pre-download and cache ML models. |

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Node.js 18+ (for frontend development)
- Python 3.11+ (for backend development)

### Running and Deploying with Docker

```bash
# Clone the repository
git clone <repository-url>
cd omnirag

# Copy environment file
cp .env.example .env

# Start all services
docker compose up -d

# View logs
docker compose logs -f backend
```

### Accessing the Application

| Service | URL |
|---------|-----|
| Frontend | http://localhost:5174 |
| Backend API | http://localhost:8081/api |
| API Docs | http://localhost:8081/docs |

Local dev (Vite) defaults to `http://localhost:5173`.

## Configuration

Key environment variables (see `.env.example` for full list):

```bash
# Database
POSTGRES_USER=omnirag
POSTGRES_PASSWORD=<your-password>
POSTGRES_DB=omnirag

# Authentication (min 64 chars, cryptographically random)
JWT_SECRET_KEY=<your-secret>  # openssl rand -base64 64
DOWNLOAD_URL_SECRET=<your-secret>  # openssl rand -base64 32

# CORS (comma-separated origins for production)
CORS_ALLOWED_ORIGINS=http://localhost:5174,http://localhost:5173,http://frontend:8000

# SharePoint Integration
SHAREPOINT_CLIENT_ID=<client-id>
SHAREPOINT_CLIENT_SECRET=<client-secret>
SHAREPOINT_TENANT_ID=<tenant-id>
SHAREPOINT_SITE_ID=<site-id>

SHAREPOINT_LIMIT=10  # Max files to process during sync/listing

# Google Cloud Configuration
GCLOUD_CONFIG_PATH=~/.config/gcloud # for linux, please replace with proper path for Windows
GCP_PROJECT=your-project-id

# LLM Configuration
GEMINI_API_KEY=your-gemini-api-key-here
OPENROUTER_API_KEY=your-openrouter-api-key-here
```

### LLM Configuration

The system supports multiple LLM providers (OpenRouter, Vertex AI) with configurable fallback strategies.

**Provider Preference** (`LLM_PROVIDER_PREFERENCE`):
-   `auto` (default): Tries OpenRouter first, falls back to Vertex AI.
-   `openrouter`: Prefer OpenRouter, fallback to Vertex AI.
-   `vertex-ai`: Prefer Vertex AI, fallback to OpenRouter.
-   `openrouter-only`: Use OpenRouter only (fail if unavailable).
-   `vertex-only`: Use Vertex AI only (fail if unavailable).

**Vertex AI Authentication**:
Vertex AI connection supports both Application Default Credentials (ADC) and explicit service account keys:
1.  **Application Default Credentials (ADC)**:
    -   Automatic detection when running on Google Cloud (GCE, GKE, Cloud Run).
    -   For local dev: `gcloud auth application-default login`.
2.  **Service Account JSON**:
    -   Set `GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json`.
    -   Ensure the file is accessible (mounted) within the Docker container.

### Docling Offline Setup Guide (Docker + Celery)

Use this setup to run Docling fully offline inside Docker.
This prevents model download failures, missing-model errors, and worker hangs.

#### 1. Configure Celery Worker (single process)

In the worker service of docker-compose.yml:

```
command:
  [
    "celery", "-A", "worker.celery_app", "worker",
    "--loglevel=info",
    "--pool=solo",
    "--concurrency=1"
  ]
```
Add shared memory:
shm_size: "2gb"
#### 2. Add shared model cache volume
```
volumes:
  - model_cache:/home/appuser/.cache
```
This ensures all Docling & HF models are stored persistently.

Also add the volume under the global `volumes:` section:
```
volumes:
  model_cache:
```
#### 3. Add required environment variables

These MUST be in the worker container:
```
DOCLING_CACHE_DIR=/home/appuser/.cache/docling
DOCLING_ARTIFACTS_PATH=/home/appuser/.cache/docling/models/docling-project--docling-models
HF_HOME=/home/appuser/.cache/huggingface
TRANSFORMERS_CACHE=/home/appuser/.cache/huggingface
```
These ensure Docling + Transformers look in the correct offline directories.

#### 4. Download Docling models (once)

Run inside worker container:
```
docker exec -u appuser omnirag-worker python - << 'EOF'
from docling.utils.model_downloader import download_models
download_models()
EOF
```
This downloads:
- TableFormer (accurate + fast)
- RapidOCR
- Layout models
- Figure classifier
- Docling internal models

#### 5. Verify that all models are present
```
docker exec omnirag-worker ls -R /home/appuser/.cache/docling/models
```
Expected folders:
```
docling-project--docling-models
RapidOcr
docling-project--CodeFormulaV2
docling-project--DocumentFigureClassifier
docling-project--docling-layout-heron
tableformer/accurate/*.safetensors
tableformer/fast/*.safetensors
```

If these exist, Docling can run fully offline.

#### 6. After verification, restart worker

`docker compose restart worker`

Worker should now:
- load Docling converter instantly
- NEVER download models
- avoid TableModel04_rs errors
- avoid blocking/hanging
- run stable inside Celery solo mode

## Project Structure

```
omnirag/
├── backend/           # FastAPI backend
│   ├── ai/           # Chat service, prompts
│   ├── models/       # SQLAlchemy models
│   ├── routes/       # API endpoints
│   ├── services/     # Business logic
│   └── tests/        # Unit tests
├── frontend/          # React frontend
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   └── services/
├── ml-service/        # ML inference service
├── infra/            # Infrastructure configs
└── docker-compose.yml
```

## API Endpoints

### Chat
- `POST /api/chat` - Send a message and get a response with citations

### Documents
- `GET /api/documents` - List accessible documents
- `DELETE /api/documents/{id}` - Delete a document

### Sessions
- `GET /api/sessions` - List chat sessions
- `DELETE /api/sessions/{id}` - Delete a session

## Development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e .
uvicorn main:app --reload --port 8080
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Running Tests

```bash
# Backend tests
cd backend
pytest tests/ -v

# Frontend tests
cd frontend
npm test
```

## Security

- JWT-based authentication with tenant isolation
- Document-level ACL (per user and group)
- Token revocation on signout (access + refresh token blacklist)
- CORS whitelist (configure via `CORS_ALLOWED_ORIGINS`)
- Rate limiting on sensitive endpoints
- Audit logging for security-relevant operations
- Tenant context cryptographically bound via JWT claims
- Tenant headers are not required; tenant identity comes from JWT `tid`

**Note:** Most API endpoints require authentication. Public endpoints are limited to health checks.

## License

Proprietary. All rights reserved.
