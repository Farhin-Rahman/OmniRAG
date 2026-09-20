# OmniRAG

Internal document compliance assistant with RAG-powered Q&A.

## Overview

OmniRAG is a unified internal AI workspace, not a pile of disconnected demos. The RAG core answers questions over ingested documents with citations. Built on that same infrastructure is a **Trust & Safety campaign-moderation** system — the main focus of this project — that pairs a deterministic rule engine with LLM risk assessment grounded in retrieval from the platform's own policy documents, keeps a human as the final decision-maker in a real reviewer UI, and measures how often the two agree.

The connective tissue is retrieval: the moderation pipeline's risk assessment queries the **same Qdrant vector index** the document-Q&A chat uses — just a separate `policy_docs` collection — so a risk score comes with a cited policy passage ("violates our Financial-scheme red flags policy"), not just the model's general sense of "seems risky."

## Architecture

```
┌───────────────┐     ┌─────────────────────────┐
│    Frontend   │────▶│         Backend         │
│ Chat, Moderate│     │        (FastAPI)        │
└───────────────┘     └────┬───────────┬────────┘
                           │           │
                      ┌────▼────┐ ┌────▼──────┐     ┌───────────────┐
                      │ SQLite  │ │  Qdrant   │◀───▶│  Groq / Ollama│
                      │ (data + │ │ (docs +   │     │     (LLM)     │
                      │  audit) │ │  policy)  │     └───────────────┘
                      └─────────┘ └───────────┘

  Moderation risk assessment retrieves from Qdrant's `policy_docs`
  collection — the same index document Q&A uses — so its rationale
  cites real policy, not just LLM judgment.

  n8n  ──▶  /api/webhooks/*   (automation-driven ingestion & query)
  MCP  ──▶  backend/mcp_server.py   (agent-driven campaign review)
```

Deliberately lean: the project was consolidated from a Postgres + RabbitMQ +
separate-ML-service design down to SQLite + in-process work, because nothing
in the problem being solved needed the heavier infrastructure. Embeddings run
against a local Ollama model; LLM calls prefer Groq and fall back to Ollama.

## Document Ingestion

Documents enter the index through webhook endpoints (`POST /api/webhooks/ingest-url`, `POST /api/webhooks/upload-file`), designed to be driven by an automation tool — an n8n workflow watching a folder, a mailbox, or a cloud drive, then POSTing new files. Each document is hashed for dedup, OCR'd if needed, chunked, embedded against a local Ollama model, and indexed in Qdrant. Deleting a document removes it from SQLite and Qdrant together.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Frontend | React, TypeScript, Tailwind CSS (Vite) |
| Backend | Python 3.11, FastAPI, SQLAlchemy |
| Database | SQLite (application data + append-only audit ledger) |
| Vector DB | Qdrant |
| Embeddings | Ollama (`nomic-embed-text`), local |
| LLM | Groq (preferred) with Ollama fallback, via `LLMClient` |
| Orchestration | LangGraph (moderation pipeline) |
| Agent interface | MCP (Model Context Protocol) |
| Auth | Firebase Auth (Google + email/password) + custom-claims RBAC |
| Voice Agent | Retell AI (telephony/STT/TTS) + WebSocket brain |
| Automation | n8n (webhook-driven) |

## Docker Services

Orchestrated via `docker-compose`:

| Service | Container Name | Description |
|---------|----------------|-------------|
| **Frontend** | `omnirag-frontend` | React UI served via Vite. |
| **Backend** | `omnirag-backend-python` | FastAPI application — API, RAG, moderation pipeline, SQLite. |
| **Qdrant** | `omnirag-qdrant` | Vector database for document embeddings. |
| **n8n** | `omnirag-n8n` | Automation workflows (webhook-driven ingestion, voice booking). |

The MCP server (`backend/mcp_server.py`) runs on the host, not in a container — MCP clients spawn it as a local subprocess over stdio.

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

# Google Cloud Configuration
GCLOUD_CONFIG_PATH=~/.config/gcloud # for linux, please replace with proper path for Windows
GCP_PROJECT=your-project-id

