"""
Centralized authorization service for ACL/RBAC.

This module provides ACL-based authorization that checks:
1. Tenant isolation (document must belong to user's tenant)
2. ACL entries (if document has ACL, user must be in the list)
3. Group memberships (indirect access via groups)

Usage:
    from services.authorization import authorize

    if not authorize(user, "read", document, db, tenant_id):
        raise HTTPException(403, "Access denied")
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models.base import User

logger = logging.getLogger(__name__)


def authorize(
    user: User,
    action: str,
    resource: any,
    db: Optional[Session] = None,
    tenant_id: Optional[UUID] = None,
) -> bool:
    """
    Centralized authorization check with full ACL enforcement.

    Args:
        user: Current authenticated user
        action: Action being performed ('read', 'write', 'delete', 'admin')
        resource: Resource being accessed (Document, Conversation, etc.)
        db: Database session for ACL lookups (required for Document)
        tenant_id: User's tenant ID from JWT (required for Document)

    Returns:
        True if authorized, False otherwise
    """
    # Import here to avoid circular imports
    from services.acl_service import can_user_access_document

    # Handle Document resources (duck-typed for testability)
    # Check for doc_id and tenant_id attributes instead of isinstance
    if hasattr(resource, "doc_id") and hasattr(resource, "tenant_id"):
        # Tenant isolation check
        if tenant_id and resource.tenant_id != tenant_id:
            logger.warning(
                f"TENANT VIOLATION: User {user.user_id} (tenant {tenant_id}) "
                f"tried to access document {resource.doc_id} (tenant {resource.tenant_id})"
            )
            return False

        # ACL check
        if db and tenant_id:
            return can_user_access_document(
                user_id=user.user_id,
                doc_id=resource.doc_id,
                tenant_id=tenant_id,
                db=db,
                permission=action,
            )
        else:
            # No DB session - fall back to tenant-only check
            logger.warning(
                f"Authorization for document {resource.doc_id} without DB session"
            )
            return tenant_id is None or resource.tenant_id == tenant_id

    # For other resources, allow (add more resource types as needed)
    logger.debug(
        f"Authorization check: user={user.user_id} action={action} "
        f"resource={type(resource).__name__} - ALLOWED (non-document resource)"
    )
    return True


def require_authorization(
    user: User,
    action: str,
    resource: any,
    db: Optional[Session] = None,
    tenant_id: Optional[UUID] = None,
):
    """
    Dependency/helper that raises HTTPException if not authorized.

    Usage in FastAPI routes:
        @router.get("/documents/{doc_id}")
        async def get_document(
            doc_id: UUID,
            ctx: RequestContext = Depends(get_request_context),
            db: Session = Depends(get_db),
        ):
            document = get_document_by_id(doc_id)
            require_authorization(ctx.user, "read", document, db, ctx.tenant_id)
            return document
    """
    if not authorize(user, action, resource, db, tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {action} on {type(resource).__name__}",
        )
