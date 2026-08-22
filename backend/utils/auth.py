"""
Enterprise-grade authentication utilities.

Provides secure password hashing, JWT token generation/validation,
and session management following industry best practices.

Security Standards:
- Password hashing: bcrypt with 12 rounds (OWASP recommended)
- JWT: HS256 with configurable expiration
- Token validation: Strict expiry and signature checks
- Secrets: Environment-based, never hardcoded
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import jwt
from fastapi import HTTPException, status
from passlib.context import CryptContext

logger = logging.getLogger(__name__)

# Password hashing context (bcrypt with 12 rounds - OWASP recommended)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

# JWT Configuration (load from environment for security)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
)  # 1 hour
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))  # 7 days


def _get_jwt_secret_key() -> str:
    """Load JWT secret from environment (required)."""
    secret = os.getenv("JWT_SECRET_KEY", "")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY is not configured")
    return secret


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt.

    Uses 12 rounds of bcrypt hashing as recommended by OWASP.
    This provides strong protection against brute-force attacks.

    Note: bcrypt has a maximum password length of 72 bytes.
    Passwords longer than this are automatically truncated.

    Args:
        password: Plain text password to hash

    Returns:
        Hashed password string (bcrypt format)

    Example:
        >>> hash_password("my_secure_password")
        '$2b$12$...'
    """
    # bcrypt has a 72-byte limit, truncate if necessary
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        password = password_bytes[:72].decode("utf-8", errors="ignore")

    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against a hash.

    Uses constant-time comparison to prevent timing attacks.

    Note: Applies same 72-byte truncation as hash_password for consistency.

    Args:
        plain_password: Plain text password from user
        hashed_password: Hashed password from database

    Returns:
        True if password matches, False otherwise

    Example:
        >>> verify_password("my_password", hashed)
        True
    """
    # Apply same truncation as hash_password
    password_bytes = plain_password.encode("utf-8")
    if len(password_bytes) > 72:
        plain_password = password_bytes[:72].decode("utf-8", errors="ignore")

    return pwd_context.verify(plain_password, hashed_password)


def normalize_role(role: Optional[str]) -> str:
    """Normalize role values to the expected RBAC set."""
    if not role:
        return "member"
    role_value = role.strip().lower()
    if role_value == "user":
        return "member"
    return role_value


def create_access_token(
    user_id: UUID,
    email: str,
    role: str = "member",
    tenant_id: Optional[UUID] = None,
    additional_claims: Optional[dict] = None,
) -> tuple[str, int]:
    """
    Create a JWT access token.

    Token contains user identification, role, tenant, and expiration. Used for API authentication.
    Short-lived for security (default 1 hour).

    Args:
        user_id: User's unique identifier
        email: User's email address
        role: User's role (default: "member")
        tenant_id: User's tenant ID (required for multi-tenant access control)
        additional_claims: Optional extra claims to include

    Returns:
        Tuple of (token_string, expiration_timestamp)

    Example:
        >>> token, exp = create_access_token(user_id, "user@example.com", "admin", tenant_id)
        >>> token
        'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    payload = {
        "user_id": str(user_id),
        "email": email,
        "role": normalize_role(role),  # Include role in token for RBAC
        "type": "access",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "sub": str(user_id),  # Standard JWT claim
    }

    # Add tenant_id claim for multi-tenancy (tid = tenant ID)
    if tenant_id:
        payload["tid"] = str(tenant_id)

    # Add any additional claims
    if additional_claims:
        payload.update(additional_claims)

    token = jwt.encode(payload, _get_jwt_secret_key(), algorithm=ALGORITHM)
    return token, int(expire.timestamp())