# LLM Configuration
GEMINI_API_KEY=your-gemini-api-key-here
OPENROUTER_API_KEY=your-openrouter-api-key-here
```

### LLM Configuration

The backend runs on **Ollama** (local, free, no API key required) via `ai/llm_client.py`. Install Ollama and pull a model:

```bash
# https://ollama.com/download
ollama pull qwen2.5:7b
```

Configure via `OLLAMA_BASE_URL` / `OLLAMA_MODEL` in `.env`. `LLMClient` also exposes `generate_stream()` for incremental token streaming (used by the voice agent below).

> Multi-provider support (OpenRouter, Vertex AI) with fallback is on the roadmap but not currently wired into `LLMClient` — `llm_provider_preference` is reserved for that.

**Groq (optional, recommended for the voice agent):** set `GROQ_API_KEY` in `.env` and `LLMClient` prefers it over Ollama automatically. Local CPU inference is too slow for a live phone call (10+ seconds per response, mostly prompt-processing overhead); Groq's inference hardware responds in about a second. Free tier, no card required, at [console.groq.com](https://console.groq.com).

Model choice is per task, not global:
- `GROQ_MODEL` (default `allam-2-7b`) — the voice agent and chat. A fast, direct-answer model on purpose: reasoning models (e.g. `gpt-oss-*`) stream hidden chain-of-thought before answering, which can exhaust a small `max_tokens` budget on a conversational turn.
- `MODERATION_LLM_MODEL` (default `openai/gpt-oss-20b`) — Trust & Safety risk assessment. Not latency-bound, and benefits from a reasoning model; the offline eval ([backend/moderation/eval](backend/moderation/eval)) showed the voice model scoring every campaign at a non-committal 0.5. Passed as `LLMClient(model=...)`, and only takes effect when Groq is the active provider (Ollama keeps its own default).

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

## Voice Agent (Retell AI)

OmniRAG can answer phone calls. [Retell AI](https://www.retellai.com) owns the telephony layer — phone number, speech-to-text, text-to-speech, turn-taking, and interruption handling. OmniRAG's backend is the "brain" Retell calls into on every conversation turn over a WebSocket: it answers questions using the same RAG pipeline as the chat/webhook endpoints, and when a caller wants to book a job, it extracts the details and triggers an n8n automation to create the appointment.

### How it works

1.  **Connect**: Retell opens a WebSocket to `wss://<your-host>/api/voice/llm-websocket/{secret}/{call_id}` (configured as a Custom LLM in the Retell dashboard). The secret is a path segment, not a query param — Retell appends `/{call_id}` to whatever base URL you give it, which would otherwise land inside a `?secret=...` query value instead of a new path segment.
2.  **Per turn**: Retell sends the live transcript; OmniRAG classifies intent (question vs. booking request).
    -   **Question** → retrieves context from Qdrant, streams a spoken-style answer back over the socket.
    -   **Booking request** → extracts `service` / `preferred_day` / `preferred_time` / `customer_name`. If anything's missing, it asks a clarifying question instead of guessing. Once complete, it POSTs to the [n8n booking workflow](automation/n8n-voice-booking-workflow.json), which creates the appointment in your CRM/calendar.
3.  **Failure handling**: if the automation webhook is unreachable, the agent doesn't pretend the booking succeeded — it tells the caller a human will confirm.

### Setup

```bash
# .env
VOICE_WEBSOCKET_SECRET=<random-secret>       # openssl rand -hex 32 (hex, not base64 — see note below)
N8N_BOOKING_WEBHOOK_URL=<your-n8n-webhook>   # see automation/README.md
```

> The secret is passed as a URL query param, so use `openssl rand -hex 32` rather than base64 — base64's `+` character gets silently decoded as a space by standard query-string parsing, which causes the secret check to fail with no useful error.

In the Retell dashboard's Custom LLM URL field, enter `wss://<your-host>/api/voice/llm-websocket/<VOICE_WEBSOCKET_SECRET>` (no `{call_id}` — Retell appends that itself).

Implementation: [backend/routes/voice.py](backend/routes/voice.py).

## Trust & Safety — Campaign Moderation

A human-authoritative moderation system for reviewing campaign submissions, with an AI reviewer in the loop but never the final decision-maker.

### How it works

