"""
Voice agent endpoint — Retell AI Custom LLM WebSocket integration.

Retell owns telephony, speech-to-text, and text-to-speech (a real phone
number, turn-taking, interruption handling). This endpoint is the "brain"
Retell calls into on every conversation turn: it receives the live call
transcript over a WebSocket, answers questions using OmniRAG's existing RAG
pipeline (same Qdrant index the chat/webhook endpoints use), or — when the
caller wants to schedule a job — extracts the booking details and triggers
an n8n automation webhook to actually create the appointment.

Protocol reference: https://docs.retellai.com/api-references/llm-websocket

Design note: Retell is the transport/telephony layer; OmniRAG stays the
agent brain (retrieval + prompt engineering + automation triggers). No
audio ever touches this process directly.
"""

import asyncio
import json
import logging
import re

import httpx
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ai.llm_client import LLMClient
from config.settings import settings
from db.bookings import (
    get_booking,
    list_bookings,
    record_booking,
    record_follow_up_call,
)
from services.embedding_service import embedding_service
from services.db.qdrant_service import get_qdrant_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["Voice Agent"])


class WebCallResponse(BaseModel):
    access_token: str
    call_id: str


class BookingResponse(BaseModel):
    id: int
    call_id: str | None
    service: str
    address: str | None
    phone: str | None
    customer_name: str | None
    preferred_day: str | None
    preferred_time: str | None
    status: str
    created_at: str


@router.get("/bookings", response_model=list[BookingResponse])
def list_bookings_endpoint(limit: int = 20):
    """Bookings the voice agent has actually confirmed — proof the
    automation trigger produces a real, persisted record, not just a
    POST to a stub endpoint."""
    return list_bookings(limit=limit)


@router.post("/web-call", response_model=WebCallResponse)
async def create_web_call():
    """
    Start a Retell web-call session server-side (keeps the Retell API key
    off the frontend) and hand back an access token. The OmniRAG frontend
    uses this token with Retell's browser SDK to run the call directly
    inside our own UI — the end user never sees Retell's dashboard, only
    OmniRAG. Retell's Custom LLM websocket (below) still supplies every
    word the agent says; this endpoint only starts the call session.
    """
    if not settings.retell_api_key or not settings.retell_agent_id:
        raise HTTPException(status_code=503, detail="Voice agent is not configured")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                # v2, not v3: RetellWebClient 2.x can't join v3 "gateway" calls (error_retell); v2 sunsets 2026-09-30.
                "https://api.retellai.com/v2/create-web-call",
                headers={
                    "Authorization": f"Bearer {settings.retell_api_key}",
                    "Content-Type": "application/json",
                },
                json={"agent_id": settings.retell_agent_id},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error(
            f"Retell create-web-call failed: {e.response.status_code} - {e.response.text}"
        )
        raise HTTPException(status_code=502, detail="Failed to start voice call")
    except Exception as e:
        logger.error(f"Retell create-web-call error: {e}")
        raise HTTPException(status_code=502, detail="Failed to start voice call")

    return WebCallResponse(access_token=data["access_token"], call_id=data["call_id"])


class OutboundFollowUpRequest(BaseModel):
    booking_id: int
    to_number: str  # E.164, e.g. "+15875551234" — not derived from the
    # booking's captured `phone`, since that field is whatever the caller
    # said verbatim during the call (see the intent-extraction rules
    # below) and isn't guaranteed to be a dialable, correctly-formatted
    # number.


class OutboundFollowUpResponse(BaseModel):
    call_id: str
    status: str


