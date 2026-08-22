"""
Unified error handling for OmniRAG API.

All errors use HTTPException. A global exception handler formats them
into RFC 9457 Problem JSON responses for consistency.
"""

import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class OmniRAGHTTPException(HTTPException):
    """
    Base exception for OmniRAG API errors.

    Extends HTTPException with additional fields for RFC 9457 Problem JSON.
    """

    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str,
        problem_type: str = "https://api.omnirag.local/problems/error",
        headers: Optional[Dict[str, str]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code
        self.problem_type = problem_type
        self.extra = extra or {}


class UnauthorizedError(OmniRAGHTTPException):
    """Raised when authentication fails."""

    def __init__(self, detail: str = "Invalid or missing bearer token"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            code="UNAUTHORIZED",
            problem_type="https://api.omnirag.local/problems/unauthorized",
        )


class ForbiddenError(OmniRAGHTTPException):
    """Raised when user lacks permission."""

    def __init__(self, detail: str = "Access denied"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            code="FORBIDDEN",
            problem_type="https://api.omnirag.local/problems/forbidden",
        )


class NotFoundError(OmniRAGHTTPException):
    """Raised when a resource is not found."""

    def __init__(
        self,
        resource: str,
        resource_id: str,
        detail: Optional[str] = None,
    ):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail or f"{resource} with id '{resource_id}' not found",
            code="NOT_FOUND",
            problem_type="https://api.omnirag.local/problems/not-found",
            extra={"resource": resource, "id": resource_id},
        )


class InvalidDownloadTokenError(OmniRAGHTTPException):
    """Raised when download token is invalid or expired."""

    def __init__(self, detail: str = "Invalid or expired download token"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            code="INVALID_DOWNLOAD_TOKEN",
            problem_type="https://api.omnirag.local/problems/invalid-download-token",
        )


class SyncInProgressError(OmniRAGHTTPException):
    """Raised when a sync is already in progress for the tenant."""

    def __init__(self, detail: str = "Sync already in progress for this tenant"):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
            code="SYNC_IN_PROGRESS",
            problem_type="https://api.omnirag.local/problems/sync-in-progress",
        )


def create_problem_json(
    status_code: int,
    title: str,
    code: str,
    problem_type: str,
    trace_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create RFC 9457 Problem JSON body.
    """
    if trace_id is None:
        trace_id = str(uuid.uuid4())

    problem = {
        "type": problem_type,
        "title": title,
        "status": status_code,
        "code": code,
        "trace_id": trace_id,
    }

    if extra:
        problem["details"] = extra

    return problem


async def omnirag_exception_handler(
    request: Request, exc: OmniRAGHTTPException
) -> JSONResponse:
    """
    Global exception handler for OmniRAGHTTPException.

    Converts exceptions to RFC 9457 Problem JSON responses.
    """
    trace_id = str(uuid.uuid4())

    logger.warning(
        f"API error: code={exc.code} status={exc.status_code} detail={exc.detail} "
        f"trace_id={trace_id} path={request.url.path}"
    )

    problem = create_problem_json(
        status_code=exc.status_code,
        title=exc.detail,
        code=exc.code,
        problem_type=exc.problem_type,
        trace_id=trace_id,
        extra=exc.extra if exc.extra else None,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=problem,
        media_type="application/problem+json",
        headers=exc.headers,
    )


async def generic_exception_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    """
    Handler for standard HTTPException (not OmniRAGHTTPException).

    Wraps them in Problem JSON format for consistency.
    """
    trace_id = str(uuid.uuid4())

    logger.warning(
        f"HTTP error: status={exc.status_code} detail={exc.detail} "
        f"trace_id={trace_id} path={request.url.path}"
    )

    problem = create_problem_json(
        status_code=exc.status_code,
        title=str(exc.detail) if exc.detail else "Error",
        code="HTTP_ERROR",
        problem_type="https://api.omnirag.local/problems/http-error",
        trace_id=trace_id,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=problem,
        media_type="application/problem+json",
        headers=exc.headers,
    )


def not_found_error(resource: str, resource_id: str) -> NotFoundError:
    """Return a NotFoundError exception instance (to be raised)."""
    return NotFoundError(resource, resource_id)
