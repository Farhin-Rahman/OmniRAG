"""
Seed realistic campaigns into the Trust & Safety moderation queue.

Usage:
    docker exec omnirag-backend-python python scripts/seed_moderation_queue.py
Or from host:
    python scripts/seed_moderation_queue.py
"""

import os
import sys
import httpx

BASE_URL = os.getenv("API_URL", "http://localhost:8080" if os.path.exists("/app/backend") else "http://localhost:8081")

CAMPAIGNS = [
    {
        "campaign_id": "camp-clean-garden-01",
        "title": "Riverside Community Garden Expansion",
        "description": "Funding raised beds, organic soil, and heirloom seeds for the Riverside Youth Center garden program in Nashville, TN. All purchases are itemized and verified with local supplier Nashville Seed Co.",
        "target_amount": 3500.0,
    },
    {
        "campaign_id": "camp-holistic-recovery-02",
        "title": "Holistic Wellness & Recovery Equipment",
        "description": "Raising funds to purchase specialized natural wellness and massage therapy equipment for our local community recovery group. We aim to help individuals with chronic fatigue and stress recovery through alternative sessions.",
        "target_amount": 7500.0,
    },
    {
        "campaign_id": "camp-9a6bd2007b41",
        "title": "Guaranteed return investment pool",
        "description": "Join now and double your money in 30 days. High yield returns guaranteed for all early backers.",
        "target_amount": 50000.0,
    },
]

def seed_queue():
    print(f"Connecting to {BASE_URL}/api/webhooks/campaign-review ...")
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        for c in CAMPAIGNS:
            try:
                print(f"\nSubmitting: {c['title']} (${c['target_amount']})")
                resp = client.post("/api/webhooks/campaign-review", json=c)
                if resp.status_code == 200:
                    data = resp.json()
                    print(f"  -> Recommended Action: {data.get('recommended_action')}")
                    print(f"  -> Risk Score: {data.get('risk_score')} ({data.get('risk_category')})")
                    print(f"  -> Consensus Used: {data.get('consensus_used')}")
                else:
                    print(f"  -> HTTP Error {resp.status_code}: {resp.text}")
            except Exception as e:
                print(f"  -> Error: {e}")

if __name__ == "__main__":
    seed_queue()