@router.post("/outbound-follow-up", response_model=OutboundFollowUpResponse)
async def trigger_outbound_follow_up(payload: OutboundFollowUpRequest):
    """
    Place an outbound call to confirm an emergency dispatch time against an
    existing booking (e.g. "your technician is still on for the 2-hour
    window — can you confirm someone will be home?").

    Deliberately a separate Retell endpoint from create_web_call above:
    outbound calling is documented at v2/create-phone-call, not v3 — the
    v2->v3 migration above was a real, Retell-issued deprecation notice
    that only covers create-web-call, and there is no equivalent notice
    for the phone-call endpoint. Using what's actually documented per
    endpoint rather than assuming the same version applies everywhere.

    Implementation complete — unverified live pending telephony credit
    check. Outbound calling requires a purchased/imported Retell number
    (RETELL_FROM_NUMBER) and spends per-minute call credit; neither has
    been confirmed live as of this writing, so this has only been
    exercised against Retell's documented request/response shape, not a
    real phone call. Not claiming a test result that hasn't happened.
    """
    if not settings.retell_api_key or not settings.retell_agent_id:
        raise HTTPException(status_code=503, detail="Voice agent is not configured")
    if not settings.retell_from_number:
        raise HTTPException(
            status_code=503,
            detail="Outbound calling is not configured (RETELL_FROM_NUMBER unset)",
        )

    booking = get_booking(payload.booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.retellai.com/v2/create-phone-call",
                headers={
                    "Authorization": f"Bearer {settings.retell_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from_number": settings.retell_from_number,
                    "to_number": payload.to_number,
                    "override_agent_id": settings.retell_agent_id,
                    "retell_llm_dynamic_variables": {
                        "customer_name": booking.get("customer_name") or "there",
                        "service": booking["service"],
                        "address": booking.get("address") or "",
                    },
                    "metadata": {
                        "booking_id": payload.booking_id,
                        "purpose": "dispatch_confirmation",
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error(
            f"Retell create-phone-call failed: {e.response.status_code} - {e.response.text}"
        )
        raise HTTPException(status_code=502, detail="Failed to trigger outbound call")
    except Exception as e:
        logger.error(f"Retell create-phone-call error: {e}")
        raise HTTPException(status_code=502, detail="Failed to trigger outbound call")

    call_id = data.get("call_id", "")
    try:
        record_follow_up_call(payload.booking_id, call_id)
    except Exception as e:
        # The call has already been accepted by Retell at this point — a
        # local logging failure shouldn't turn into a 502 for a call that
        # actually went out. Log and degrade, don't block the response.
        logger.error(
            f"Failed to record follow-up call for booking {payload.booking_id}: {e}"
        )

    return OutboundFollowUpResponse(call_id=call_id, status="triggered")


SYSTEM_INSTRUCTION = (
    "You are the phone assistant for Apex HVAC & Plumbing, an HVAC and "
    "plumbing company serving Alberta, Canada. This is a live phone call, "
    "not a chat window. Answer in ONE short sentence, under 20 words — a "
    "caller will not wait through a long answer. Ground every factual "
    "answer (service areas, pricing, hours, troubleshooting) strictly in "
    "the provided context — never invent a price, address, or policy that "
    "isn't in it. If the context doesn't cover the question, say so "
    "briefly and offer to have a human follow up instead of guessing."
)

# Local CPU inference costs real wall-clock seconds per generated token —
# every extra sentence is seconds a caller sits in silence. Cap output hard
# as a backstop regardless of how well the model follows the brevity
# instruction above.
RAG_ANSWER_MAX_TOKENS = 60

# Deliberately asks the model to name what's still missing rather than
# guessing — this is the ambiguity-handling seam: the agent asks a
# clarifying question instead of booking with incomplete/assumed details.
INTENT_PROMPT_TEMPLATE = """Classify the caller's latest message. Respond with ONLY compact JSON, no prose, no markdown fences.

Schema:
{{"intent": "book_appointment" | "question" | "other", "service": string|null, "address": string|null, "phone": string|null, "customer_name": string|null, "preferred_day": string|null, "preferred_time": string|null, "missing_fields": string[]}}

Rules:
- intent="book_appointment" only if the caller is clearly asking to schedule/book a job.
- "missing_fields" lists any of [service, address, phone, customer_name] that are still unknown — do not guess values.
- "address" must be the caller's own words, verbatim. Never infer, complete, autocorrect, or guess a street number, unit, or city the caller did not actually say — a partial or unclear address counts as missing, not as a best guess.
- "phone" must also be exactly what the caller said, digit for digit — do not normalize, autocomplete, or assume a missing digit.
- preferred_day/preferred_time are nice to capture but are never required to confirm a booking.
- Otherwise intent="question" (they're asking something) or "other" (small talk, unclear).

Conversation so far:
{conversation}

Caller's latest message: "{message}"

JSON:"""

_SENTINEL = object()

_BOOKING_KEYWORDS = (
    "book",
    "appointment",
    "schedule",
    "reschedule",
    "reserve",
    "come by",
    "come out",
    "send someone",
    "set up a visit",
)


def _looks_like_booking_request(message: str) -> bool:
    """Cheap pre-filter so plain questions can skip the classification LLM
    call entirely. False negatives just fall through to the RAG path (worst
    case: an oddly-phrased booking request gets answered as a question
    instead of triggering the booking flow) — an acceptable tradeoff against
    doubling response latency on every single question asked."""
    lowered = message.lower()
    return any(kw in lowered for kw in _BOOKING_KEYWORDS)


_CLOSING_WORDS = set(
    "no nope nah ok okay alright great perfect awesome cool nice sounds good got "
    "thats that it its all is will be thatll should covers thank thanks cheers "
    "you so very much a lot bye goodbye nothing else more anymore questions "
    "everything im i am we are were think about now for need needed just only "
    "done finished set fine have day one evening take care see later talk to "
    "well sir maam appreciate appreciated help helping helpful youve been "
    "really calling your the".split()
)
# An unmistakable "I'm finished" — safe to hang up on immediately.
_CLOSING_STRONG = re.compile(
    r"\b(thats (it|all|everything|about it)|that is (it|all|everything)|"
    r"that will be (it|all)|thatll be (it|all)|that should be (it|all)|"
    r"that covers (it|everything)|nothing (else|more)|no more( questions)?|"
    r"all set|all good|all done|(im|i am|we are|were) "
    r"(good|done|finished|all set|set|fine)|bye|goodbye|take care|"
    r"have a (good|great|nice)|see you|talk to you later)\b"
)
_CLOSING_THANKS = re.compile(r"\b(thanks?|thank you|cheers|appreciate|appreciated)\b")
_CLOSING_ACK = re.compile(
    r"(?:(?:ok|okay|alright|great|perfect|awesome|cool|nice|good|sounds good|got it)\s*)+"
)


def _closing_kind(message: str, previous_agent: str = "") -> str | None:
    """How to treat a caller who may be wrapping up:

    "end"  — clearly done ("that's it", "I'm all set", "bye"): say goodbye and
             hang up. Also a bare thanks/"no"/"okay" once we've already asked
             whether there's anything else.
    "soft" — a thanks or "okay" that might just be acknowledging an answer:
             ask "anything else?" instead of hanging up.
    None   — anything else, including "thanks, also do you fix boilers?".

    The match is on the *whole* utterance being closing words, deliberately:
    hanging up on someone who wasn't finished is far worse than missing a
    goodbye, so one unrecognised word means "not a goodbye".
    """
    text = re.sub(r"[^a-z\s]", "", message.lower().replace("'", "").replace("’", ""))
    tokens = text.split()
    if not tokens or len(tokens) > 12:
        return None
    if not all(t in _CLOSING_WORDS for t in tokens):
        return None
    joined = " ".join(tokens)
    asked_more = "anything else" in previous_agent.lower()

    if _CLOSING_STRONG.search(joined):
        return "end"
    if all(t in {"no", "nope", "nah"} for t in tokens):
        return "end" if asked_more else None
    if _CLOSING_THANKS.search(joined) or _CLOSING_ACK.fullmatch(joined):
        return "end" if asked_more else "soft"
    return None


def _last_agent_message(transcript: list) -> str:
    for turn in reversed(transcript or []):
        if turn.get("role") == "agent" and (turn.get("content") or "").strip():
            return turn["content"]
    return ""


def _extract_conversation(transcript: list) -> tuple[str, str]:
    """Return (full transcript as text, latest caller utterance)."""
    lines = []
    latest_user = ""
    for turn in transcript or []:
        role = turn.get("role", "user")
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"{role}: {content}")
        if role == "user":
            latest_user = content
    return "\n".join(lines), latest_user


async def _classify_intent(llm: LLMClient, conversation: str, message: str) -> dict:
    prompt = INTENT_PROMPT_TEMPLATE.format(
        conversation=conversation or "(none yet)", message=message
    )
    fallback = {
        "intent": "question",
        "service": None,
        "address": None,
        "phone": None,
        "customer_name": None,
        "preferred_day": None,
        "preferred_time": None,
        "missing_fields": [],
    }
    try:
        raw = await asyncio.to_thread(
            llm.generate, prompt, temperature=0.0, max_tokens=200
        )
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return fallback
        parsed = json.loads(match.group(0))
        fallback.update({k: v for k, v in parsed.items() if k in fallback})
        return fallback
    except Exception as e:
        logger.warning(f"Voice intent classification failed, falling back to RAG: {e}")
        return fallback


async def _retrieve_context(question: str, k: int = 5) -> list[str]:
    try:
        query_vector = await embedding_service.generate_embedding(
            question, mode="query"
        )
    except Exception as e:
        logger.error(f"Voice RAG embedding failed: {e}")
        return []

    scope = (
        {"must": [{"key": "doc_name", "match": {"value": settings.voice_kb_doc_name}}]}
        if settings.voice_kb_doc_name
        else None
    )
    results = get_qdrant_service().search(
        query_vector=query_vector,
        tenant_id="default",
        k=k,
        embedding_id=settings.embedding_model,
        filters={},
        acl_filter=scope,
    )
    return [
        r.get("text") or r.get("content")
        for r in results
        if (r.get("text") or r.get("content"))
    ]


def _start_stream_worker(llm: LLMClient, prompt: str) -> asyncio.Queue:
    """Bridge the blocking Ollama stream generator onto the asyncio loop.

    Returns the queue directly (not an async generator) so the caller can
    apply asyncio.wait_for(queue.get(), ...) per item — timing out a bare
    queue.get() is harmless, whereas timing out an async generator's
    __anext__() would tear down the generator's frame and silently kill the
    stream (a real gotcha: cancellation propagates into the generator and
    exhausts it — every later __anext__() then just raises
    StopAsyncIteration instead of resuming). The background worker thread
    keeps running and pushing to the queue regardless of whether anyone is
    actively awaiting it, so nothing is lost across a timeout here.
    """
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def worker():
        try:
            for piece in llm.generate_stream(
                prompt,
                system_instruction=SYSTEM_INSTRUCTION,
                max_tokens=RAG_ANSWER_MAX_TOKENS,
            ):
                loop.call_soon_threadsafe(queue.put_nowait, piece)
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, e)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

    loop.run_in_executor(None, worker)
    return queue


BOOKING_REQUIRED_FIELDS = ("service", "address", "phone", "customer_name")
BOOKING_FIELDS = BOOKING_REQUIRED_FIELDS + ("preferred_day", "preferred_time")

# Speech-to-text often returns numbers as words ("four five two one McEwan
# Road"), not digits — a digit-only check rejected real addresses forever.
_DIGIT_WORDS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}
_NUMBER_WORDS = set(_DIGIT_WORDS) | {
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
    "hundred",
    "thousand",
}
_DIGIT_WORD_ALT = "|".join(_DIGIT_WORDS)
_DIGIT_RUN = re.compile(
    rf"\b(?:{_DIGIT_WORD_ALT})(?:[\s,.-]+(?:{_DIGIT_WORD_ALT}))+\b", re.IGNORECASE
)


