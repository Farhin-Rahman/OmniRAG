# OmniRAG — Recruiter & Reviewer Walkthrough Guide 🎬

> **Quick Summary:** OmniRAG is an enterprise AI operations platform that automates customer workflows while keeping humans in full control of critical decisions. It combines **smart document search (RAG)**, **automated background workflows (n8n)**, **fraud & policy moderation (Trust & Safety)**, and **an AI voice agent for appointment bookings**.

---

## ⚡ Quick Setup (Open These 4 Tabs Before Recording)

Open these tabs in your browser side-by-side:
1. **Tab 1 — Chat & Documents:** `http://localhost:5174/chat` (Signed in as `sadiafarhin62@gmail.com`)
2. **Tab 2 — Automations:** `http://localhost:5174/automation`
3. **Tab 3 — Automated Workflows (n8n):** `http://localhost:5678` (Open the "OmniRAG Trust & Safety — Campaign Intake" workflow)
4. **Tab 4 — Trust & Safety:** `http://localhost:5174/moderation` (Contains 3 pre-loaded campaigns to review)
5. **Tab 5 — Voice Agent:** `http://localhost:5174/voice`

*(Note: Everything is running locally in Docker. You do **not** need to redeploy anything on Render).*

---

## 💻 Quick Terminal Commands (Keep Handy)

If you want to demonstrate how access permissions work, or reset the test cards:
```powershell
# 1. Grant Admin Access (Shows green Admin tag & Trust & Safety button)
docker exec omnirag-backend-python python set_admin.py sadiafarhin62@gmail.com

# 2. Revoke Admin Access (Turns account back into a normal standard user)
docker exec omnirag-backend-python python revoke_admin.py sadiafarhin62@gmail.com

# 3. Reset Review Queue (Restores the 3 sample campaigns anytime for a fresh take)
python scripts/seed_moderation_queue.py
```

---

## ⏱️ Video Plan (~6–7 Minutes Total)

| Section | Time | What You Are Showing |
| :--- | :--- | :--- |
| **1. Intro** | 0:00 – 0:45 | High-level problem: scaling AI operations safely with human oversight. |
| **2. Document Chat** | 0:45 – 1:45 | Asking questions against company PDFs with real, clickable source citations. |
| **3. Automations** | 1:45 – 3:15 | Background pipelines (`/automation`) & automated intake workflow in n8n. |
| **4. Trust & Safety** | 3:15 – 5:30 | Role permissions (Admin vs Regular) + Reviewing the 3 campaigns (Approve, Escalate, Reject). |
| **5. Voice Agent** | 5:30 – 6:30 | An AI phone agent that answers calls and books appointments directly to the system. |
| **6. Wrap-Up** | 6:30 – 7:00 | Summary of business value: speed of automation + safety of human review. |

---

## STEP 1: Introduction (0:00 – 0:45)

📍 **Where to be:** Tab 1 (`http://localhost:5174/chat`)

🗣️ **What to say aloud:**
> "Hi everyone! Today I'm excited to walk you through OmniRAG. 
> 
> OmniRAG is an enterprise AI operations platform. When companies adopt AI, they face two big challenges: first, generic AI often hallucinates or gives inaccurate answers; and second, you can't trust an autonomous AI to make high-stakes decisions on its own — like approving financial payouts or booking customer jobs.
> 
> OmniRAG solves this by combining four core pillars:
> 1. Grounded document search with citations.
> 2. Automated background workflows to connect systems.
> 3. Trust & Safety moderation where AI assists, but a human manager always has the final say.
> 4. An AI voice agent that takes real customer calls and bookings.
> 
> Let's take a look at how it works."

---

## STEP 2: Smart Document Chat & Citations (0:45 – 1:45)

📍 **Where to be:** Tab 1 (`http://localhost:5174/chat`)

🖱️ **What to do:**
1. Click **"Document Library"** in the sidebar. Show that files (like `apex_hvac_faq.pdf`) are stored in the knowledge base.
2. Click back to **"Chat"**.
3. In the message box at the bottom, type:
   `What maintenance does an HVAC system need?`
4. Press Enter.

👀 **What you see:**
- The AI answers clearly in seconds.
- Below the answer, point to the source citation showing the exact document and section used.

💡 **How it works (in plain terms):**
- Instead of guessing from general internet training, the system searches the uploaded company document, finds the exact relevant paragraph, and bases its answer strictly on those facts.

🗣️ **What to say aloud:**
> "Here in our chat workspace, questions are strictly grounded in our company documents. Instead of making up answers, the AI retrieves the exact paragraphs from our uploaded manuals or policies, and provides clickable citations back to the source. This gives teams full confidence in accuracy."

