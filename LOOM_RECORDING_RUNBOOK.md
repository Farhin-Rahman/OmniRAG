# OmniRAG Loom Recording Runbook 🎬

> **Quick Note on Render:** You **do NOT need to redeploy Render**. Everything is running locally in your Docker containers (`localhost:5174`, `localhost:8081`, `localhost:5678`). Local execution has zero cold starts, zero latency, and 100% reliability for recording.

---

## ⚡ Pre-Flight Setup (Open These Tabs Before Pressing Record)

Have these browser tabs open side-by-side in Chrome:
1. **Tab 1 — Chat:** `http://localhost:5174/chat` (signed in as `sadiafarhin62@gmail.com`)
2. **Tab 2 — Automations:** `http://localhost:5174/automation`
3. **Tab 3 — n8n Canvas:** `http://localhost:5678` (Open the "OmniRAG Trust & Safety — Campaign Intake" workflow)
4. **Tab 4 — Trust & Safety:** `http://localhost:5174/moderation` (Should show **Pending review (3)**)
5. **Tab 5 — Voice Agent:** `http://localhost:5174/voice`

---

## 🔑 Terminal Cheat Sheet: Controlling RBAC Access

You control user roles directly via terminal commands using the backend admin scripts:

```powershell
# 1. Grant Admin access (sets Firebase custom claim: roles=["TrustAndSafetyAdmin"])
docker exec omnirag-backend-python python set_admin.py sadiafarhin62@gmail.com

# 2. Revoke Admin access (clears role to normal user: roles=[])
docker exec omnirag-backend-python python revoke_admin.py sadiafarhin62@gmail.com

# 3. Emergency Queue Reset (re-seeds the 3 moderation campaigns if needed)
python scripts/seed_moderation_queue.py
```