def _spoken_digits_to_numerals(text: str) -> str:
    """ "four five two one McEwan Road" -> "4521 McEwan Road". Only runs of
    two or more digit words convert, so an ordinary "one" in a sentence is
    left alone."""
    return _DIGIT_RUN.sub(
        lambda m: "".join(
            _DIGIT_WORDS[w.lower()] for w in re.findall(r"[A-Za-z]+", m.group(0))
        ),
        text,
    )


def _has_street_number(address: str) -> bool:
    """A real street address has a number — as digits, or spoken."""
    normalized = _spoken_digits_to_numerals(address or "")
    if any(ch.isdigit() for ch in normalized):
        return True
    words = re.findall(r"[a-z]+", normalized.lower())
    if words and words[0] in _NUMBER_WORDS:  # "five McEwan Road"
        return True
    # "twenty one fifty McEwan Road" — two or more number words in a row
    return any(
        a in _NUMBER_WORDS and b in _NUMBER_WORDS for a, b in zip(words, words[1:])
    )


def _missing_booking_fields(intent: dict) -> list[str]:
    """Which required booking fields are actually missing.

    Deliberately does not trust the model's self-reported `missing_fields`
    — smaller models sometimes claim nothing's missing while still leaving
    a field null. Independently verify every required field actually has
    a value.
    """
    missing = [f for f in BOOKING_REQUIRED_FIELDS if not intent.get(f)]
    # A non-null address isn't necessarily a *usable* one — tested this
    # directly: the model will capture a vague phrase like "somewhere
    # near downtown" verbatim (correctly not fabricating a fake precise
    # address) but won't reliably flag it as missing on its own. A real
    # address always has a street number; treat one with none as still
    # missing. Asked first (not last) so the caller isn't left wondering
    # why their answer was ignored.
    if "address" not in missing and not _has_street_number(intent["address"]):
        missing.insert(0, "address")
    return missing


