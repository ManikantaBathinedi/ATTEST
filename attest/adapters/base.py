"""Base agent adapter interface.

All agent adapters must implement this ABC. The adapter's job is to:
1. Connect to an agent (HTTP, WebSocket, SDK, callable, etc.)
2. Send a message (with optional conversation history)
3. Return a standardized AgentResponse

The framework doesn't care HOW the agent is reached — only that the adapter
produces an AgentResponse with content, tool_calls, and timing info.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from attest.core.models import AgentResponse, Message, ToolCall


@dataclass
class StreamChunk:
    """A single chunk emitted by a streaming agent response."""

    delta: str = ""  # Incremental text in this chunk
    done: bool = False  # True on the final chunk
    tool_call: Optional[ToolCall] = None  # Tool call surfaced in this chunk, if any
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentCapabilities:
    """Describes what an agent can do — populated by adapter if discoverable."""

    supports_streaming: bool = False
    supports_tool_calls: bool = False
    supports_multi_turn: bool = True
    supports_attachments: bool = False
    available_tools: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseAgentAdapter(ABC):
    """Interface all agent adapters must implement."""

    @abstractmethod
    async def send_message(
        self,
        message: str,
        conversation_history: Optional[List[Message]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResponse:
        """Send a message to the agent and get a response.

        Args:
            message: The user message to send.
            conversation_history: Prior messages for multi-turn context.
            metadata: Additional data (session_id, attachments, etc.)

        Returns:
            Standardized AgentResponse with content, tool_calls, latency.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the agent is reachable and responsive.

        Returns:
            True if the agent is up and responding.
        """
        ...

    async def send_message_stream(
        self,
        message: str,
        conversation_history: Optional[List[Message]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream the agent's response chunk-by-chunk.

        Default implementation falls back to the non-streaming ``send_message``
        and yields the whole response as a single final chunk. Adapters that
        support real streaming should override this to yield incremental
        ``StreamChunk`` objects (and set ``supports_streaming=True`` in
        capabilities).

        Yields:
            StreamChunk objects; the last one has ``done=True``.
        """
        response = await self.send_message(message, conversation_history, metadata)
        for tc in response.tool_calls:
            yield StreamChunk(tool_call=tc)
        yield StreamChunk(delta=response.content, done=True, metadata=response.metadata)

    async def collect_stream(
        self,
        message: str,
        conversation_history: Optional[List[Message]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResponse:
        """Consume ``send_message_stream`` into a full AgentResponse.

        Measures ``time_to_first_token_ms`` (the latency until the first
        non-empty text chunk) and total ``latency_ms``. Useful for testing
        streaming agents with the same assertions as non-streaming ones.
        """
        start = time.perf_counter()
        first_token_at: Optional[float] = None
        parts: List[str] = []
        tool_calls: List[ToolCall] = []
        last_meta: Dict[str, Any] = {}

        async for chunk in self.send_message_stream(message, conversation_history, metadata):
            if chunk.tool_call is not None:
                tool_calls.append(chunk.tool_call)
            if chunk.delta:
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                parts.append(chunk.delta)
            if chunk.metadata:
                last_meta = chunk.metadata

        total_ms = (time.perf_counter() - start) * 1000
        ttft_ms = ((first_token_at - start) * 1000) if first_token_at is not None else total_ms

        return AgentResponse(
            content="".join(parts),
            tool_calls=tool_calls,
            latency_ms=total_ms,
            time_to_first_token_ms=ttft_ms,
            metadata=last_meta,
        )

    async def get_capabilities(self) -> AgentCapabilities:
        """Get agent capabilities (if discoverable).

        Override this in adapters that can introspect the agent.
        """
        return AgentCapabilities()

    async def setup(self) -> None:
        """One-time setup before test execution (e.g., create session).

        Override if the agent requires initialization.
        """
        pass

    async def teardown(self) -> None:
        """Cleanup after test execution (e.g., close session).

        Override if the agent requires cleanup.
        """
        pass

    async def reset_conversation(self) -> None:
        """Reset conversation state between test cases.

        Override if the agent maintains server-side session state.
        """
        pass
