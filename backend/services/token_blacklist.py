"""
Token blacklist service for JWT revocation.

Provides a simple in-memory token blacklist with automatic expiry cleanup.
For production with multiple instances, replace with Redis.

Industry Standard: Auth0, Okta use similar token revocation patterns.
"""

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional, Set

logger = logging.getLogger(__name__)

# Configuration
BLACKLIST_CLEANUP_INTERVAL = int(
    os.getenv("BLACKLIST_CLEANUP_INTERVAL", "300")
)  # 5 min


class TokenBlacklist:
    """
    In-memory token blacklist with automatic cleanup.

    For production multi-instance deployments, extend this to use Redis:
    - Key: f"revoked:{token_hash}"
    - TTL: token's remaining expiry time

    This implementation is suitable for:
    - Single-instance deployments
    - Development/testing
    - Low-to-medium traffic applications
    """

    def __init__(self):
        self._blacklist: Set[str] = set()
        self._expiry_times: dict[str, float] = {}
        self._lock = threading.Lock()
        self._cleanup_thread: Optional[threading.Thread] = None
        self._running = False

    def start_cleanup_worker(self):
        """Start background cleanup thread."""
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            return

        self._running = True
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()
        logger.info("Token blacklist cleanup worker started")

    def stop_cleanup_worker(self):
        """Stop background cleanup thread."""
        self._running = False
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)
        logger.info("Token blacklist cleanup worker stopped")

    def _cleanup_loop(self):
        """Background loop to remove expired tokens."""
        while self._running:
            time.sleep(BLACKLIST_CLEANUP_INTERVAL)
            self._cleanup_expired()

    def _cleanup_expired(self):
        """Remove tokens that have naturally expired."""
        now = datetime.now(timezone.utc).timestamp()
        with self._lock:
            expired = [token for token, exp in self._expiry_times.items() if exp < now]
            for token in expired:
                self._blacklist.discard(token)
                del self._expiry_times[token]

            if expired:
                logger.debug(f"Cleaned up {len(expired)} expired tokens from blacklist")

    def revoke(self, token: str, expires_at: float):
        """
        Add a token to the blacklist.

        Args:
            token: The JWT token string (or its hash)
            expires_at: Unix timestamp when token naturally expires
        """
        with self._lock:
            self._blacklist.add(token)
            self._expiry_times[token] = expires_at
        logger.debug(f"Token revoked, expires at {expires_at}")

    def is_revoked(self, token: str) -> bool:
        """
        Check if a token is revoked.

        Args:
            token: The JWT token string (or its hash)

        Returns:
            True if token is revoked, False otherwise
        """
        with self._lock:
            return token in self._blacklist

    def clear(self):
        """Clear all revoked tokens (for testing)."""
        with self._lock:
            self._blacklist.clear()
            self._expiry_times.clear()
        logger.debug("Token blacklist cleared")

    @property
    def count(self) -> int:
        """Number of tokens in blacklist."""
        with self._lock:
            return len(self._blacklist)


# Singleton instance
_token_blacklist: Optional[TokenBlacklist] = None


def get_token_blacklist() -> TokenBlacklist:
    """Get singleton TokenBlacklist instance."""
    global _token_blacklist
    if _token_blacklist is None:
        _token_blacklist = TokenBlacklist()
        _token_blacklist.start_cleanup_worker()
    return _token_blacklist


def revoke_token(token: str, expires_at: float):
    """Convenience function to revoke a token."""
    get_token_blacklist().revoke(token, expires_at)


def is_token_revoked(token: str) -> bool:
    """Convenience function to check if token is revoked."""
    return get_token_blacklist().is_revoked(token)