def _merge_booking_fields(state: dict, intent: dict) -> dict:
    """Fold this turn's extraction into what the call has already
    established. The classifier re-reads the transcript from scratch each
    turn and a small model sometimes drops a detail the caller already gave
    (asking for the service twice) — a field once captured is never
    forgotten, and a usable address is never replaced by a vaguer one."""
    for field in BOOKING_FIELDS:
        new = intent.get(field)
        if not new:
            continue
        new = str(new)
        if field in ("address", "phone"):
            new = _spoken_digits_to_numerals(new)
        if (
            field == "address"
            and state.get("address")
            and _has_street_number(state["address"])
            and not _has_street_number(new)
        ):
            continue
        state[field] = new
    return {**intent, **{f: state.get(f) for f in BOOKING_FIELDS}}


_FIELD_PHRASES = {
    "service": "what service you need",
    "address": "the address for the visit",
    "phone": "the best phone number",
    "customer_name": "your name",
}


def _ask_for(field: str, vague_address: bool, first_ask: bool) -> str:
    if field == "address" and vague_address:
        return "I didn't catch a street number. Could you give me the full address, including the number?"
    lead = "Happy to book that — could you" if first_ask else "Got it. Could you"
    return f"{lead} tell me {_FIELD_PHRASES[field]}?"


