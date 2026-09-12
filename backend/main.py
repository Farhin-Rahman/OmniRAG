"""
Main application file for the OmniRAG backend.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from routes.chat import router as chat_router
from routes.webhooks import router as webhooks_router
from routes.documents import router as documents_router
from routes.voice import router as voice_router
from routes.campaigns import router as campaigns_router
from schemas.chat import ChatRequest
from services.db.qdrant_service import QdrantService
from services.db.sqlite_service import init_db
from db.audit import init_audit_db
from db.recommendations import init_recommendations_db
from services.rate_limiter import RateLimitMiddleware
from config.settings import settings
from config.logging import setup_logging
from utils.errors import (
    OmniRAGHTTPException,
    omnirag_exception_handler,
    generic_exception_handler,
)

setup_logging()

logger = logging.getLogger(__name__)

qdrant_service = QdrantService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application starting up")

    try:
        init_db()
    except Exception as e:
        logger.error(f"Failed to initialize SQLite db: {e}")

    try:
        init_audit_db()
    except Exception as e:
        logger.error(f"Failed to initialize audit ledger db: {e}")

    try:
        init_recommendations_db()
    except Exception as e:
        logger.error(f"Failed to initialize AI recommendations db: {e}")

    try:
        qdrant_service.initialize_qdrant_collection()
    except Exception as e:
        logger.error(f"Failed to initialize Qdrant collections: {e}")

    yield
    logger.info("Application shutting down")


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_exception_handler(OmniRAGHTTPException, omnirag_exception_handler)
app.add_exception_handler(HTTPException, generic_exception_handler)

# Registered before CORSMiddleware: Starlette wraps middleware in reverse
# registration order, so the middleware added last ends up outermost. CORS
# needs to be outermost so a 429 from RateLimitMiddleware still carries
# Access-Control-Allow-Origin — otherwise the browser reports a CORS error
# and hides the real rate-limit response from the frontend entirely.
app.add_middleware(RateLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api")
app.include_router(webhooks_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(voice_router, prefix="/api")
app.include_router(
    campaigns_router
)  # already carries the full /api/v1/campaigns prefix
app.include_router(chat_router, prefix="", include_in_schema=False)


@app.post("/api/chat/completions")
async def chat_completions_alias(request: ChatRequest):
    """
    Chat completions endpoint (OpenAI-compatible alias).
    """
    from ai.chat_service import ChatService

    logger.info(
        f"Chat request: session={request.session_id}, conversation={request.conversation_id}"
    )

    chat_service = ChatService()
    response = await chat_service.chat(request)
    return response


@app.get("/")
async def index():
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
