"""
Request context for multi-tenant authorization.

Provides a unified RequestContext dependency that extracts:
- Authenticated user
- Tenant ID (from JWT claims, not headers)
- User role

This is the single source of truth for who is making the request.
"""

import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from fastapi import Depends, Header, HTTPException

from models.base import User
from routes.auth import get_current_user, get_current_user_optional
from utils.auth import extract_token_from_header, normalize_role, verify_token

logger = logging.getLogger(__name__)


@dataclass
class RequestContext:
    """
    Unified request context for authorization.

    Contains all the information needed to make authorization decisions:
    - user: The authenticated User object
    - tenant_id: The tenant ID from JWT claims (source of truth)
    - role: The user's role (admin/member/viewer)
    """

    user: User
    tenant_id: UUID
    role: str

    @property
    def user_id(self) -> UUID:
        return self.user.user_id

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_viewer(self) -> bool:
        return self.role == "viewer"

    def can_write(self) -> bool:
        """Check if user can perform write operations (admin or member)."""
        return self.role in ("admin", "member")

    def can_manage(self) -> bool:
        """Check if user can manage ACL, groups, etc. (admin only)."""
        return self.role == "admin"


def _build_request_context(
    token: str,
    user: User,
) -> RequestContext:
    payload = verify_token(token, expected_type="access")
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Get tenant_id from JWT claims (tid)
    jwt_tenant_id = payload.get("tid")
    jwt_role = normalize_role(payload.get("role", "member"))

    # Validate tenant_id exists in JWT
    if not jwt_tenant_id:
        # For backward compatibility during migration, fall back to user.tenant_id
        if user.tenant_id:
            jwt_tenant_id = str(user.tenant_id)
            logger.warning(
                f"User {user.user_id} token missing 'tid' claim, falling back to user.tenant_id"
            )
        else:
            raise HTTPException(
                status_code=401,
                detail="Token missing tenant claim. Please sign in again.",
            )

    tenant_uuid = UUID(jwt_tenant_id)

    # Verify JWT tenant matches user's tenant (defense in depth)
    if user.tenant_id and user.tenant_id != tenant_uuid:
        logger.error(
            f"SECURITY: User {user.user_id} JWT tenant {jwt_tenant_id} != "
            f"user.tenant_id {user.tenant_id}"
        )
        raise HTTPException(
            status_code=403, detail="Token tenant mismatch. Please sign in again."
        )

    return RequestContext(
        user=user,
        tenant_id=tenant_uuid,
        role=jwt_role,
    )


async def get_request_context(
    authorization: Optional[str] = Header(None),
    user: User = Depends(get_current_user),
) -> RequestContext:
    """
    Dependency to get the unified request context.

    Extracts tenant_id from JWT claims (not from headers).
    This ensures tenant context is cryptographically bound to the user.

    Args:
        authorization: Authorization header (for extracting JWT claims)
        user: Authenticated user from get_current_user dependency
    Returns:
        RequestContext with user, tenant_id, and role

    Raises:
        HTTPException: 401 if JWT is invalid or missing tenant
        HTTPException: 403 if user's tenant doesn't match JWT tenant
    """
    # Extract tenant_id from JWT claims
    token = extract_token_from_header(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing authorization token")

    return _build_request_context(token, user)


async def get_request_context_optional(
    authorization: Optional[str] = Header(None),
    user: Optional[User] = Depends(get_current_user_optional),
) -> Optional[RequestContext]:
    """
    Dependency to get request context if Authorization header is present.

    Returns None if the Authorization header is missing or invalid.
    """
    if not authorization:
        return None

    token = extract_token_from_header(authorization)
    if not token or not user:
        return None

    try:
        return _build_request_context(token, user)
    except HTTPException:
        return None


def require_admin(ctx: RequestContext = Depends(get_request_context)) -> RequestContext:
    """
    Dependency that requires admin role.

    Use on admin-only endpoints like group management, ACL management.

    Raises:
        HTTPException: 403 if user is not an admin
    """
    if not ctx.is_admin:
        raise HTTPException(
            status_code=403, detail="Admin role required for this operation"
        )
    return ctx


def require_write_access(
    ctx: RequestContext = Depends(get_request_context),
) -> RequestContext:
    """
    Dependency that requires write access (admin or member).

    Use on endpoints that modify data like ingest, delete, etc.

    Raises:
        HTTPException: 403 if user is viewer
    """
    if not ctx.can_write():
        raise HTTPException(
            status_code=403, detail="Write access required (admin or member role)"
        )
    return ctx
