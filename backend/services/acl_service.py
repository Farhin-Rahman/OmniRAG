"""
ACL (Access Control List) Service for document access control.

Provides functions to check and manage document access permissions:
- can_user_access_document: Check if user can access a specific document
- get_accessible_doc_filter: Get Qdrant filter for user's accessible documents
- set_document_acl: Set ACL entries for a document
- refresh_doc_acl_payload: Sync ACL to Qdrant payloads

ACL Policy:
- If a document has NO ACL entries -> visible to ALL users in the same tenant
- If a document HAS ACL entries -> only listed users/groups can access
"""

import logging
from typing import List, Optional, Set
from uuid import UUID

from sqlalchemy.orm import Session

from models.base import Document, DocumentACL, GroupMember

logger = logging.getLogger(__name__)


def get_user_group_ids(user_id: UUID, db: Session) -> Set[UUID]:
    """
    Get all group IDs that a user belongs to.

    Args:
        user_id: The user's ID
        db: Database session

    Returns:
        Set of group UUIDs the user is a member of
    """
    memberships = (
        db.query(GroupMember.group_id).filter(GroupMember.user_id == user_id).all()
    )
    return {m[0] for m in memberships}


def can_user_access_document(
    user_id: UUID,
    doc_id: UUID,
    tenant_id: UUID,
    db: Session,
    permission: str = "read",
) -> bool:
    """
    Check if a user can access a specific document.

    ACL Policy:
    1. Document must belong to the same tenant
    2. If document has NO ACL entries -> allowed (public within tenant)
    3. If document HAS ACL entries -> check user/group permissions

    Args:
        user_id: The requesting user's ID
        doc_id: The document ID to check access for
        tenant_id: The user's tenant ID (from JWT)
        db: Database session
        permission: Permission level to check (default: "read")

    Returns:
        True if access is allowed, False otherwise
    """
    # 1. Check document exists and belongs to tenant
    document = (
        db.query(Document)
        .filter(Document.doc_id == doc_id, Document.tenant_id == tenant_id)
        .first()
    )

    if not document:
        logger.debug(f"Document {doc_id} not found in tenant {tenant_id}")
        return False

    # 2. Check if document has any ACL entries
    acl_count = db.query(DocumentACL).filter(DocumentACL.doc_id == doc_id).count()

    if acl_count == 0:
        # No ACL = public within tenant
        logger.debug(f"Document {doc_id} has no ACL, allowing tenant access")
        return True

    # 3. Check user-level ACL
    user_acl = (
        db.query(DocumentACL)
        .filter(
            DocumentACL.doc_id == doc_id,
            DocumentACL.principal_type == "user",
            DocumentACL.principal_id == user_id,
            DocumentACL.permission == permission,
        )
        .first()
    )

    if user_acl:
        logger.debug(
            f"User {user_id} has direct {permission} access to document {doc_id}"
        )
        return True

    # 4. Check group-level ACL
    user_groups = get_user_group_ids(user_id, db)
    if user_groups:
        group_acl = (
            db.query(DocumentACL)
            .filter(
                DocumentACL.doc_id == doc_id,
                DocumentACL.principal_type == "group",
                DocumentACL.principal_id.in_(user_groups),
                DocumentACL.permission == permission,
            )
            .first()
        )

        if group_acl:
            logger.debug(
                f"User {user_id} has {permission} access via group to document {doc_id}"
            )
            return True

    logger.debug(f"User {user_id} denied access to document {doc_id}")
    return False