async def _trigger_booking_webhook(details: dict, call_id: str) -> bool:
    if not settings.n8n_booking_webhook_url:
        logger.warning(
            "Voice booking requested but N8N_BOOKING_WEBHOOK_URL is not configured"
        )
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                settings.n8n_booking_webhook_url,
                json={**details, "call_id": call_id},
            )
            resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Voice booking webhook failed: {e}")
        return False


async def _handle_turn(
    websocket: WebSocket, llm: LLMClient, event: dict, call_id: str, state: dict
) -> None:
    response_id = event.get("response_id")
    transcript = event.get("transcript", [])
    conversation, latest_message = _extract_conversation(transcript)

    if not latest_message:
        await websocket.send_text(
            json.dumps(
                {
                    "response_type": "response",
                    "response_id": response_id,
                    "content": "Sorry, could you repeat that?",
                    "content_complete": True,
                }
            )
        )
        return

    # A caller who's wrapping up gets a goodbye or an "anything else?" — never
    # a knowledge-base lookup (which has nothing to match and answers with
    # whatever unrelated text scores highest). Not while a booking is
    # mid-way: "no" there is an answer, not a goodbye.
    closing = (
        None
        if state.get("in_booking")
        else _closing_kind(latest_message, _last_agent_message(transcript))
    )
    if closing == "end":
        await websocket.send_text(
            json.dumps(
                {
                    "response_type": "response",
                    "response_id": response_id,
                    "content": "Thanks for calling Apex HVAC & Plumbing — have a great day. Goodbye!",
                    "content_complete": True,
                    "end_call": True,
                }
            )
        )
        return
    if closing == "soft":
        await websocket.send_text(
            json.dumps(
                {
                    "response_type": "response",
                    "response_id": response_id,
                    "content": "Of course. Is there anything else I can help you with?",
                    "content_complete": True,
                }
            )
        )
        return

    # Skip the classification LLM call entirely when the message plainly
    # isn't a booking request — on CPU-only local inference, every call
    # costs several real seconds, and the RAG path already needs its own
    # generation call. Halving the round trips for the common "just asking
    # a question" case is the difference between a usable and unusable
    # response time here. Booking-shaped messages still get the full,
    # accurate LLM classification (needed for field extraction anyway).
    # Check the whole conversation so far, not just this message — once a
    # caller has said "I'd like to book an appointment", their follow-up
    # turns answering "which service?" naturally won't repeat that word,
    # but the conversation is still a booking flow in progress.
    if (
        state.get("in_booking")
        or _looks_like_booking_request(latest_message)
        or _looks_like_booking_request(conversation)
    ):
        intent = await _classify_intent(llm, conversation, latest_message)
    else:
        intent = {
            "intent": "question",
            "service": None,
            "address": None,
            "phone": None,
            "customer_name": None,
            "preferred_day": None,
            "preferred_time": None,
            "missing_fields": [],
        }

    # Once a booking is under way, a bare answer like "it's repair" or a
    # street address is still part of it, even if the classifier labels the
    # turn "other". A genuine question mid-booking still gets answered below.
    if state.get("in_booking") and intent["intent"] == "other":
        intent["intent"] = "book_appointment"

    if intent["intent"] == "book_appointment":
        state["in_booking"] = True
        details = _merge_booking_fields(state, intent)
        missing = _missing_booking_fields(details)
        if missing:
            vague_address = missing[0] == "address" and bool(details.get("address"))
            ask = _ask_for(missing[0], vague_address, first_ask=not state.get("asked"))
            state["asked"] = True
            await websocket.send_text(
                json.dumps(
                    {
                        "response_type": "response",
                        "response_id": response_id,
                        "content": ask,
                        "content_complete": True,
                    }
                )
            )
            return

        payload = {k: details[k] for k in BOOKING_FIELDS}
        tool_call_id = f"book-{call_id}-{response_id}"
        await websocket.send_text(
            json.dumps(
                {
                    "response_type": "tool_call_invocation",
                    "tool_call_id": tool_call_id,
                    "name": "book_appointment",
                    "arguments": json.dumps(payload),
                }
            )
        )

        booked = await _trigger_booking_webhook(payload, call_id)

        await websocket.send_text(
            json.dumps(
                {
                    "response_type": "tool_call_result",
                    "tool_call_id": tool_call_id,
                    "content": "booked" if booked else "automation_unavailable",
                    "successful": booked,
                }
            )
        )

        if booked:
            record_booking(
                service=details["service"],
                call_id=call_id,
                address=details.get("address"),
                phone=details.get("phone"),
                customer_name=details.get("customer_name"),
                preferred_day=details.get("preferred_day"),
                preferred_time=details.get("preferred_time"),
            )
            # preferred_day is optional now (never blocks a booking), so the
            # confirmation can't assume it's there.
            when = (
                f" on {details['preferred_day']}"
                if details.get("preferred_day")
                else ""
            )
            content = f"You're all set for {details['service']}{when} at {details['address']}. Anything else?"
            state.clear()
        else:
            # Failure mode: don't pretend it worked — degrade to a human handoff.
            content = "I've got your details, but I'm having trouble reaching the booking system right now — I'll have someone confirm with you shortly."
            state.clear()
        await websocket.send_text(
            json.dumps(
                {
                    "response_type": "response",
                    "response_id": response_id,
                    "content": content,
                    "content_complete": True,
                }
            )
        )
        return

    # Otherwise: answer from the knowledge base, streamed for natural cadence.
    context_chunks = await _retrieve_context(latest_message)
    if not context_chunks:
        await websocket.send_text(
            json.dumps(
                {
                    "response_type": "response",
                    "response_id": response_id,
                    "content": "I don't have that information on hand — I'll have someone follow up with you.",
                    "content_complete": True,
                }
            )
        )
        return

    context = "\n\n---\n\n".join(context_chunks[:5])
    prompt = (
        "Answer the caller's question using only the context below. "
        "If the context doesn't cover it, say you're not sure.\n\n"
        f"Context:\n{context}\n\n"
        f"Caller's question: {latest_message}"
    )

    try:
        # Most of the wait here is prompt prefill on CPU, before the model
        # emits its first token — capping output length doesn't touch that.
        # Rather than one filler then dead air, keep reassuring the caller
        # every few seconds until real content starts arriving (capped, so
        # it doesn't turn into a broken record on a truly slow answer).
        queue = _start_stream_worker(llm, prompt)
        reassurances_sent = 0
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=4.0)
            except asyncio.TimeoutError:
                if reassurances_sent < 2:
                    reassurances_sent += 1
                    await websocket.send_text(
                        json.dumps(
                            {
                                "response_type": "response",
                                "response_id": response_id,
                                "content": "Still looking that up. ",
                                "content_complete": False,
                            }
                        )
                    )
                continue
            if item is _SENTINEL:
                break
            if isinstance(item, Exception):
                raise item
            await websocket.send_text(
                json.dumps(
                    {
                        "response_type": "response",
                        "response_id": response_id,
                        "content": item,
                        "content_complete": False,
                    }
                )
            )
    except Exception as e:
        logger.error(f"Voice RAG generation failed: {e}")
        await websocket.send_text(
            json.dumps(
                {
                    "response_type": "response",
                    "response_id": response_id,
                    "content": "Sorry, I'm having trouble finding that right now.",
                    "content_complete": True,
                }
            )
        )
        return

    await websocket.send_text(
        json.dumps(
            {
                "response_type": "response",
                "response_id": response_id,
                "content": "",
                "content_complete": True,
            }
        )
    )