---

## STEP 3: Automated Workflows & Webhooks (1:45 – 3:15)

📍 **Where to be:** Switch to Tab 2 (`http://localhost:5174/automation`)

🖱️ **What to do (Part A — Live Dashboard):**
1. Scroll across the top diagram: point out the 5 visual steps: **Upload ➔ Parse ➔ Chunk ➔ Embed ➔ Index**.
2. Point out the **Live Stats** counters: Total documents, Indexed & ready.
3. Scroll down to the **"Live Webhook Test"** box at the bottom:
   - In the Question box, type: `What is the warranty policy?`
   - Click the blue **"Send"** button.
   - Show the clean green JSON answer that appears instantly below.

🗣️ **What to say aloud:**
> "Under our Automations dashboard, we provide transparency into how data moves through the platform. This visual pipeline shows documents being processed and indexed in real-time.
> 
> We also provide secure webhook connections. For example, testing a query here instantly returns structured data that any external company system can use."

📍 **Where to be:** Switch to Tab 3 (`http://localhost:5678` — n8n Workflow)

🖱️ **What to do (Part B — Visual Automation):**
1. Show the visual node flow on the canvas:
   **Submission Webhook** ➔ **Data Normalization** ➔ **AI Review** ➔ **Slack Notification**.

💡 **How it works (in plain terms):**
- When someone submits a new campaign or form, this automated workflow receives it, cleans the data, runs the AI review in the background, and posts a notification into Slack.
- **Crucial Rule:** The automation sends alerts, but it is **never** allowed to automatically approve financial payouts. High-stakes approvals are strictly reserved for human reviewers.

🗣️ **What to say aloud:**
> "Here in n8n, we automate the heavy lifting. When a new submission arrives, this workflow automatically normalizes the data, sends it through our AI policy checks, and alerts our team in Slack. 
> 
> But notice the boundary: automation handles the intake and notifications, while human managers retain final approval authority. That brings us to our Trust and Safety system."

---

## STEP 4: Trust & Safety with Role Security (3:15 – 5:30)

📍 **Where to be:** Back to Tab 1 (`http://localhost:5174/chat`)

### A. Showing Role-Based Access Control (RBAC)

🖱️ **What to do:**
1. Look at the bottom-left sidebar under your user email.
2. Point your cursor to the green **"Admin"** badge and the green **"Trust & Safety"** shield button.

💡 **How it works (in plain terms):**
- Only authorized managers with the `TrustAndSafetyAdmin` role can see this button or access moderation tools.
- If a regular user logs in, the button is completely hidden. If an unauthorized user tries typing the `/moderation` link directly in their browser, the system automatically kicks them back to the chat screen.
- Backend permissions are also locked down, so unauthorized requests get rejected immediately.

🗣️ **What to say aloud:**
> "Before opening the moderation queue, notice down here by my profile: there's an 'Admin' badge and a green 'Trust & Safety' button.
> 
> Access is strictly controlled through Role-Based Access Control. Only accounts with the Trust & Safety manager role can see this button. If a regular team member logs in, this entire section is hidden, and if anyone tries navigating directly to the URL, our security guards bounce them back. Roles can easily be toggled right from our administrative terminal."

---

### B. Reviewing the Moderation Queue (3 Realistic Cases)

📍 **Where to be:** Click the green **"Trust & Safety"** button (or go to Tab 4: `http://localhost:5174/moderation`)

👀 **What you see:**
- The left column shows **"Pending review (3)"** with three realistic campaigns waiting for review.

---

#### 🟢 Case 1: Legitimate Campaign (APPROVE)
🖱️ **Click:** **"Riverside Community Garden Expansion"** ($3,500)
- **AI Recommendation:** `APPROVE` (Risk Score: 0.10 — Low)
- **AI Rationale:** Mentions verified organization (*Riverside Youth Center*), local supplier (*Nashville Seed Co.*), and itemized costs.
- **Action:** Click the green **"Approve"** button.
- **Result:** A green notification pops up: *"Campaign approved. Recorded to the audit ledger."* The item disappears from the pending list.

🗣️ **What to say aloud:**
> "Here is our first case: a community garden funding request. The AI analyzed the description, confirmed verified local partners and transparent costs, and gave it a very low risk score of 0.10, recommending approval. As the human manager, I confirm the details and click 'Approve'. It is permanently logged to our audit ledger."

---