def get_accessible_doc_ids(
    user_id: UUID,
    tenant_id: UUID,
    db: Session,
    permission: str = "read",
) -> Optional[Set[UUID]]:
    """
    Get all document IDs that a user can access.

    Returns None if the set would be too large (use Qdrant payload filter instead).

    Args:
        user_id: The requesting user's ID
        tenant_id: The user's tenant ID
        db: Database session
        permission: Permission level to check

    Returns:
        Set of accessible doc_ids, or None if using payload filter is recommended
    """
    MAX_DOC_FILTER = 1000  # Beyond this, use Qdrant payload filtering

    # Count total tenant documents
    total_docs = db.query(Document).filter(Document.tenant_id == tenant_id).count()

    if total_docs > MAX_DOC_FILTER:
        # Too many docs - caller should use Qdrant payload filter instead
        logger.info(
            f"Tenant {tenant_id} has {total_docs} docs, "
            "recommending Qdrant payload filter"
        )
        return None

    # Get user's groups
    user_groups = get_user_group_ids(user_id, db)

    # Get docs with explicit user ACL
    user_allowed_docs = set(
        row[0]
        for row in db.query(DocumentACL.doc_id)
        .filter(
            DocumentACL.principal_type == "user",
            DocumentACL.principal_id == user_id,
            DocumentACL.permission == permission,
        )
        .all()
    )

    # Get docs with group ACL for user's groups
    group_allowed_docs = set()
    if user_groups:
        group_allowed_docs = set(
            row[0]
            for row in db.query(DocumentACL.doc_id)
            .filter(
                DocumentACL.principal_type == "group",
                DocumentACL.principal_id.in_(user_groups),
                DocumentACL.permission == permission,
            )
            .all()
        )

    # Get docs with NO ACL (public within tenant)
    docs_with_acl = set(row[0] for row in db.query(DocumentACL.doc_id).distinct().all())

    all_tenant_docs = set(
        row[0]
        for row in db.query(Document.doc_id)
        .filter(Document.tenant_id == tenant_id)
        .all()
    )

    public_docs = all_tenant_docs - docs_with_acl

    # Combine all accessible docs
    accessible = public_docs | user_allowed_docs | group_allowed_docs

    logger.debug(
        f"User {user_id} can access {len(accessible)} docs in tenant {tenant_id}: "
        f"{len(public_docs)} public, {len(user_allowed_docs)} user ACL, "
        f"{len(group_allowed_docs)} group ACL"
    )

    return accessible


def build_qdrant_acl_filter(
    user_id: UUID,
    tenant_id: UUID,
    user_group_ids: List[UUID],
) -> dict:
    """
    Build a Qdrant filter that enforces ACL at query time.

    This is the preferred method for large tenants (>1000 docs).
    Uses payload filtering on acl_users and acl_groups fields.

    Filter logic:
    - tenant_id must match
    - AND (acl_users is empty OR contains user_id OR acl_groups contains any user_group)

    Args:
        user_id: The requesting user's ID
        tenant_id: The user's tenant ID
        user_group_ids: List of group IDs the user belongs to

    Returns:
        Qdrant filter dict for use in search requests
    """
    # Build the ACL condition:
    # (acl_users is empty AND acl_groups is empty) -> public doc
    # OR acl_users contains user_id
    # OR acl_groups contains any of user's groups

    acl_conditions = [
        # Public docs (no ACL)
        {
            "must": [
                {"is_empty": {"key": "acl_users"}},
                {"is_empty": {"key": "acl_groups"}},
            ]
        },
        # User has direct access
        {"must": [{"key": "acl_users", "match": {"any": [str(user_id)]}}]},
    ]

    # Add group access conditions
    if user_group_ids:
        acl_conditions.append(
            {
                "must": [
                    {
                        "key": "acl_groups",
                        "match": {"any": [str(gid) for gid in user_group_ids]},
                    }
                ]
            }
        )

    return {
        "must": [
            # Tenant isolation
            {"key": "tenant_id", "match": {"value": str(tenant_id)}},
        ],
        "should": acl_conditions,  # At least one ACL condition must match
    }


def get_document_acl(doc_id: UUID, db: Session) -> List[dict]:
    """
    Get all ACL entries for a document.

    Args:
        doc_id: Document ID
        db: Database session

    Returns:
        List of ACL entry dicts
    """
    entries = db.query(DocumentACL).filter(DocumentACL.doc_id == doc_id).all()
    return [
        {
            "acl_id": str(entry.acl_id),
            "principal_type": entry.principal_type,
            "principal_id": str(entry.principal_id),
            "permission": entry.permission,
            "granted_by": str(entry.granted_by) if entry.granted_by else None,
            "granted_at": entry.granted_at.isoformat() if entry.granted_at else None,
        }
        for entry in entries
    ]