def create_refresh_token(user_id: UUID) -> tuple[str, int]:
    """
    Create a JWT refresh token.

    Long-lived token used to obtain new access tokens without re-authentication.
    Default 7 days expiration.

    Args:
        user_id: User's unique identifier

    Returns:
        Tuple of (token_string, expiration_timestamp)

    Example:
        >>> token, exp = create_refresh_token(user_id)
    """
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    payload = {
        "user_id": str(user_id),
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "sub": str(user_id),
    }

    token = jwt.encode(payload, _get_jwt_secret_key(), algorithm=ALGORITHM)
    return token, int(expire.timestamp())


def verify_token(token: str, expected_type: str = "access") -> Optional[dict]:
    """
    Verify and decode a JWT token.

    Validates signature, expiration, and token type.
    Returns None if token is invalid or expired.

    Args:
        token: JWT token string
        expected_type: Expected token type ('access' or 'refresh')

    Returns:
        Decoded token payload if valid, None otherwise

    Example:
        >>> payload = verify_token(token)
        >>> payload['user_id']
        '550e8400-e29b-41d4-a716-446655440000'
    """
    try:
        payload = jwt.decode(token, _get_jwt_secret_key(), algorithms=[ALGORITHM])

        # Verify token type
        if payload.get("type") != expected_type:
            return None

        return payload

    except jwt.ExpiredSignatureError:
        # Token has expired
        return None
    except jwt.InvalidTokenError:
        # Invalid token (bad signature, malformed, etc.)
        return None
    except Exception:
        # Any other error
        return None


def decode_token_unsafe(token: str) -> Optional[dict]:
    """
    Decode token without verification (for debugging only).

    WARNING: DO NOT USE FOR AUTHENTICATION!
    Only for inspecting token contents during development.

    Args:
        token: JWT token string

    Returns:
        Decoded payload without verification

    Example:
        >>> payload = decode_token_unsafe(token)  # For debugging only
    """
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except Exception:
        return None


def extract_token_from_header(authorization: Optional[str]) -> Optional[str]:
    """
    Extract JWT token from Authorization header.

    Expects format: "Bearer <token>"

    Args:
        authorization: Authorization header value

    Returns:
        Token string if present, None otherwise

    Example:
        >>> extract_token_from_header("Bearer eyJhbGc...")
        'eyJhbGc...'
    """
    if not authorization:
        return None

    if not authorization.startswith("Bearer "):
        return None

    return authorization.replace("Bearer ", "").strip()


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate password strength.

    Requirements (OWASP standards):
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one number
    - At least one special character

    Args:
        password: Password to validate

    Returns:
        Tuple of (is_valid, error_message)

    Example:
        >>> validate_password_strength("weak")
        (False, "Password must be at least 8 characters")
        >>> validate_password_strength("StrongP@ss123")
        (True, "")
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters"

    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"

    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"

    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one number"

    if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
        return False, "Password must contain at least one special character"

    return True, ""


def create_unauthorized_exception(
    detail: str = "Could not validate credentials",
) -> HTTPException:
    """
    Create a standardized unauthorized HTTP exception.

    Args:
        detail: Error message detail

    Returns:
        HTTPException with 401 status

    Example:
        >>> raise create_unauthorized_exception("Invalid token")
    """
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def create_token_pair(
    user_id: UUID, email: str, role: str = "member", tenant_id: Optional[UUID] = None
) -> dict:
    """
    Create both access and refresh tokens.

    Convenience method for login/signup flows.

    Args:
        user_id: User's unique identifier
        email: User's email address
        role: User's role (default: "member")
        tenant_id: User's tenant ID for multi-tenancy

    Returns:
        Dict with tokens and expiration info

    Example:
        >>> tokens = create_token_pair(user_id, "user@example.com", "member", tenant_id)
        >>> tokens['access_token']
        'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'
    """
    access_token, access_exp = create_access_token(user_id, email, role, tenant_id)
    refresh_token, refresh_exp = create_refresh_token(user_id)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "access_token_expires_at": access_exp,
        "refresh_token_expires_at": refresh_exp,
        "token_type": "bearer",
    }