1.  **Deterministic rules first** ([backend/moderation/rules.py](backend/moderation/rules.py)) — banned phrases, description length, target-amount bounds. This layer deliberately does **not** use an LLM; some checks don't need AI judgment.
2.  **Multilingual, automatically** ([backend/moderation/translate.py](backend/moderation/translate.py)) — every submission is language-detected and translated to English before the steps below (LLM-based, reuses `LLMClient`/`GroqClient` — no dedicated translation model or extra dependency).
3.  **Two AI review paths, same underlying tools:**
    -   **Automatic** ([backend/moderation/graph.py](backend/moderation/graph.py)) — a small LangGraph pipeline (`translate → rules → risk_assessment → record`) runs the moment a campaign is submitted (`POST /api/v1/campaigns/{id}/auto-review`), so a reviewer's queue already has a recommendation waiting, not a blank campaign. Skips the LLM call entirely when a hard rule block already applies — no point spending an LLM call second-guessing a deterministic block. Otherwise, risk assessment is **policy-grounded**: [backend/moderation/policy_retrieval.py](backend/moderation/policy_retrieval.py) embeds the campaign and retrieves the most relevant passages from the platform's Trust & Safety policy (a reference policy written for this project; ingested into a dedicated Qdrant `policy_docs` collection — see [backend/moderation/policy_docs](backend/moderation/policy_docs)), and the model is asked to cite them by name. If the single-pass risk score itself lands in an ambiguous middle band (0.3–0.7), a scoped LLM-as-judge consensus kicks in: 3 independent voters (higher temperature, for genuine variation) plus a judge that reviews all three and gives the final call, using the same retrieved policy — only for the cases the first pass wasn't confident about, not every submission.
    -   **Interactive, via MCP** ([backend/mcp_server.py](backend/mcp_server.py)) — an actual agent (Claude Desktop, or any MCP client) calls `check_campaign_rules_tool`, reasons about a specific case, and calls `record_campaign_recommendation`. For when a human wants to dig into something ambiguous together with an agent, rather than accept the automatic pass.
    -   Neither path ever takes action — both only record a recommendation.
    -   A hard-block ([backend/moderation/notify.py](backend/moderation/notify.py)) posts to Slack (`SLACK_WEBHOOK_URL`, optional — silently skipped if unset), same as an escalation.
4.  **Intake is glue, not code** — a submitted campaign reaches the pipeline through `POST /api/webhooks/campaign-review` (webhook-secret auth, not RBAC), driven by an [n8n workflow](automation/n8n-campaign-moderation-workflow.json): it takes the recommendation and posts it to a reviewer's Slack channel. The workflow owns intake and notification; the service owns the AI and the immutable record; the decision stays with a human on the RBAC-gated endpoints. Deciding *which of those is a workflow and which is code* is the point.
5.  **A human decides** — via the [reviewer UI](frontend/src/pages/Moderation.tsx) (`/moderation`: a queue of campaigns with an AI recommendation and no human decision yet, a detail view with the policy-cited rationale, and Approve/Reject/Escalate) or directly via `POST /api/v1/campaigns/{id}/approve|reject|escalate`, both gated by Firebase RBAC (`require_roles("TrustAndSafetyAdmin")`). The AI's recommendation and the human's actual decision are two separate records, so the comparison between them is meaningful. The queue itself is `GET /api/v1/campaigns/queue` ([backend/db/recommendations.py](backend/db/recommendations.py)) — campaigns with a recommendation but no matching audit-ledger entry yet.
6.  **Append-only audit trail** ([backend/db/audit.py](backend/db/audit.py)) — every human decision, enforced immutable at the SQLite level (triggers block `UPDATE`/`DELETE`, not just app-level convention).
7.  **Eval metric from real usage** ([backend/db/recommendations.py](backend/db/recommendations.py)) — `GET /api/v1/campaigns/metrics/agreement-rate` joins AI recommendations against human decisions by `campaign_id` and reports how often they agreed. Not a synthetic benchmark — computed from actual reviews.

### Evaluation

Three bars, matching the three kinds of eval:

| Kind | Where | What it checks |
|---|---|---|
| **Deterministic** | `pytest tests` on every push ([test_moderation_eval_golden_set.py](backend/tests/test_moderation_eval_golden_set.py)) | The rule engine's hard-block verdict matches the label for all 23 golden-set campaigns. Zero API calls. |
| **LLM-as-judge** | [dispatchable CI job](.github/workflows/moderation-eval.yml) + `python -m moderation.eval.run_eval` locally ([golden_set.py](backend/moderation/eval/golden_set.py)) | The full pipeline (LLM + consensus) against the same labels — action accuracy, a confusion matrix, and **"missed risk"** (anything dangerous that got APPROVED). Runs weekly and on demand, not on every push (real cost); fails only on a missed risk. |
| **Human review** | `GET /api/v1/campaigns/metrics/agreement-rate` (point 7 above) | AI recommendation vs. the human's actual decision, from live usage. |

