"""Base agent adapter interface.

All agent adapters must implement this ABC. The adapter's job is to:
1. Connect to an agent (HTTP, WebSocket, SDK, callable, etc.)
2. Send a message (with optional conversation history)
3. Return a standardized AgentResponse

The framework doesn't care HOW the agent is reached — only that the adapter
produces an AgentResponse with content, tool_calls, and timing info.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from attest.core.models import AgentResponse, Message, ToolCall


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
