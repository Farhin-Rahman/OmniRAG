"""
Secure download token generation and validation.

Implements HMAC-signed tokens for URL-based document downloads, enabling
browser-clickable download links without requiring custom headers.

Token format: base64(payload).base64(signature)
Payload: JSON with doc_id, tenant_id, exp, purpose
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)


def _get_secret() -> bytes:
    """Get the download URL secret from environment."""
    secret = os.getenv("DOWNLOAD_URL_SECRET", "")
    if not secret:
        raise RuntimeError("DOWNLOAD_URL_SECRET is not configured")
    return secret.encode("utf-8")


def _constant_time_compare(a: bytes, b: bytes) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    return hmac.compare_digest(a, b)


def generate_download_token(
    doc_id: UUID,
    tenant_id: UUID,
    expiry_minutes: int = 5,
    purpose: str = "download",
    user_id: Optional[UUID] = None,
) -> str:
    """
    Generate a signed download token for a document.

    Args:
        doc_id: The document UUID.
        tenant_id: The tenant UUID (owner).
        expiry_minutes: Token validity in minutes (default: 5).
        purpose: Token purpose claim (default: "download").
        user_id: Optional user UUID for audit trail.

    Returns:
        str: Base64-encoded signed token.
    """
    secret = _get_secret()

    # Calculate expiry timestamp
    exp = int(time.time()) + (expiry_minutes * 60)

    # Create payload
    payload = {
        "doc_id": str(doc_id),
        "tenant_id": str(tenant_id),
        "exp": exp,
        "purpose": purpose,
    }

    # Add user_id if provided (for audit trail)
    if user_id:
        payload["user_id"] = str(user_id)

    # Encode payload
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("utf-8")

    # Create HMAC signature
    signature = hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).digest()
    signature_b64 = base64.urlsafe_b64encode(signature).decode("utf-8")

    # Combine: payload.signature
    token = f"{payload_b64}.{signature_b64}"

    logger.debug(
        f"Generated download token for doc_id={doc_id} tenant_id={tenant_id} user_id={user_id} exp={exp}"
    )

    return token


def validate_download_token(
    token: str,
    expected_doc_id: UUID,
    expected_purpose: str = "download",
) -> Optional[dict]:
    """
    Validate a download token and return its claims if valid.

    Performs:
    1. Signature verification (constant-time)
    2. Expiry check
    3. doc_id match verification
    4. Purpose claim verification

    Args:
        token: The token string to validate.
        expected_doc_id: The doc_id the token must be bound to.
        expected_purpose: The purpose claim to verify (default: "download").

    Returns:
        Optional[dict]: Claims dict with tenant_id and optional user_id if valid.
    """
    try:
        secret = _get_secret()

        # Split token
        parts = token.split(".")
        if len(parts) != 2:
            logger.warning("Invalid token format: wrong number of parts")
            return None

        payload_b64, signature_b64 = parts

        # Verify signature first (constant-time)
        expected_signature = hmac.new(
            secret, payload_b64.encode("utf-8"), hashlib.sha256
        ).digest()

        try:
            actual_signature = base64.urlsafe_b64decode(signature_b64)
        except Exception:
            logger.warning("Invalid token: malformed signature")
            return None

        if not _constant_time_compare(expected_signature, actual_signature):
            logger.warning("Invalid token: signature mismatch")
            return None

        # Decode and parse payload
        try:
            payload_json = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
            payload = json.loads(payload_json)
        except Exception:
            logger.warning("Invalid token: malformed payload")
            return None

        # Check expiry
        exp = payload.get("exp", 0)
        if time.time() > exp:
            logger.warning("Invalid token: expired")
            return None

        # Verify doc_id
        token_doc_id = payload.get("doc_id")
        if token_doc_id != str(expected_doc_id):
            logger.warning(
                f"Invalid token: doc_id mismatch (expected {expected_doc_id}, got {token_doc_id})"
            )
            return None

        # Verify purpose
        token_purpose = payload.get("purpose")
        if token_purpose != expected_purpose:
            logger.warning(
                f"Invalid token: purpose mismatch (expected {expected_purpose}, got {token_purpose})"
            )
            return None

        # Return tenant_id
        tenant_id = payload.get("tenant_id")
        if not tenant_id:
            logger.warning("Invalid token: missing tenant_id")
            return None
        user_id = payload.get("user_id")
        return {
            "tenant_id": UUID(tenant_id),
            "user_id": UUID(user_id) if user_id else None,
        }

    except Exception as e:
        logger.exception(f"Token validation error: {e}")
        return None


def get_token_info(token: str) -> Optional[dict]:
    """
    Decode token payload without verification (for debugging/logging).

    WARNING: This does NOT validate the token. Use validate_download_token() for validation.

    Returns:
        Optional[dict]: The decoded payload or None if malformed.
    """
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None

        payload_b64 = parts[0]
        payload_json = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
        return json.loads(payload_json)
    except Exception:
        return None