*(Note: Custom claims take effect on the user's next token refresh or when signing out/in).*

---

## ⏱️ RECORDING TIMELINE (Target: ~7–8 Minutes)

```
[0:00 - 1:00]  Introduction & Executive Overview
[1:00 - 2:00]  Chat & Document Library (RAG with Citations)
[2:00 - 4:00]  The Automation Layer (Frontend Pipeline + n8n Webhook Workflow)
[4:00 - 6:30]  Trust & Safety: RBAC + 3-Layer Moderation Queue Review
[6:30 - 7:30]  Voice Agent & Live Booking Intake
[7:30 - 8:00]  Closing Summary
```

---

## STEP 1: Introduction (0:00 – 1:00)

📍 **SCREEN:** Tab 1 (`http://localhost:5174/chat`)

🗣️ **SAY ALOUD:**
> "Hi everyone. Today I'm presenting OmniRAG — an enterprise-grade AI operations platform built for automated intake, knowledge retrieval, and human-in-the-loop Trust & Safety governance.
>
> In production systems, you can't just give an autonomous LLM unconstrained decision power over critical operations like financial campaign approval or customer bookings. 
> 
> OmniRAG demonstrates how to build a deliberate architectural seam: using workflow automations like n8n for intake and notifications, real backend code for deterministic policy rules and AI consensus scoring, and strict Role-Based Access Control so humans always retain final authority."

---

## STEP 2: Document Library & RAG Chat (1:00 – 2:00)

📍 **SCREEN:** Tab 1 (`http://localhost:5174/chat`)

👉 **ACTION:** Click **"Document Library"** in the sidebar. Show the ingested document (e.g. `apex_hvac_faq.pdf`). Then click back to **Chat** and ask a question:
- Type: `What maintenance does an HVAC system require?`
- Press Enter.

🗣️ **SAY ALOUD:**
> "Here in our chat workspace, questions are grounded against our vector store in Qdrant. Documents are chunked and embedded using local embedding models, and every answer returns with source citations rather than hallucinations."

---

## STEP 3: The Automation Layer (2:00 – 4:00) ⚡ *HIGH PRIORITY*

📍 **SCREEN:** Switch to Tab 2 (`http://localhost:5174/automation`)

👉 **ACTION 1:** Scroll through the **Document Ingestion Pipeline** visual diagram at the top.
- Point to the 5 stages: Upload ➔ Parse ➔ Chunk ➔ Embed ➔ Index.
- Point to the **Live Stats** cards below it: Total documents, Indexed & ready.

🗣️ **SAY ALOUD:**
> "Under the Automations tab, we expose the operational plumbing of the platform. Here is our live ingestion pipeline showing real-time document processing stages and status badges.
>
> Down here, we expose standardized webhook endpoints like `/api/webhooks/ingest-url` and `/api/webhooks/query`, secured with webhook secrets, allowing platforms like n8n, Make, or Zapier to trigger background ingestion or query our knowledge base over HTTP."

👉 **ACTION 2:** Scroll down to **"Live Webhook Test"** at the bottom of the page.
- In the **Question** box, type: `What is the warranty policy?`
- Click the blue **"Send"** button.
- Show the formatted JSON response appearing instantly in green in the **Response JSON** box below.

🗣️ **SAY ALOUD:**
> "We can even test this live right here: firing a webhook query returns a clean JSON payload containing the grounded answer and citations, ready to be consumed by any external downstream workflow."

👉 **ACTION 3:** Switch to Tab 3 (`http://localhost:5678` — n8n Canvas)
- Show the node graph: **Campaign Submitted (Webhook)** ➔ **Normalize Campaign (Code)** ➔ **Auto-Review (HTTP Request)** ➔ **Notify #trust-safety (Slack)**.

🗣️ **SAY ALOUD:**
> "Now let's look at n8n, running in our Docker stack. This workflow handles campaign intake. When a creator submits a campaign, n8n normalizes the payload, calls our backend AI moderation webhook, and posts the resulting recommendation directly to our Slack `#trust-safety` channel.
>
> The key design principle here is the seam: n8n owns the intake glue and notification formatting. But notice what this workflow does NOT have — it is never given approval or payout authority. High-stakes governance decisions are strictly human-in-the-loop."

---

## STEP 4: Trust & Safety & RBAC (4:00 – 6:30) ⚡ *CORE FEATURE*

📍 **SCREEN:** Switch to Tab 1 (`http://localhost:5174/chat`)

👉 **ACTION 1: Showcase RBAC in the Sidebar**
- Point mouse to the bottom-left sidebar under your email (`sadiafarhin62@gmail.com`).
- Point to the green **"Admin"** badge.
- Point to the green **"Trust & Safety"** shield button.

🗣️ **SAY ALOUD:**
> "Notice down here in the sidebar — my profile has an 'Admin' badge and a green 'Trust & Safety' navigation button.
>
> This is protected by full Role-Based Access Control (RBAC). Roles are managed directly from the terminal using our backend admin scripts — `set_admin.py` and `revoke_admin.py` — which inject or clear custom claims in Firebase Auth.
>
> In our React AuthProvider, we verify this `TrustAndSafetyAdmin` claim on the JWT. If a normal user logs in, this button is completely hidden. If an unauthorized user tries typing `/moderation` directly in the URL bar, our `<AdminRoute>` guard intercepts and redirects them back to `/chat`. And on the backend, every single review and decision endpoint enforces role requirements, returning a strict `403 Forbidden` if the claim is missing."

👉 **ACTION 2: Enter the Moderation Queue**
- Click the green **"Trust & Safety"** button (or switch to Tab 4: `http://localhost:5174/moderation`).
- Point to the left pane showing **"Pending review (3)"**.

🗣️ **SAY ALOUD:**
> "This brings us to the Trust & Safety review queue. Here we have three campaigns pre-loaded from our intake webhook, representing the three distinct paths of our moderation engine."

👉 **ACTION 3: Case 1 — Clean Legitimate Campaign (APPROVE)**
- Click on **"Riverside Community Garden Expansion"** ($3,500).
- Point to: AI Recommends: **APPROVE**, Risk score: **0.10 (Low)**.
- Read rationale aloud: *"Campaign provides a specific purpose, named organization (Riverside Youth Center), supplier (Nashville Seed Co.), and itemized, verified costs."*
- Click the green **"Approve"** button.
- Point to the green toast: *"Campaign approved. Recorded to the audit ledger."* Show it drop off the queue.

👉 **ACTION 4: Case 2 — Ambiguous / Consensus Trigger (ESCALATE)**
- Click on **"Holistic Wellness & Recovery Equipment"** ($7,500).
- Point to the badge: AI Recommends: **ESCALATE**, Risk score: **0.55 (Unverifiable)**.
- Highlight the source: **`langgraph-auto-consensus`**!

🗣️ **SAY ALOUD:**
> "Look at the source here: `langgraph-auto-consensus`. Because this campaign's initial risk score fell in the ambiguous 0.3 to 0.7 middle band, the system triggered our multi-agent consensus judge: three independent LLM reviewer voters and one judge. They agreed that while the wellness mission is plausible, it lacks itemized equipment quotes or verification documents, so escalation is required."

- Click the yellow **"Escalate"** button.
- In Notes, type: `Requesting verified supplier invoice and facility credentials.`
- Click Confirm. Show it recorded.

👉 **ACTION 5: Case 3 — Policy Violation / Rule Block (REJECT)**
- Click on **"Guaranteed return investment pool"** ($50,000).
- Point to: AI Recommends: **REJECT**, Risk score: **1.0 (rule_violation)**.
- Read rationale: *"Blocked by deterministic policy rule: Contains banned phrase: 'guaranteed return'; Contains banned phrase: 'double your money'"*

🗣️ **SAY ALOUD:**
> "And this third case shows our first line of defense: deterministic policy rules. The phrases 'guaranteed return' and 'double your money' fired an immediate hard block. Zero LLM tokens were wasted, and a Slack alert was fired immediately."

- Click the red **"Reject"** button.
- Reason code: `financial_fraud_guaranteed_return`
- Click Confirm.

👉 **ACTION 6: Live Agreement Rate Eval Metric**
- Point mouse to the top-right header: **"AI / human agreement X%"**.

🗣️ **SAY ALOUD:**
> "Finally, look at the agreement rate up here in the header. This is not a synthetic benchmark. It is calculated dynamically from our append-only SQLite audit ledger joined with our AI recommendation log. In SQLite, UPDATE and DELETE are blocked by database triggers, giving us an immutable, tamper-proof record of every human decision."

---

## STEP 5: Voice Agent & Live Booking (6:30 – 7:30)

📍 **SCREEN:** Switch to Tab 5 (`http://localhost:5174/voice`)

👉 **ACTION:** Show the Voice Agent interface and the **"Recent Bookings"** panel on the right.

🗣️ **SAY ALOUD:**
> "The third pillar of OmniRAG is our Voice Agent. We integrate with Retell AI for telephony, speech-to-text, and audio streaming over a high-speed WebSocket. OmniRAG's backend serves as the brain.
>
> When a customer calls in, the backend identifies whether they're asking FAQ questions or want to book an appointment. If they want to book, our intent extractor captures their service, address, phone number, and name.
>
> Once confirmed, it writes the booking to our database, triggers our n8n booking workflow to update calendar records, confirms the booking to the caller, and automatically terminates the call."

---

## STEP 6: Conclusion (7:30 – 8:00)

📍 **SCREEN:** Back to Tab 1 (`http://localhost:5174/chat`)

🗣️ **SAY ALOUD:**
> "To wrap up: OmniRAG bridges the gap between RAG retrieval, workflow automation, and production governance. By separating intake into workflows, policy scoring into AI graph pipelines, and final approvals into an RBAC-gated audit ledger, we get full automation speed without sacrificing human accountability.
>
> Thank you so much for your time, and I look forward to your questions!"

---

### 🛠️ Quick Rehearsal Cheat Sheet

| Step | Tab / URL | Primary Action | Key Talking Point |
| :--- | :--- | :--- | :--- |
| **Intro** | Tab 1 (`/chat`) | Introduce OmniRAG | AI with human accountability & automation seams |
| **RAG** | Tab 1 (`/chat`) | Show Documents, ask FAQ | Vector grounding in Qdrant with citations |
| **Automation** | Tab 2 (`/automation`) & Tab 3 (`n8n:5678`) | Show pipeline, run Live Webhook query, show n8n canvas | Workflow owns intake & notifications; code owns AI & audit |
| **RBAC & T&S** | Tab 1 (`/chat`) ➔ Tab 4 (`/moderation`) | Point to Admin badge, review 3 queue items (Approve, Escalate, Reject) | Role claims, route guards, multi-agent consensus, append-only ledger |
| **Voice** | Tab 5 (`/voice`) | Show Voice Agent & Recent Bookings | Telephony via Retell, WebSocket LLM brain, automated booking |
| **Outro** | Tab 1 (`/chat`) | Closing recap | Production-grade governance |