def set_document_acl(
    doc_id: UUID,
    principals: List[dict],
    granted_by: UUID,
    db: Session,
    replace: bool = True,
) -> List[DocumentACL]:
    """
    Set ACL entries for a document.

    Args:
        doc_id: Document ID to set ACL for
        principals: List of dicts with keys: type ('user'|'group'), id (UUID), permission
        granted_by: User ID who is granting access
        db: Database session
        replace: If True, remove existing ACL entries first

    Returns:
        List of created DocumentACL entries

    Example:
        set_document_acl(doc_id, [
            {"type": "user", "id": user_uuid, "permission": "read"},
            {"type": "group", "id": group_uuid, "permission": "read"},
        ], admin_user_id, db)
    """
    if replace:
        # Remove existing ACL entries
        db.query(DocumentACL).filter(DocumentACL.doc_id == doc_id).delete()

    created = []
    for principal in principals:
        acl_entry = DocumentACL(
            doc_id=doc_id,
            principal_type=principal["type"],
            principal_id=UUID(str(principal["id"])),
            permission=principal.get("permission", "read"),
            granted_by=granted_by,
        )
        db.add(acl_entry)
        created.append(acl_entry)

    db.flush()

    logger.info(
        f"Set ACL for document {doc_id}: {len(created)} entries by user {granted_by}"
    )

    return created


def clear_document_acl(doc_id: UUID, db: Session) -> int:
    """
    Remove all ACL entries for a document (makes it public within tenant).

    Args:
        doc_id: Document ID
        db: Database session

    Returns:
        Number of ACL entries removed
    """
    count = db.query(DocumentACL).filter(DocumentACL.doc_id == doc_id).delete()
    logger.info(f"Cleared {count} ACL entries for document {doc_id}")
    return count


def get_doc_acl_for_qdrant(doc_id: UUID, db: Session) -> tuple[List[str], List[str]]:
    """
    Get ACL user and group IDs for Qdrant payload sync.

    Args:
        doc_id: Document ID
        db: Database session

    Returns:
        Tuple of (acl_users, acl_groups) as string lists
    """
    entries = (
        db.query(DocumentACL)
        .filter(
            DocumentACL.doc_id == doc_id,
            DocumentACL.permission == "read",  # Only sync read permissions to Qdrant
        )
        .all()
    )

    acl_users = []
    acl_groups = []

    for entry in entries:
        if entry.principal_type == "user":
            acl_users.append(str(entry.principal_id))
        elif entry.principal_type == "group":
            acl_groups.append(str(entry.principal_id))

    return acl_users, acl_groups


def refresh_doc_acl_payload(doc_id: UUID, db: Session) -> dict:
    """
    Sync ACL entries from database to Qdrant payload for a document.

    This function should be called after:
    - Setting document ACL (POST /admin/documents/{id}/acl)
    - Clearing document ACL (DELETE /admin/documents/{id}/acl)

    Args:
        doc_id: Document ID to refresh ACL for
        db: Database session

    Returns:
        Dict with refresh status
    """
    # Get current ACL from database
    acl_users, acl_groups = get_doc_acl_for_qdrant(doc_id, db)

    # Get Qdrant service and update all points for this doc
    try:
        from services.db.qdrant_service import get_qdrant_service

        qdrant = get_qdrant_service()

        # Update payload for all points with this doc_id
        # Note: Qdrant set_payload requires point selector
        # We'll search for points by doc_id and update them
        points_updated = qdrant.update_acl_payload(
            doc_id=str(doc_id),
            acl_users=acl_users,
            acl_groups=acl_groups,
        )

        logger.info(
            f"Refreshed ACL payload for doc {doc_id}: "
            f"{len(acl_users)} users, {len(acl_groups)} groups, "
            f"{points_updated} points updated"
        )

        return {
            "doc_id": str(doc_id),
            "acl_users": acl_users,
            "acl_groups": acl_groups,
            "points_updated": points_updated,
            "success": True,
        }

    except Exception as e:
        logger.error(f"Failed to refresh ACL payload for doc {doc_id}: {e}")
        return {
            "doc_id": str(doc_id),
            "success": False,
            "error": str(e),
        }
