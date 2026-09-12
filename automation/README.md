# Automation Workflow Templates

Ready-to-import workflow files for connecting OmniRAG to Make, n8n, and Zapier.

## Setup

1. Set `WEBHOOK_SECRET` in your `.env` (generate with `openssl rand -base64 32`) — the `/api/webhooks/*` endpoints check the `X-Webhook-Secret` header against it. Leave it blank to run open in local dev.
2. Import the workflow file into your automation platform.

---

## n8n — Trust & Safety Campaign Intake

**File:** `n8n-campaign-moderation-workflow.json`

**What it does:** a campaign submission comes in on a webhook → the workflow POSTs it to `POST /api/webhooks/campaign-review`, which runs the full moderation pipeline (translate → deterministic rules → LLM risk assessment → scoped consensus if the score is ambiguous → record a recommendation) → the workflow formats the recommendation and posts it to a Slack channel for a human reviewer.

**Why this is a workflow and not more backend code:** the pipeline, the rule engine, and the immutable recommendation log need real code — but intake, formatting, and notification are glue. This is the seam. The workflow is deliberately **not** given approve/reject authority; the human decision goes through the RBAC-gated `/api/v1/campaigns/{id}/approve|reject|escalate` endpoints, which require the `TrustAndSafetyAdmin` Firebase role.

**Import steps:**
1. Open n8n → Workflows → Import from file → `n8n-campaign-moderation-workflow.json`
2. Open the **"Notify #trust-safety"** node → set the **URL** field to your Slack Incoming Webhook URL (replace the `PASTE_YOUR_SLACK_WEBHOOK_URL_HERE` placeholder).
3. If n8n and the backend aren't on the same Docker network, also open **"Auto-Review (OmniRAG)"** and change `http://backend:8080` to `http://host.docker.internal:8081`. If the backend has `WEBHOOK_SECRET` set, put the same value in that node's `X-Webhook-Secret` header.
4. Save, then activate the workflow.

**Test:**
```bash
curl -X POST http://localhost:5678/webhook/omnirag-campaign-review \
  -H "Content-Type: application/json" \
  -d '{"title": "Guaranteed return investment pool", "description": "Join now and double your money in 30 days", "target_amount": 50000}'
```
Expect a hard-block `REJECT` (banned phrases) posted to Slack, with no LLM call spent.

---

## n8n — RAG Query Workflow

**File:** `n8n-rag-query-workflow.json`

**What it does:** Exposes an HTTP endpoint. When POSTed a `{ "question": "..." }`, it queries OmniRAG and returns an AI-generated answer.

**Import steps:**
1. Open n8n → Workflows → Import from file
2. Select `n8n-rag-query-workflow.json`
3. Set environment variables in n8n:
   - `OMNIRAG_WEBHOOK_SECRET` — your webhook secret
   - `OMNIRAG_TENANT_ID` — your tenant UUID
4. Activate the workflow

**Test:**
```bash
curl -X POST http://localhost:5678/webhook/ask-omnirag \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the key compliance requirements?"}'
```

---

## Make — Ingest Document from URL

**File:** `make-ingest-from-url.json`

**What it does:** Listens for a webhook with a file URL. Downloads the file and queues it for RAG ingestion.

**Import steps:**
1. Open Make → Scenarios → Import Blueprint
2. Select `make-ingest-from-url.json`
3. Replace placeholders:
   - `{{your-webhook-secret}}` → your WEBHOOK_SECRET value
   - `{{your-tenant-uuid}}` → your tenant UUID
4. Update the backend URL if not running locally

**Trigger payload:**
```json
{ "url": "https://example.com/compliance-report.pdf", "doc_name": "Q4 Compliance Report" }
```

---

## n8n — Voice Agent Booking Automation

**File:** `n8n-voice-booking-workflow.json`

**What it does:** Receives booking details extracted by OmniRAG's voice agent (see `backend/routes/voice.py`, a Retell AI Custom LLM WebSocket integration) and creates the appointment in your CRM/calendar of choice.

**Context:** The voice agent handles calls end-to-end — Retell owns telephony/STT/TTS, OmniRAG's backend is the "brain" (RAG answers + intent extraction). When a caller asks to book a job, the backend extracts `service`, `preferred_day`, `preferred_time`, `customer_name`, and POSTs them here instead of guessing or hardcoding a CRM integration.

**Import steps:**
1. Open n8n → Workflows → Import from file
2. Select `n8n-voice-booking-workflow.json`
3. Replace `{{your-crm-or-calendar-webhook-url}}` in the "Create Booking" node with your actual CRM/calendar endpoint
4. Set `N8N_BOOKING_WEBHOOK_URL` in your `.env` to this workflow's webhook URL
5. Activate the workflow

**Payload sent by the voice agent:**
```json
{ "service": "drain cleaning", "preferred_day": "Tuesday", "preferred_time": "afternoon", "customer_name": "Jane Doe", "call_id": "abc123" }
```

---

## Direct API usage

Both endpoints work with any HTTP client. No library needed.

### Ingest a document from URL
```bash
curl -X POST http://localhost:8081/api/webhooks/ingest-url \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: YOUR_SECRET" \
  -d '{"url": "https://example.com/doc.pdf", "tenant_id": "YOUR_TENANT_UUID"}'
```

### Query the knowledge base
```bash
curl -X POST http://localhost:8081/api/webhooks/query \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: YOUR_SECRET" \
  -d '{"question": "What are the key requirements?", "tenant_id": "YOUR_TENANT_UUID"}'
```