#### 🟡 Case 2: Borderline Campaign — Multi-AI Consensus (ESCALATE)
🖱️ **Click:** **"Holistic Wellness & Recovery Equipment"** ($7,500)
- **AI Recommendation:** `ESCALATE` (Risk Score: 0.55 — Unverifiable)
- **Notice the source badge:** Reads **`langgraph-auto-consensus`**!

💡 **How it works (in plain terms):**
- This campaign sounds plausible, but lacks verifiable receipts or hospital paperwork.
- Because the risk was in the borderline zone, the system didn't rely on just one AI. It had **three independent AI reviewers vote on it**, and a judge synthesized the final recommendation to escalate for manual paperwork check.

🖱️ **Action:** Click the yellow **"Escalate"** button.
- In the notes box, type: `Requesting equipment invoices and official registration.`
- Click Confirm.

🗣️ **What to say aloud:**
> "Our second case is a borderline appeal for wellness equipment. Notice the badge says 'auto-consensus'. Because the risk fell in an ambiguous middle zone, our system automatically ran a consensus panel of three AI reviewers. They agreed that while the campaign is plausible, it lacks itemized supplier quotes. So it recommends escalating. I'll add a quick note requesting verification documents and confirm."

---

#### 🔴 Case 3: Scam / Policy Violation (REJECT)
🖱️ **Click:** **"Guaranteed return investment pool"** ($50,000)
- **AI Recommendation:** `REJECT` (Risk Score: 1.0 — Policy Violation)
- **AI Rationale:** Blocked immediately by policy rules: contains banned phrases *"guaranteed return"* and *"double your money"*.

💡 **How it works (in plain terms):**
- The system checks strict rule filters before calling expensive AI models.
- Obvious scam phrases are blocked instantly, and the safety team is alerted right away.

🖱️ **Action:** Click the red **"Reject"** button.
- In Reason Code, type: `financial_fraud_guaranteed_returns`
- Click Confirm.

🗣️ **What to say aloud:**
> "Our third case is an immediate rejection. Words like 'guaranteed return' and 'double your money' are caught by our automatic policy filters without wasting AI processing time. I click 'Reject', provide the reason code, and it's securely archived."

---

#### 📊 Live Agreement Metric (Top Right)
🖱️ **What to point to:** The percentage counter in the top-right header: **"AI / human agreement X%"**.

🗣️ **What to say aloud:**
> "Up here in the header, we track the live agreement rate between our AI recommendations and actual human decisions. This isn't a theoretical test — it measures how reliably the AI assists human reviewers in real daily operations."

---

## STEP 5: AI Voice Agent for Customer Bookings (5:30 – 6:30)

📍 **Where to be:** Switch to Tab 5 (`http://localhost:5174/voice`)

👀 **What you see:**
- The Voice Agent call screen.
- On the right side, the **"Recent Bookings"** dashboard showing confirmed appointments.

💡 **How it works (in plain terms):**
- Customers can call a phone number to ask questions or book a service.
- The voice AI answers questions conversationally using the document knowledge base.
- When the caller wants to book an appointment, the AI naturally gathers their **service type, address, phone number, and name**.
- Once confirmed, it saves the booking to the database, updates the team calendar, confirms with the customer, and hangs up the call.

🗣️ **What to say aloud:**
> "Finally, we have our Voice Agent. In addition to text and chat, OmniRAG can handle real inbound customer phone calls.
> 
> The voice agent answers questions naturally, and when a customer wants to schedule a service, it gathers their details — like their name, service needed, address, and phone number.
> 
> Once the customer confirms, the agent records the booking here in the system, triggers our calendar automation, confirms it to the caller, and automatically ends the call. This enables 24/7 automated booking without needing round-the-clock call center staff."

---

## STEP 6: Conclusion (6:30 – 7:00)

📍 **Where to be:** Back to Tab 1 (`http://localhost:5174/chat`)

🗣️ **What to say aloud:**
> "To recap: OmniRAG delivers the full package for modern AI operations. It grounds answers in real company data, connects workflows to save time, automates customer phone bookings, and crucially, maintains strict human-in-the-loop governance for Trust & Safety.
> 
> Thank you so much for watching, and I'd love to answer any questions you have!"

---

### 🎯 Practice Checklist

- [ ] All 5 tabs open and loaded in Chrome.
- [ ] Logged in as `sadiafarhin62@gmail.com` (green Admin badge visible).
- [ ] Moderation queue shows 3 items ready (`Riverside Garden`, `Holistic Recovery`, `Guaranteed Return`).
- [ ] If you ever need to reset the queue: run `python scripts/seed_moderation_queue.py` in your terminal.
- [ ] Speak naturally, smile, and focus on the business value!
