# Automation Workflow Templates

Ready-to-import workflow files for connecting OmniRAG to Make, n8n, and Zapier.

## Setup

1. Set `WEBHOOK_SECRET` in your `.env` file (generate with `openssl rand -base64 32`)
2. Get your tenant ID from the Automation Pipeline page in the UI (or from `GET /api/auth/session`)
3. Import the workflow file into your automation platform

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
