"""
Chat API routes.

Provides chat endpoint for RAG-based responses.
"""

import logging

from fastapi import APIRouter

from ai.chat_service import ChatService
from schemas.chat import ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
    """
    Handles a chat request, returning a RAG-based response.
    Stateless version for automation RAG.
    """
    chat_service = ChatService()
    response = await chat_service.chat(request)
    return response
