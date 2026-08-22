"""
Audit logging service for security-relevant operations.

Provides structured logging for security events following industry standards:
- Authentication events (login, logout, failed attempts)
- Authorization events (access denied, ACL violations)
- Data access events (document access, download)
- Administrative actions (user creation, permission changes)

Industry Standard: Similar to SIEM-ready logging used by AWS CloudTrail, Azure Activity Log.
"""

import json
import logging
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("audit")

# Configure audit logger to output JSON for SIEM ingestion
AUDIT_LOG_LEVEL = os.getenv("AUDIT_LOG_LEVEL", "INFO")
AUDIT_LOG_FILE = os.getenv("AUDIT_LOG_FILE", "")  # Empty = stdout only


class AuditEventType(str, Enum):
    """Security event types for audit logging."""

    # Authentication
    AUTH_LOGIN_SUCCESS = "auth.login.success"
    AUTH_LOGIN_FAILED = "auth.login.failed"
    AUTH_LOGOUT = "auth.logout"
    AUTH_TOKEN_REFRESH = "auth.token.refresh"
    AUTH_TOKEN_REVOKED = "auth.token.revoked"
    AUTH_SIGNUP = "auth.signup"

    # Authorization
    AUTHZ_ACCESS_DENIED = "authz.access.denied"
    AUTHZ_ACL_VIOLATION = "authz.acl.violation"
    AUTHZ_TENANT_MISMATCH = "authz.tenant.mismatch"

    # Data Access
    DATA_DOCUMENT_ACCESS = "data.document.access"
    DATA_DOCUMENT_DOWNLOAD = "data.document.download"
    DATA_DOCUMENT_UPLOAD = "data.document.upload"
    DATA_DOCUMENT_DELETE = "data.document.delete"
    DATA_QUERY = "data.query"

    # Administrative
    ADMIN_USER_CREATE = "admin.user.create"
    ADMIN_USER_DELETE = "admin.user.delete"
    ADMIN_ACL_CHANGE = "admin.acl.change"
    ADMIN_CONFIG_CHANGE = "admin.config.change"

    # Security
    SECURITY_RATE_LIMIT = "security.rate_limit"
    SECURITY_INVALID_TOKEN = "security.invalid_token"
    SECURITY_SUSPICIOUS = "security.suspicious"


class AuditLogger:
    """
    Structured audit logger for security events.

    Outputs JSON-formatted log entries suitable for SIEM ingestion.
    Each entry includes:
    - timestamp: ISO 8601 format with timezone
    - event_type: Categorized event type
    - actor: Who performed the action (user_id, ip, etc.)
    - resource: What was accessed/modified
    - outcome: success/failure
    - details: Additional context
    """

    def __init__(self):
        self._logger = logging.getLogger("audit")
        self._setup_handler()

    def _setup_handler(self):
        """Configure audit logger with JSON formatting."""
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
            self._logger.setLevel(
                getattr(logging, AUDIT_LOG_LEVEL.upper(), logging.INFO)
            )

            # Add file handler if configured
            if AUDIT_LOG_FILE:
                file_handler = logging.FileHandler(AUDIT_LOG_FILE)
                file_handler.setFormatter(logging.Formatter("%(message)s"))
                self._logger.addHandler(file_handler)

    def log(
        self,
        event_type: AuditEventType,
        actor_id: Optional[str] = None,
        actor_ip: Optional[str] = None,
        tenant_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        outcome: str = "success",
        details: Optional[dict[str, Any]] = None,
    ):
        """
        Log a security audit event.

        Args:
            event_type: Type of security event
            actor_id: User ID who performed the action
            actor_ip: IP address of the actor
            tenant_id: Tenant context
            resource_type: Type of resource (document, user, etc.)
            resource_id: ID of the resource
            outcome: "success" or "failure"
            details: Additional context as dict
        """
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type.value,
            "actor": {
                "user_id": actor_id,
                "ip": actor_ip,
            },
            "tenant_id": tenant_id,
            "resource": {
                "type": resource_type,
                "id": resource_id,
            },
            "outcome": outcome,
        }

        if details:
            event["details"] = details

        # Log as JSON for SIEM parsing
        self._logger.info(json.dumps(event))

        # Also log to standard logger for debugging
        if outcome == "failure":
            logger.warning(f"AUDIT: {event_type.value} - {outcome} - {details}")

    # Convenience methods for common events

    def log_login_success(self, user_id: str, ip: str, tenant_id: str):
        """Log successful login."""
        self.log(
            AuditEventType.AUTH_LOGIN_SUCCESS,
            actor_id=user_id,
            actor_ip=ip,
            tenant_id=tenant_id,
            outcome="success",
        )

    def log_login_failed(self, email: str, ip: str, reason: str):
        """Log failed login attempt."""
        self.log(
            AuditEventType.AUTH_LOGIN_FAILED,
            actor_ip=ip,
            outcome="failure",
            details={"email": email, "reason": reason},
        )

    def log_logout(self, user_id: str, ip: str, tenant_id: str):
        """Log user logout."""
        self.log(
            AuditEventType.AUTH_LOGOUT,
            actor_id=user_id,
            actor_ip=ip,
            tenant_id=tenant_id,
            outcome="success",
        )

    def log_access_denied(
        self,
        user_id: str,
        ip: str,
        tenant_id: str,
        resource_type: str,
        resource_id: str,
        reason: str,
    ):
        """Log access denied event."""
        self.log(
            AuditEventType.AUTHZ_ACCESS_DENIED,
            actor_id=user_id,
            actor_ip=ip,
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome="failure",
            details={"reason": reason},
        )

    def log_document_access(
        self,
        user_id: str,
        ip: str,
        tenant_id: str,
        doc_id: str,
        action: str = "view",
    ):
        """Log document access event."""
        self.log(
            AuditEventType.DATA_DOCUMENT_ACCESS,
            actor_id=user_id,
            actor_ip=ip,
            tenant_id=tenant_id,
            resource_type="document",
            resource_id=doc_id,
            outcome="success",
            details={"action": action},
        )

    def log_document_download(self, user_id: str, ip: str, tenant_id: str, doc_id: str):
        """Log document download event."""
        self.log(
            AuditEventType.DATA_DOCUMENT_DOWNLOAD,
            actor_id=user_id,
            actor_ip=ip,
            tenant_id=tenant_id,
            resource_type="document",
            resource_id=doc_id,
            outcome="success",
        )

    def log_rate_limit(self, ip: str, endpoint: str):
        """Log rate limit violation."""
        self.log(
            AuditEventType.SECURITY_RATE_LIMIT,
            actor_ip=ip,
            outcome="failure",
            details={"endpoint": endpoint},
        )


# Singleton instance
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get singleton AuditLogger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


# Convenience function
def audit_log(
    event_type: AuditEventType,
    actor_id: Optional[str] = None,
    actor_ip: Optional[str] = None,
    tenant_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    outcome: str = "success",
    details: Optional[dict[str, Any]] = None,
):
    """Convenience function to log an audit event."""
    get_audit_logger().log(
        event_type=event_type,
        actor_id=actor_id,
        actor_ip=actor_ip,
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        details=details,
    )
