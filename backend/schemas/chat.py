"""
Chat-related request/response models.

Shared schemas to avoid circular imports between routes and services.
"""

from typing import Optional
from pydantic import BaseModel


class ChatRequest(BaseModel):
    """Request model for chat interaction."""

    message: str
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    user_preferences: Optional[dict] = None
    enable_pev: Optional[bool] = None
    max_reasoning_steps: Optional[int] = 5
