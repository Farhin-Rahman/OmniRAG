"""
Manual smoke test for the Retell Custom-LLM voice WebSocket endpoint
(backend/routes/voice.py). Simulates the message sequence Retell sends
during a real call, so you can verify the RAG-answer path and the
booking-automation path without a Retell account or phone call.

Usage:
    python scripts/test_voice_websocket.py [ws_url]

Default ws_url assumes the backend is reachable at localhost:8081
(the port docker-compose exposes it on). If VOICE_WEBSOCKET_SECRET is
set in your .env, append it: ws://localhost:8081/api/voice/llm-websocket/test-call-001?secret=...
"""

import asyncio
import itertools
import json
import sys

import websockets

DEFAULT_URL = "ws://localhost:8081/api/voice/llm-websocket/test-call-001"
_response_id = itertools.count(1)


def response_required(message: str, history: list) -> dict:
    transcript = list(history)
    transcript.append({"role": "user", "content": message})
    return {
        "interaction_type": "response_required",
        "response_id": next(_response_id),
        "transcript": transcript,
    }


async def send_turn(ws, event: dict, label: str) -> str:
    print(f"\n>>> [{label}] caller says: {event['transcript'][-1]['content']!r}")
    await ws.send(json.dumps(event))

    full_text = ""
    while True:
        msg = json.loads(await ws.recv())
        rtype = msg.get("response_type")
        if rtype == "response":
            full_text += msg.get("content", "")
            if msg.get("content_complete"):
                break
        elif rtype in ("tool_call_invocation", "tool_call_result"):
            print(f"    < {rtype}: {msg}")
        else:
            print(f"    < (unexpected message) {msg}")

    print(f"<<< [{label}] agent: {full_text!r}")
    return full_text


async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    print(f"Connecting to {url} ...")

    async with websockets.connect(url) as ws:
        config = json.loads(await ws.recv())
        print(f"Received config: {config}")
        assert config.get("response_type") == "config", "expected config message first"

        # Retell sends call metadata once the call starts.
        await ws.send(json.dumps({
            "interaction_type": "call_details",
            "call": {"call_id": "test-call-001", "from_number": "+15550001111"},
        }))

        # Keepalive check.
        await ws.send(json.dumps({"interaction_type": "ping_pong", "timestamp": 1234567890}))
        pong = json.loads(await ws.recv())
        print(f"Ping/pong reply: {pong}")
        assert pong.get("response_type") == "ping_pong"

        history: list = []

        # 1) RAG question path — needs documents ingested to return a real
        #    answer; with an empty index it should still respond gracefully
        #    ("I don't have that information...") rather than error out.
        ev = response_required("What are the key compliance requirements?", history)
        history = ev["transcript"]
        answer = await send_turn(ws, ev, "RAG question")
        history.append({"role": "agent", "content": answer})

        # 2) Booking request missing details — should ask a clarifying
        #    question, NOT call the automation webhook.
        ev = response_required("I'd like to book an appointment", history)
        history = ev["transcript"]
        answer = await send_turn(ws, ev, "Booking (incomplete)")
        history.append({"role": "agent", "content": answer})

        # 3) Booking request with everything needed — should trigger
        #    tool_call_invocation/result and POST to N8N_BOOKING_WEBHOOK_URL.
        ev = response_required(
            "I need drain cleaning this Tuesday afternoon, my name is Jane Doe", history
        )
        await send_turn(ws, ev, "Booking (complete)")

    print("\nSmoke test finished — no crashes, all turns answered.")


if __name__ == "__main__":
    asyncio.run(main())
