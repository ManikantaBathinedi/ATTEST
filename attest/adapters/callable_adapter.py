"""Callable agent adapter.

For when the agent is a Python function or class — no HTTP server needed.
This is useful for:
  - Testing agent logic directly (fastest, no network overhead)
  - Agents that are Python packages (import and call)
  - Unit-testing agent code before deployment

Usage:
    from my_agent import handle_message

    # Simple: function takes string, returns string
    adapter = CallableAgentAdapter(fn=handle_message)

    # Advanced: custom input/output mapping
    adapter = CallableAgentAdapter(
        fn=my_agent.chat,
        input_param="user_message",              # kwarg name for the input
        output_extract=lambda r: r.response_text, # how to get text from return value
    )
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List, Optional

from attest.adapters.base import BaseAgentAdapter
from attest.core.exceptions import AdapterError
from attest.core.models import AgentResponse, Message


class CallableAgentAdapter(BaseAgentAdapter):
    """Adapter that calls a Python function or method directly.

    The callable can be:
    - A simple function: fn("hello") → "hi there"
    - An async function: async fn("hello") → "hi there"
    - A method: agent.chat("hello") → "hi there"
    """

    def __init__(
        self,
        fn: Callable,
        input_param: str = "message",
        output_extract: Optional[Callable[[Any], str]] = None,
    ):
        """
        Args:
            fn: The function/method to call. Can be sync or async.
            input_param: The keyword argument name for the input message.
                         Default "message" → fn(message="hello").
                         Set to None to pass as positional arg → fn("hello").
            output_extract: Optional function to extract text from the return value.
                           Default: treats return value as a string.
                           Example: lambda r: r.response_text
        """
        self._fn = fn
        self._input_param = input_param
        self._output_extract = output_extract

    async def send_message(
        self,
        message: str,
        conversation_history: Optional[List[Message]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResponse:
        """Call the function with the message and return the response."""
        # Build the arguments
        if self._input_param:
            kwargs = {self._input_param: message}
        else:
            kwargs = {}

        # Measure latency
        start_time = time.perf_counter()

        try:
            # Call the function (support both sync and async)
            if asyncio.iscoroutinefunction(self._fn):
                if self._input_param:
                    result = await self._fn(**kwargs)
                else:
                    result = await self._fn(message)
            else:
                if self._input_param:
                    result = self._fn(**kwargs)
                else:
                    result = self._fn(message)
        except Exception as e:
            raise AdapterError(f"Callable agent raised an error: {e}") from e

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Extract the text response
        if self._output_extract:
            content = self._output_extract(result)
        elif isinstance(result, str):
            content = result
        elif isinstance(result, dict):
            # Try common keys
            content = (
                result.get("response")
                or result.get("content")
                or result.get("answer")
                or result.get("message")
                or str(result)
            )
        else:
            content = str(result)

        return AgentResponse(content=content, latency_ms=latency_ms)

    async def health_check(self) -> bool:
        """Callable is always 'healthy' — it's local code."""
        return True
