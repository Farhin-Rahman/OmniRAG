# OmniRAG — Hands-On Testing & Reviewer Runbook 🚀

Welcome to the **OmniRAG** test runbook. This guide is designed for reviewers, recruiters, and hiring managers to explore and test the platform step-by-step on their own machine in **5–10 minutes**.

---

## 📌 Executive Summary

**OmniRAG** is an enterprise AI operations platform built for safe, compliant AI deployment:
1. **Smart Document Search (RAG):** Answers customer questions grounded strictly in company documents with clickable source citations (zero hallucinations).
2. **Trust & Safety Moderation:** Evaluates financial campaigns with deterministic rules, policy-grounded AI risk scoring, and a multi-agent consensus judge.
3. **Role-Based Access Control (RBAC):** Only authorized team members can access moderation tools.
4. **Human-in-the-Loop Governance:** AI recommends, but human managers always make the final call, permanently recorded to an immutable audit ledger.
5. **Workflow Automation (n8n):** Automated background pipelines handle data ingestion, webhook events, and team notifications.
6. **AI Voice Agent:** An automated phone assistant that answers customer questions and captures appointment bookings.

---

## 🌐 Quick Links (Open in Your Browser)

| Section | Local URL | What It Does |
| :--- | :--- | :--- |
| **Chat & Document Workspace** | [http://localhost:5174/chat](http://localhost:5174/chat) | Document library & cited AI search |
| **Trust & Safety Moderation** | [http://localhost:5174/moderation](http://localhost:5174/moderation) | RBAC-gated campaign review queue |
| **Automations Dashboard** | [http://localhost:5174/automation](http://localhost:5174/automation) | Live processing pipeline & webhook tester |
| **Workflow Engine (n8n)** | [http://localhost:5678](http://localhost:5678) | Visual background automation workflows |
| **Voice Agent** | [http://localhost:5174/voice](http://localhost:5174/voice) | Inbound call agent & appointment dashboard |

---

## 🧪 Interactive Testing Steps

---

### Step 1: Test Role-Based Access Control (RBAC) 🔐

OmniRAG uses strict role-based access control. Moderation tools are completely inaccessible to standard users.

#### A. See what an Admin sees:
1. Make sure you are signed in as an admin (e.g., `sadiafarhin62@gmail.com`).
2. Go to [http://localhost:5174/chat](http://localhost:5174/chat).
3. Look at the bottom-left sidebar:
   - Notice the green **"Admin"** pill next to your profile.
   - Notice the green **"Trust & Safety"** shield button above the navigation buttons.

#### B. See what a Standard User sees:
1. Open your terminal and run:
   ```powershell
   docker exec omnirag-backend-python python revoke_admin.py sadiafarhin62@gmail.com
   ```
2. Refresh the browser page (`http://localhost:5174/chat`).
3. Notice:
   - The **"Admin"** tag is gone.
   - The green **"Trust & Safety"** button is **completely hidden**.
4. Try typing `http://localhost:5174/moderation` directly in your browser's address bar.
   - **Result:** The system automatically intercepts the request and redirects you back to `/chat`. (Backend API calls also return `403 Forbidden`).

#### C. Restore Admin access for the rest of your test:
Run this command in your terminal:
```powershell
docker exec omnirag-backend-python python set_admin.py sadiafarhin62@gmail.com
```
Refresh the page — your Admin badge and Trust & Safety button are restored!

---

### Step 2: Test Trust & Safety Moderation 🛡️

1. Click the green **"Trust & Safety"** button in the sidebar (or visit [http://localhost:5174/moderation](http://localhost:5174/moderation)).
2. Look at the left pane under **"Pending review (3)"**. Three pre-loaded campaigns are ready for evaluation:

---

#### 🟢 Test Case 1: Legitimate Campaign (APPROVE)
1. Click on **"Riverside Community Garden Expansion"** ($3,500).
2. **Review the AI Analysis:**
   - **Recommendation:** `APPROVE`
   - **Risk Score:** `0.10` (Low)
   - **Rationale:** The AI verified the named organization (*Riverside Youth Center*), local supplier (*Nashville Seed Co.*), and itemized budget.
3. **Take Action:** Click the green **"Approve"** button.
   - **Result:** A green notification confirms the approval, the campaign is logged to the immutable audit ledger, and it drops off the pending queue.

---

#### 🟡 Test Case 2: Borderline Appeal — Multi-Agent Consensus (ESCALATE)
1. Click on **"Holistic Wellness & Recovery Equipment"** ($7,500).
2. **Review the AI Analysis:**
   - **Recommendation:** `ESCALATE`
   - **Risk Score:** `0.55` (Unverifiable)
   - **Source:** Look at the source badge: **`langgraph-auto-consensus`**!
   - **Why:** When a campaign's risk score lands in the ambiguous middle zone (0.3–0.7), OmniRAG automatically convenes a **consensus panel of 3 independent AI reviewers plus a judge**. All agreed that while the wellness center sounds plausible, it lacks itemized equipment quotes or verification documents.
3. **Take Action:** Click the yellow **"Escalate"** button.
   - Enter notes: `Requesting official equipment invoices.`
   - Click **Confirm**.

---

#### 🔴 Test Case 3: Policy Violation / Scam (REJECT)
1. Click on **"Guaranteed return investment pool"** ($50,000).
2. **Review the AI Analysis:**
   - **Recommendation:** `REJECT`
   - **Risk Score:** `1.00` (Policy Violation)
   - **Rationale:** Caught by deterministic rules: contains banned phrases *"guaranteed return"* and *"double your money"*. Zero LLM tokens were wasted, and an alert was sent directly to Slack.
3. **Take Action:** Click the red **"Reject"** button.
   - Enter reason code: `financial_fraud_guaranteed_returns`
   - Click **Confirm**.

---

#### 📊 Live Agreement Metric
- Look at the top-right header: **"AI / human agreement X%"**.
- This metric is computed live by joining the permanent human audit ledger against the AI recommendation log, giving leadership real-time visibility into AI reliability.

> 💡 **Resetting the Queue:** If you want to reload the 3 test campaigns to test again, run:
> ```powershell
> python scripts/seed_moderation_queue.py
> ```

---

### Step 3: Test Smart Document Search (RAG) 📚

1. Go to [http://localhost:5174/chat](http://localhost:5174/chat).
2. Click **"Document Library"** in the sidebar to see uploaded company manuals (e.g. `apex_hvac_faq.pdf`).
3. Click back to **"Chat"**.
4. In the question box at the bottom, type:
   ```text
   What maintenance does an HVAC system require?
   ```
5. Press Enter.
6. **Observe:** The AI answers accurately using the manual and provides **clickable citations** showing the exact source document and section.

---

### Step 4: Test Automations & Webhooks ⚙️

1. Navigate to [http://localhost:5174/automation](http://localhost:5174/automation).
2. **Visual Ingestion Pipeline:** Look at the top diagram showing the 5 real-time processing stages: **Upload ➔ Parse ➔ Chunk ➔ Embed ➔ Index**, along with live document stats.
3. **Live Webhook Test:** Scroll down to the interactive testing tool:
   - In the **Question** box, type:
     ```text
     What is the warranty policy?
     ```
   - Click the blue **"Send"** button.
   - **Observe:** The system returns clean, formatted JSON with the answer and source citations, demonstrating how external platforms (like Zapier, Make, or custom apps) can query the AI engine.
4. **Visual Workflow Canvas (Optional):** Open [http://localhost:5678](http://localhost:5678) to view the n8n automation workflow connecting intake webhooks to Slack notifications.

---

### Step 5: Test the AI Voice Agent 📞

1. Navigate to [http://localhost:5174/voice](http://localhost:5174/voice).
2. Look at the **"Recent Bookings"** dashboard on the right.
3. **How it operates:**
   - Inbound phone calls are received via telephony (Retell AI).
   - OmniRAG's backend acts as the real-time conversational brain over WebSockets.
   - When a caller requests an appointment, the agent conversationally extracts their **service type, address, phone number, and name**.
   - Once confirmed, the agent registers the booking into the database, triggers the team calendar automation, confirms with the caller, and automatically cuts off the call.

---

## 🛠️ CLI Quick Reference

```powershell
# Grant Trust & Safety Admin Role
docker exec omnirag-backend-python python set_admin.py <email>

# Revoke Trust & Safety Admin Role
docker exec omnirag-backend-python python revoke_admin.py <email>

# Re-seed the 3 Moderation Test Campaigns
python scripts/seed_moderation_queue.py

# Run Automated Backend Test Suite
docker exec omnirag-backend-python pytest
```

---

*Thank you for evaluating OmniRAG! For any questions or deep architectural discussions, please reach out directly.*
