"""
Streaming response handler for real-time agent responses.

Provides chunked HTTP streaming with proper formatting, timing,
and different message types for progressive response delivery.
"""

import logging
import json
from typing import Any, Dict, AsyncGenerator, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class StreamingResponse:
    """
    Handles streaming response formatting and chunking.

    Supports different message types:
    - start: Beginning of response
    - thinking: Agent reasoning process
    - action: Tool execution
    - observation: Tool results
    - answer: Final response
    - error: Error messages
    - end: Completion signal
    """

    def __init__(self):
        self.chunk_id_counter = 0
        self.message_buffer = ""

    def format_chunk(self, message_type: str, data: Dict[str, Any]) -> str:
        """
        Format a response chunk with proper structure.

        Args:
            message_type: Type of message (start, thinking, action, etc.)
            data: Message content and metadata

        Returns:
            str: JSON-formatted chunk ready for streaming
        """
        try:
            self.chunk_id_counter += 1

            chunk = {
                "id": self.chunk_id_counter,
                "type": message_type,
                "timestamp": datetime.utcnow().isoformat(),
                "data": data,
            }

            # Convert to JSON string with newline for streaming
            chunk_json = json.dumps(chunk, separators=(",", ":"))
            return f"data: {chunk_json}\\n\\n"

        except Exception as e:
            logger.error(f"Chunk formatting failed: {e}")
            # Return error chunk instead
            error_chunk = {
                "id": self.chunk_id_counter,
                "type": "error",
                "timestamp": datetime.utcnow().isoformat(),
                "data": {"error": f"Formatting error: {str(e)}"},
            }
            return f"data: {json.dumps(error_chunk, separators=(',', ':'))}\\n\\n"

    async def stream_response(
        self, response_generator, chunk_size: int = 100
    ) -> AsyncGenerator[str, None]:
        """
        Stream response with configurable chunking.

        Args:
            response_generator: Generator yielding response parts
            chunk_size: Maximum size of each chunk in bytes

        Yields:
            str: Formatted chunks for HTTP streaming
        """
        try:
            buffer = ""

            async for chunk in response_generator:
                buffer += str(chunk)

                # Check if buffer exceeds chunk_size
                while len(buffer.encode("utf-8")) >= chunk_size:
                    # Split at nearest complete JSON structure
                    split_pos = self._find_safe_split_point(buffer)
                    if split_pos > 0:
                        yield buffer[:split_pos]
                        buffer = buffer[split_pos:]
                    else:
                        # If no safe split point, yield the whole buffer
                        yield buffer
                        buffer = ""

            # Yield remaining buffer at the end
            if buffer:
                yield buffer

        except Exception as e:
            logger.error(f"Streaming failed: {e}")
            error_chunk = self.format_chunk(
                "error", {"message": f"Streaming error: {str(e)}"}
            )
            yield error_chunk

    def _find_safe_split_point(self, buffer: str) -> int:
        """
        Find safe point to split JSON buffer.

        Looks for complete JSON structures to avoid breaking
        them mid-transmission.
        """
        # Count JSON structure characters
        open_braces = 0
        close_braces = 0
        in_string = False

        for i, char in enumerate(buffer):
            if char == '"' and not in_string:
                in_string = not in_string
            elif char == "\\\\" and in_string:
                in_string = not in_string

            if not in_string:
                if char == "{":
                    open_braces += 1
                elif char == "}":
                    close_braces += 1

                # Safe split point: complete JSON object
                if close_braces >= open_braces and close_braces > 0:
                    return i + 1

        return -1  # No safe split point found

    def create_start_chunk(self, session_id: str, message: str) -> str:
        """Create initial connection chunk."""
        return self.format_chunk(
            "start",
            {
                "session_id": session_id,
                "message": message,
                "agent_version": "1.0.0",
                "capabilities": ["reasoning", "tool_use", "streaming", "pev"],
            },
        )

    def create_thinking_chunk(self, message: str, step: Optional[str] = None) -> str:
        """Create thinking/reasoning chunk."""
        data = {"message": message}
        if step:
            data["step"] = step
        return self.format_chunk("thinking", data)

    def create_action_chunk(
        self, tool: str, description: str, parameters: Dict[str, Any]
    ) -> str:
        """Create tool execution chunk."""
        return self.format_chunk(
            "action",
            {
                "tool": tool,
                "description": description,
                "parameters": parameters,
                "status": "executing",
            },
        )

    def create_observation_chunk(
        self, tool: str, message: str, results: Dict[str, Any]
    ) -> str:
        """Create tool observation/result chunk."""
        return self.format_chunk(
            "observation",
            {
                "tool": tool,
                "message": message,
                "results": results,
                "status": "completed",
            },
        )

    def create_answer_chunk(
        self,
        answer: str,
        sources: int,
        reasoning_steps: int,
        personalization_applied: bool = False,
    ) -> str:
        """Create final answer chunk."""
        return self.format_chunk(
            "answer",
            {
                "message": answer,
                "sources_used": sources,
                "reasoning_steps": reasoning_steps,
                "personalization_applied": personalization_applied,
                "status": "final",
            },
        )

    def create_error_chunk(
        self, error_message: str, error_type: str = "general"
    ) -> str:
        """Create error chunk."""
        return self.format_chunk(
            "error",
            {
                "message": error_message,
                "error_type": error_type,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

    def create_end_chunk(self, session_id: str, summary: Dict[str, Any]) -> str:
        """Create completion chunk."""
        return self.format_chunk(
            "end",
            {
                "session_id": session_id,
                "summary": summary,
                "total_chunks": self.chunk_id_counter,
                "completion_time": datetime.utcnow().isoformat(),
            },
        )


class StreamingMetrics:
    """Track streaming performance and usage metrics."""

    def __init__(self):
        self.start_time = None
        self.chunks_sent = 0
        self.bytes_sent = 0
        self.errors = 0

    def start_streaming(self):
        """Mark start of streaming session."""
        self.start_time = datetime.utcnow()
        logger.info(f"Streaming started at {self.start_time.isoformat()}")

    def record_chunk(self, chunk_size: int):
        """Record chunk transmission."""
        self.chunks_sent += 1
        self.bytes_sent += chunk_size

    def record_error(self):
        """Record streaming error."""
        self.errors += 1

    def get_metrics(self) -> Dict[str, Any]:
        """Get current streaming metrics."""
        duration = (
            (datetime.utcnow() - self.start_time).total_seconds()
            if self.start_time
            else 0
        )

        return {
            "duration_seconds": duration,
            "chunks_sent": self.chunks_sent,
            "bytes_sent": self.bytes_sent,
            "errors": self.errors,
            "average_chunk_size": (
                self.bytes_sent / self.chunks_sent if self.chunks_sent > 0 else 0
            ),
            "chunks_per_second": self.chunks_sent / duration if duration > 0 else 0,
        }


# Global streaming metrics instance
streaming_metrics = StreamingMetrics()
