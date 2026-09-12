"""
Firebase Auth dependencies for FastAPI routes.

Verifies Firebase ID tokens (firebase_admin.auth.verify_id_token) and
exposes the decoded principal as AuthenticatedUser, plus a require_roles
dependency factory for role-gated endpoints (roles come from Firebase custom
claims — see set_admin.py).

Note: this is a separate, new auth path alongside the existing JWT-based
system in routes/auth.py (which the document/chat/ACL routes already use).
That system is untouched here — this module is for routes that should
authenticate via Firebase instead.
"""

import logging
import os
from typing import List, Optional

import firebase_admin
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials

from config.settings import settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)
_firebase_app: Optional[firebase_admin.App] = None


def _get_firebase_app() -> firebase_admin.App:
    """Lazily initialize the Firebase Admin app on first use, rather than at
    import time — so the app can still start (and non-Firebase routes still
    work) even if the service account file isn't present in this environment."""
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app

    if firebase_admin._apps:
        _firebase_app = firebase_admin.get_app()
        return _firebase_app

    path = settings.firebase_service_account_path
    if not os.path.exists(path):
        raise RuntimeError(
            f"Firebase service account not found at '{path}'. Set "
            "FIREBASE_SERVICE_ACCOUNT_PATH or place gcp-service-account.json "
            "in the backend root."
        )

    cred = credentials.Certificate(path)
    _firebase_app = firebase_admin.initialize_app(cred)
    return _firebase_app


class AuthenticatedUser:
    """Authenticated principal decoded from a verified Firebase ID token."""

    def __init__(self, uid: str, email: Optional[str], roles: List[str], claims: dict):
        self.uid = uid
        self.email = email
        self.roles = roles
        self.claims = claims

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def __repr__(self) -> str:
        return f"AuthenticatedUser(uid={self.uid!r}, email={self.email!r}, roles={self.roles!r})"


async def get_current_firebase_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> AuthenticatedUser:
    """Verify the Firebase ID token from the Authorization header and return
    the decoded user. Raises 401 if missing, invalid, or expired."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        _get_firebase_app()
        decoded = firebase_auth.verify_id_token(credentials.credentials)
    except RuntimeError:
        raise
    except Exception as e:
        logger.warning(f"Firebase token verification failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Roles are mapped directly from the decoded token's custom claims,
    # set via auth.set_custom_user_claims(uid, {"roles": [...]}) — see
    # backend/set_admin.py.
    roles = decoded.get("roles", [])
    if isinstance(roles, str):
        roles = [roles]

    return AuthenticatedUser(
        uid=decoded["uid"],
        email=decoded.get("email"),
        roles=roles,
        claims=decoded,
    )


def require_roles(*allowed_roles: str):
    """
    Dependency factory — require the authenticated user to have at least
    one of the given roles.

    Usage:
        @router.get("/admin/reports")
        async def list_reports(
            user: AuthenticatedUser = Depends(require_roles("TrustAndSafetyAdmin")),
        ):
            ...
    """

    async def _check(
        user: AuthenticatedUser = Depends(get_current_firebase_user),
    ) -> AuthenticatedUser:
        if not any(user.has_role(r) for r in allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(allowed_roles)}",
            )
        return user

    return _check