@router.websocket("/llm-websocket/{call_id}")
async def retell_llm_websocket_open(websocket: WebSocket, call_id: str):
    """Unauthenticated variant — only reachable when no secret is configured."""
    if settings.voice_websocket_secret:
        await websocket.close(code=4401)
        return
    await _run_call(websocket, call_id)


@router.websocket("/llm-websocket/{secret}/{call_id}")
async def retell_llm_websocket(websocket: WebSocket, secret: str, call_id: str):
    """
    Retell appends "/{call_id}" to whatever base URL you configure in its
    dashboard — a query string (?secret=...) doesn't survive that (the
    appended call_id would land inside the query value, not a new path
    segment). So the secret is a path segment instead: configure Retell's
    Custom LLM URL as wss://<host>/api/voice/llm-websocket/<secret>
    """
    if settings.voice_websocket_secret and secret != settings.voice_websocket_secret:
        await websocket.close(code=4401)
        return
    await _run_call(websocket, call_id)


async def _run_call(websocket: WebSocket, call_id: str) -> None:
    await websocket.accept()
    logger.info(f"Voice call connected: {call_id}")

    llm = LLMClient()
    booking_state: dict = {}  # what this call has established so far

    try:
        await websocket.send_text(
            json.dumps(
                {
                    "response_type": "config",
                    "config": {
                        "auto_reconnect": True,
                        "call_details": True,
                        "transcript_with_tool_calls": True,
                    },
                }
            )
        )

        while True:
            raw = await websocket.receive_text()
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(
                    f"Voice call {call_id}: received non-JSON frame, ignoring"
                )
                continue

            interaction_type = event.get("interaction_type")

            try:
                if interaction_type == "ping_pong":
                    await websocket.send_text(
                        json.dumps(
                            {
                                "response_type": "ping_pong",
                                "timestamp": event.get("timestamp"),
                            }
                        )
                    )
                elif interaction_type == "call_details":
                    logger.info(
                        f"Voice call {call_id} details: {event.get('call', {})}"
                    )
                elif interaction_type == "update_only":
                    continue
                elif interaction_type in ("response_required", "reminder_required"):
                    await _handle_turn(websocket, llm, event, call_id, booking_state)
                else:
                    logger.debug(
                        f"Voice call {call_id}: unhandled interaction_type={interaction_type}"
                    )
            except Exception as e:
                # Never let one bad turn kill the call.
                logger.error(
                    f"Voice call {call_id}: error handling turn: {e}", exc_info=True
                )
                response_id = event.get("response_id")
                if response_id is not None:
                    try:
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "response_type": "response",
                                    "response_id": response_id,
                                    "content": "Sorry, something went wrong on my end — could you say that again?",
                                    "content_complete": True,
                                }
                            )
                        )
                    except Exception:
                        # The caller likely already hung up (e.g. ended the
                        # call mid-response) — nothing more we can do here.
                        # The outer loop's receive_text() will raise
                        # WebSocketDisconnect on the next iteration.
                        logger.debug(
                            f"Voice call {call_id}: couldn't send error recovery message, socket already closed"
                        )
    except WebSocketDisconnect:
        logger.info(f"Voice call disconnected: {call_id}")
    except Exception as e:
        # Final safety net — an unexpected error here should never surface
        # as an unhandled traceback; the caller just experiences a dropped call.
        logger.error(
            f"Voice call {call_id}: unhandled error, call ended: {e}", exc_info=True
        )