The golden set has two parts: 18 **synthetic** cases written for this project, and 5 **real public crowdfunding campaigns** (title / description / goal, condensed). The `run_eval` report breaks the real ones out separately. There's no real decision history for a from-scratch project; a production deployment would evaluate against logged human decisions instead.

Latest run: **~19–21/23 exact-action match** (it varies run to run — Groq isn't fully deterministic at temperature 0), but two numbers are stable and are the ones that matter: **0 missed risk** (nothing that should have been stopped was approved) and **0 over-block** (nothing legitimate was auto-rejected). Every mismatch is the pipeline *escalating to a human when it wasn't certain* — a scam it declined to auto-reject, or a real campaign with an internal inconsistency (on one real campaign the model spotted that "$50 × 150 girls" doesn't equal the stated $5,000 goal). The errors are all in the safe direction, by design.

The report also prints **cost** — total LLM calls, tokens, an estimated dollar figure, and how many campaigns triggered the consensus path (each adds 4 calls) — so "is the scoped consensus worth it" is a number. Current run: ~$0.0006/campaign, consensus fires on ~9/23.

> The dispatchable job needs a `GROQ_API_KEY` repository secret (Settings → Secrets and variables → Actions).

### RBAC setup

```bash
python backend/set_admin.py   # grants TrustAndSafetyAdmin to an email via Firebase custom claims
```

### Policy ingestion (one-time)

Risk assessment needs the `policy_docs` Qdrant collection populated before it has anything to retrieve — run once (and again if you edit the docs in `backend/moderation/policy_docs/`):

```bash
docker exec omnirag-backend-python python -m moderation.policy_retrieval
```

Run inside the container (not the host) — Qdrant and Ollama resolve there via their Docker-network names. Without this, retrieval degrades gracefully to no citation rather than failing the pipeline.

### Running the MCP server

Runs on the **host**, not in Docker — MCP clients spawn servers as local subprocesses over stdio, which doesn't fit a container. Since `./data` is bind-mounted into the backend container at `/app/backend/data`, this script and the running API read/write the same audit trail.

```bash
.venv/Scripts/python.exe -m pip install -r backend/requirements-mcp.txt
```

Claude Desktop config (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "omnirag-moderation": {
      "command": "<repo-path>/.venv/Scripts/python.exe",
      "args": ["<repo-path>/backend/mcp_server.py"]
    }
  }
}
```

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

### Voice Agent
- `WS /api/voice/llm-websocket/{call_id}` - Retell AI Custom LLM integration (see [Voice Agent](#voice-agent-retell-ai))

### Automation Webhooks
- `POST /api/webhooks/ingest-url` - Ingest a document from a URL
- `POST /api/webhooks/upload-file` - Ingest an uploaded file
- `POST /api/webhooks/query` - RAG query for n8n/Make/Zapier integrations

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

- **Firebase Auth** — Google Sign-In and email/password with real email-verification gating. ID tokens verified server-side (`firebase_admin.auth.verify_id_token`), not decode-and-trust.
- **RBAC** — role from Firebase custom claims. The moderation actions require `TrustAndSafetyAdmin`, enforced independently on the HTTP path (`require_roles`) and the MCP path (`_verify_reviewer`).
- **Append-only audit ledger** — every human moderation decision, immutability enforced by SQLite triggers (`BEFORE UPDATE`/`BEFORE DELETE`), not app-level convention. (Protects against tampering via SQL; not against raw file access — a production system would add hash-chaining.)
- **Rate limiting** — in-memory sliding window on all non-health endpoints, keyed by authenticated user then IP; returns 429 with `Retry-After`. Swap for a Redis-backed limiter for multi-instance deploys.
- **Slack alerting** — hard-blocks and escalations post to `SLACK_WEBHOOK_URL` if configured.

**Note:** Most API endpoints require authentication. Public endpoints are limited to health checks.

## License

Proprietary. All rights reserved.
