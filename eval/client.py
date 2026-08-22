"""
HTTP Client for OmniRAG API.

This module provides a synchronous HTTP client for interacting with the
OmniRAG RAG backend during evaluation runs.

The client handles:
- Chat completions via POST /api/chat/completions
- Trace retrieval via GET /traces/{trace_id}
- Authorization header injection (Bearer JWT)
- Response parsing and validation

Example:
    from eval.client import OmniRAGClient
    
    client = OmniRAGClient("http://localhost:8081", access_token="your-jwt")
    response = client.chat("What is the user policy?")
    print(response.answer)
    print(f"Retrieved {len(response.sources)} sources")
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class Source:
    """
    A source document/chunk returned from RAG retrieval.
    
    Attributes:
        chunk_id: Unique identifier for the chunk.
        doc_id: Unique identifier for the parent document.
        doc_name: Human-readable document name.
        text: Text content of the chunk (truncated to 500 chars by backend).
        page: Page number in the original document.
        score: Relevance/similarity score from vector search.
        metadata: Additional metadata from the chunk.
        raw: Original raw dict from API response.
    """
    chunk_id: str
    doc_id: str
    doc_name: str
    text: str
    page: int
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "Source":
        """Create a Source from the API response format."""
        metadata = data.get("metadata", {})
        return cls(
            chunk_id=str(data.get("chunk_id", "")),
            doc_id=str(data.get("doc_id", "")),
            doc_name=metadata.get("doc_name", "Unknown"),
            text=data.get("text", ""),
            page=data.get("page", 1),
            score=float(data.get("score", 0.0)),
            metadata=metadata,
            raw=data,
        )


@dataclass
class ChatEvalResponse:
    """
    Response from a chat evaluation request.
    
    Attributes:
        answer: The generated answer text from the LLM.
        sources: List of retrieved source chunks.
        citations: List of citation objects from the response.
        trace_id: Unique identifier for the execution trace.
        session_id: Session identifier.
        conversation_id: Conversation identifier.
        http_latency_ms: Wall-clock HTTP request latency in milliseconds.
        raw_response: Original raw API response dict.
    """
    answer: str
    sources: List[Source]
    citations: List[Dict[str, Any]]
    trace_id: str
    session_id: str
    conversation_id: str
    http_latency_ms: float
    raw_response: Dict[str, Any] = field(default_factory=dict)


class OmniRAGClientError(Exception):
    """Base exception for OmniRAG client errors."""
    pass


class OmniRAGAPIError(OmniRAGClientError):
    """Raised when the API returns a non-success status code."""
    def __init__(self, message: str, status_code: int, response_body: Optional[str] = None):
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(f"{message} (HTTP {status_code})")


class OmniRAGConnectionError(OmniRAGClientError):
    """Raised when connection to the API fails."""
    pass


class OmniRAGClient:
    """
    Synchronous HTTP client for the OmniRAG RAG API.
    
    This client is designed for offline evaluation, not production use.
    It uses synchronous HTTP requests for simplicity in evaluation scripts.
    
    Attributes:
        base_url: Base URL for the OmniRAG backend API.
        access_token: JWT access token for authenticated calls.
        timeout: HTTP request timeout in seconds.
        
    Example:
        client = OmniRAGClient("http://localhost:8081", access_token="your-jwt")
        
        # Send a chat request
        response = client.chat("What is the company policy?")
        print(f"Answer: {response.answer}")
        print(f"Latency: {response.http_latency_ms}ms")
        
        # Get execution trace
        trace = client.get_trace(response.trace_id)
        print(f"Steps: {len(trace.get('steps', []))}")
    """
    
    def __init__(
        self,
        base_url: str,
        access_token: Optional[str] = None,
        timeout: float = 120.0,
    ):
        """
        Initialize the OmniRAG client.
        
        Args:
            base_url: Base URL for the backend API (e.g., "http://localhost:8081").
            access_token: JWT access token for authenticated requests.
            timeout: HTTP request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)
        logger.info(f"Initialized OmniRAGClient with base_url={self.base_url}")

    def _get_headers(self) -> Dict[str, str]:
        """Build request headers with Authorization."""
        if not self.access_token:
            raise OmniRAGClientError("access_token is required for authenticated calls")
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }
    
    def chat(
        self,
        query: str,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> ChatEvalResponse:
        """
        Send a chat request to the RAG system.
        
        Args:
            query: The question/query to send.
            session_id: Optional session ID (generated by backend if not provided).
            conversation_id: Optional conversation ID (generated by backend if not provided).
            
        Returns:
            ChatEvalResponse with answer, sources, trace_id, and latency.
            
        Raises:
            OmniRAGAPIError: If the API returns a non-200 status code.
            OmniRAGConnectionError: If connection to the API fails.
        """
        url = f"{self.base_url}/api/chat/completions"
        
        payload: Dict[str, Any] = {"message": query}
        if session_id:
            payload["session_id"] = session_id
        if conversation_id:
            payload["conversation_id"] = conversation_id
        
        headers = self._get_headers()
        
        logger.debug(f"Sending chat request: query='{query[:50]}...'")
        
        start_time = time.perf_counter()
        try:
            response = self._client.post(url, json=payload, headers=headers)
        except httpx.ConnectError as e:
            raise OmniRAGConnectionError(
                f"Failed to connect to {url}: {e}"
            ) from e
        except httpx.TimeoutException as e:
            raise OmniRAGConnectionError(
                f"Request timed out after {self.timeout}s: {e}"
            ) from e
        except httpx.HTTPError as e:
            raise OmniRAGConnectionError(
                f"HTTP error during request: {e}"
            ) from e
        
        http_latency_ms = (time.perf_counter() - start_time) * 1000
        
        if response.status_code != 200:
            raise OmniRAGAPIError(
                f"Chat request failed",
                status_code=response.status_code,
                response_body=response.text[:1000] if response.text else None,
            )
        
        try:
            data = response.json()
        except Exception as e:
            raise OmniRAGClientError(f"Failed to parse JSON response: {e}")
        
        # Extract data from nested response structure
        response_data = data.get("data", data)
        
        message = response_data.get("message", {})
        answer = message.get("content", "")
        
        # Parse sources
        raw_sources = response_data.get("sources", [])
        sources = [Source.from_api_response(s) for s in raw_sources]
        
        citations = response_data.get("citations", [])
        trace_id = response_data.get("trace_id", "")
        session_id_resp = response_data.get("session_id", "")
        conversation_id_resp = response_data.get("conversation_id", "")
        
        logger.info(
            f"Chat response received: {len(sources)} sources, "
            f"trace_id={trace_id}, latency={http_latency_ms:.1f}ms"
        )
        
        return ChatEvalResponse(
            answer=answer,
            sources=sources,
            citations=citations,
            trace_id=trace_id,
            session_id=session_id_resp,
            conversation_id=conversation_id_resp,
            http_latency_ms=http_latency_ms,
            raw_response=data,
        )
    
    def get_trace(
        self,
        trace_id: str,
    ) -> Dict[str, Any]:
        """
        Retrieve an execution trace by ID.
        
        Args:
            trace_id: The trace ID to retrieve.
        Returns:
            Dict containing trace data with steps, tools_used, citations, etc.
            
        Raises:
            OmniRAGAPIError: If the API returns a non-200 status code.
            OmniRAGConnectionError: If connection to the API fails.
        """
        import time
        
        url = f"{self.base_url}/traces/{trace_id}"
        headers = self._get_headers()
        
        logger.debug(f"Fetching trace: {trace_id}")
        
        # Retry once after a short delay (trace might not be persisted yet)
        max_retries = 2
        for attempt in range(max_retries):
            try:
                response = self._client.get(url, headers=headers, timeout=5.0)
                
                if response.status_code == 200:
                    try:
                        return response.json()
                    except Exception as e:
                        raise OmniRAGClientError(f"Failed to parse trace JSON: {e}") from e
                
                elif response.status_code == 404:
                    # Trace not found - might not be persisted yet, retry once
                    if attempt < max_retries - 1:
                        logger.debug(f"Trace {trace_id} not found (404), retrying after 1s...")
                        time.sleep(1.0)
                        continue
                    else:
                        raise OmniRAGAPIError(
                            f"Trace not found",
                            status_code=404,
                            response_body=response.text[:500] if response.text else None,
                        )
                else:
                    raise OmniRAGAPIError(
                        f"Trace retrieval failed",
                        status_code=response.status_code,
                        response_body=response.text[:500] if response.text else None,
                    )
                    
            except httpx.ConnectError as e:
                raise OmniRAGConnectionError(
                    f"Failed to connect to {url}: {e}"
                ) from e
            except httpx.TimeoutException as e:
                raise OmniRAGConnectionError(
                    f"Request timed out after 5s: {e}"
                ) from e
            except httpx.HTTPError as e:
                raise OmniRAGConnectionError(
                    f"HTTP error during request: {e}"
                ) from e
        
        # Should not reach here, but just in case
        raise OmniRAGAPIError("Trace retrieval failed after retries", status_code=404)
    
    def get_document(
        self,
        doc_id: str,
    ) -> Dict[str, Any]:
        """
        Retrieve document metadata by ID.
        
        Note: This method is provided for future extensibility.
        Currently not used in v1 evaluation pipeline.
        
        Args:
            doc_id: The document ID to retrieve.
        Returns:
            Dict containing document metadata.
        """
        url = f"{self.base_url}/documents/{doc_id}"
        headers = self._get_headers()
        
        logger.debug(f"Fetching document: {doc_id}")
        
        try:
            response = self._client.get(url, headers=headers)
        except httpx.HTTPError as e:
            raise OmniRAGConnectionError(
                f"HTTP error during request: {e}"
            ) from e
        
        if response.status_code != 200:
            raise OmniRAGAPIError(
                f"Document retrieval failed",
                status_code=response.status_code,
                response_body=response.text[:1000] if response.text else None,
            )
        
        return response.json()
    
    def health_check(self) -> bool:
        """
        Check if the backend is healthy.
        
        Returns:
            True if backend responds with status=ok, False otherwise.
        """
        try:
            response = self._client.get(f"{self.base_url}/healthz")
            if response.status_code == 200:
                data = response.json()
                return data.get("status") == "ok"
            return False
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False
    
    def close(self) -> None:
        """Close the HTTP client and release resources."""
        self._client.close()
    
    def __enter__(self) -> "OmniRAGClient":
        return self
    
    def __exit__(self, *args) -> None:
        self.close()
