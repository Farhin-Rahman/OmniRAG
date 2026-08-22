"""
Rate limiting middleware for API protection.

Implements a sliding window rate limiter to protect against abuse.
Industry standard: Similar to what Stripe, GitHub, and Auth0 use.

For production with multiple instances, replace with Redis-based limiter.
"""

import logging
import os
import time
from collections import defaultdict
from threading import Lock
from typing import Callable, Optional

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from services.audit_logger import AuditEventType, audit_log
from utils.auth import extract_token_from_header, verify_token

logger = logging.getLogger(__name__)

# Configuration
DEFAULT_RATE_LIMIT = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))  # requests
DEFAULT_RATE_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))  # seconds


class RateLimiter:
    """
    In-memory sliding window rate limiter.

    For production multi-instance deployments, extend to use Redis:
    - Key: f"ratelimit:{client_id}:{window}"
    - Use INCR with EXPIRE for atomic operations

    Configuration via environment variables:
    - RATE_LIMIT_REQUESTS: Max requests per window (default: 100)
    - RATE_LIMIT_WINDOW: Window size in seconds (default: 60)
    """

    def __init__(
        self, requests: int = DEFAULT_RATE_LIMIT, window: int = DEFAULT_RATE_WINDOW
    ):
        self.requests = requests
        self.window = window
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def _cleanup_old_hits(self, client_id: str, now: float):
        """Remove hits older than the window."""
        cutoff = now - self.window
        self._hits[client_id] = [t for t in self._hits[client_id] if t > cutoff]

    def is_allowed(self, client_id: str) -> tuple[bool, int, int]:
        """
        Check if request is allowed for this client.

        Args:
            client_id: Unique client identifier (IP, user_id, etc.)

        Returns:
            Tuple of (allowed, remaining, reset_in_seconds)
        """
        now = time.time()

        with self._lock:
            self._cleanup_old_hits(client_id, now)

            current_hits = len(self._hits[client_id])
            remaining = max(0, self.requests - current_hits)

            # Calculate reset time
            if self._hits[client_id]:
                oldest_hit = min(self._hits[client_id])
                reset_in = int((oldest_hit + self.window) - now)
            else:
                reset_in = self.window

            if current_hits >= self.requests:
                return False, 0, reset_in

            # Record this hit
            self._hits[client_id].append(now)
            return True, remaining - 1, reset_in

    def get_client_id(self, request: Request) -> str:
        """
        Extract client identifier from request.

        Priority:
        1. Authenticated user ID (from JWT)
        2. X-Forwarded-For header (for proxied requests)
        3. Client IP address
        """
        # Try to get user_id from request state (set by auth middleware)
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            return f"user:{user_id}"

        # Try to extract user_id from the Authorization header
        token = extract_token_from_header(request.headers.get("Authorization"))
        if token:
            payload = verify_token(token, expected_type="access")
            if payload:
                token_user_id = payload.get("user_id")
                if token_user_id:
                    request.state.user_id = token_user_id
                    return f"user:{token_user_id}"

        # Check for forwarded IP (behind proxy/load balancer)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"

        # Fall back to direct client IP
        client_ip = request.client.host if request.client else "unknown"
        return f"ip:{client_ip}"


def _get_request_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for rate limiting.

    Adds headers to responses:
    - X-RateLimit-Limit: Max requests allowed
    - X-RateLimit-Remaining: Requests remaining in window
    - X-RateLimit-Reset: Seconds until window reset

    Returns 429 Too Many Requests when limit exceeded.
    """

    def __init__(
        self,
        app,
        requests: int = DEFAULT_RATE_LIMIT,
        window: int = DEFAULT_RATE_WINDOW,
        exclude_paths: Optional[list[str]] = None,
    ):
        super().__init__(app)
        self.limiter = RateLimiter(requests, window)
        self.exclude_paths = exclude_paths or [
            "/health",
            "/api/health",
            "/api/auth/health",
            "/api/conversations/health",
            "/api/system/health",
            "/docs",
            "/openapi.json",
        ]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip rate limiting for excluded paths
        if any(request.url.path.startswith(path) for path in self.exclude_paths):
            return await call_next(request)

        client_id = self.limiter.get_client_id(request)
        allowed, remaining, reset_in = self.limiter.is_allowed(client_id)

        if not allowed:
            logger.warning(f"Rate limit exceeded for {client_id}")
            audit_log(
                AuditEventType.SECURITY_RATE_LIMIT,
                actor_ip=_get_request_ip(request),
                outcome="failure",
                details={"endpoint": request.url.path, "client_id": client_id},
            )
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Try again in {reset_in} seconds.",
                headers={
                    "X-RateLimit-Limit": str(self.limiter.requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_in),
                    "Retry-After": str(reset_in),
                },
            )

        response = await call_next(request)

        # Add rate limit headers to response
        response.headers["X-RateLimit-Limit"] = str(self.limiter.requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_in)

        return response


# Singleton rate limiter for use outside middleware
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get singleton RateLimiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter
