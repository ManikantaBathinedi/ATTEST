"""LangChain agent adapter.

Wraps a LangChain agent (``AgentExecutor``) or any LangChain Runnable so it
can be tested with ATTEST. LangChain is the most widely used agent framework,
so this adapter covers a large share of real-world agents.

It extracts:
  - the final text answer (``output`` / message content)
  - tool calls from ``intermediate_steps`` (when ``return_intermediate_steps``
    is enabled on the ``AgentExecutor``)
  - token usage from the LLM callback / response metadata when available

Because a LangChain agent is an in-process Python object, this adapter is used
directly in Python code (like ``CallableAgentAdapter``), not created from
``attest.yaml``.

Usage::

    from langchain.agents import AgentExecutor, create_tool_calling_agent
    from attest.adapters import LangChainAgentAdapter

    executor = AgentExecutor(
        agent=agent,
        tools=tools,
        return_intermediate_steps=True,   # needed to capture tool calls
    )
    adapter = LangChainAgentAdapter(executor)

    # or wrap any Runnable/chain:
    adapter = LangChainAgentAdapter(my_chain, input_key="question")
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from attest.adapters.base import AgentCapabilities, BaseAgentAdapter, StreamChunk
from attest.core.exceptions import AdapterError
from attest.core.models import AgentResponse, Message, ToolCall, TokenUsage


class LangChainAgentAdapter(BaseAgentAdapter):
    """Adapter for LangChain agents and runnables.

    Works with:
      - ``AgentExecutor`` (recommended; set ``return_intermediate_steps=True``
        to capture tool calls)
      - Any LangChain ``Runnable`` / chain that exposes ``invoke`` / ``ainvoke``
    """

    def __init__(
        self,
        agent: Any,
        input_key: str = "input",
        output_key: str = "output",
        history_key: str = "chat_history",
        pass_history: bool = True,
    ):
        """
        Args:
            agent: A LangChain ``AgentExecutor`` or ``Runnable``.
            input_key: The dict key used for the user message when invoking
                the agent (LangChain agents typically use ``"input"``).
            output_key: The dict key that holds the final answer in the
                agent's return value (typically ``"output"``).
            history_key: The dict key used to pass conversation history to the
                agent (typically ``"chat_history"``).
            pass_history: Whether to forward ATTEST conversation history to the
                agent via ``history_key``. Disable if the agent manages its own
                memory or does not accept a history argument.
        """
        if agent is None:
            raise AdapterError("LangChainAgentAdapter requires a non-None agent.")
        if not (hasattr(agent, "invoke") or hasattr(agent, "ainvoke")):
            raise AdapterError(
                "Object passed to LangChainAgentAdapter does not look like a "
                "LangChain agent/runnable (no 'invoke' or 'ainvoke' method)."
            )
        self._agent = agent
        self._input_key = input_key
        self._output_key = output_key
        self._history_key = history_key
        self._pass_history = pass_history

    async def send_message(
        self,
        message: str,
        conversation_history: Optional[List[Message]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResponse:
        """Invoke the LangChain agent and return a standardized response."""
        payload: Dict[str, Any] = {self._input_key: message}

        if self._pass_history and conversation_history:
            payload[self._history_key] = self._to_lc_history(conversation_history)

        start_time = time.perf_counter()
        try:
            if hasattr(self._agent, "ainvoke"):
                result = await self._agent.ainvoke(payload)
            else:
                # Run sync invoke in a thread so we don't block the event loop.
                result = await asyncio.to_thread(self._agent.invoke, payload)
        except Exception as e:  # noqa: BLE001 - surface as adapter error
            raise AdapterError(f"LangChain agent raised an error: {e}") from e
        latency_ms = (time.perf_counter() - start_time) * 1000

        content = self._extract_content(result)
        tool_calls = self._extract_tool_calls(result)
        token_usage = self._extract_token_usage(result)

        return AgentResponse(
            content=content,
            tool_calls=tool_calls,
            latency_ms=latency_ms,
            token_usage=token_usage,
            raw_response=result,
        )

    async def health_check(self) -> bool:
        """LangChain agents are in-process objects — always reachable."""
        return True

    async def send_message_stream(
        self,
        message: str,
        conversation_history=None,
        metadata=None,
    ):
        """Stream the LangChain agent's output token-by-token when possible.

        Uses the runnable's ``astream`` if available; otherwise falls back to
        the base (single-chunk) implementation.
        """
        if not hasattr(self._agent, "astream"):
            async for chunk in super().send_message_stream(message, conversation_history, metadata):
                yield chunk
            return

        payload = {self._input_key: message}
        if self._pass_history and conversation_history:
            payload[self._history_key] = self._to_lc_history(conversation_history)

        try:
            async for piece in self._agent.astream(payload):
                # piece may be a dict ({"output": "..."}), a message, or a str
                text = ""
                if isinstance(piece, dict):
                    val = piece.get(self._output_key) or piece.get("output")
                    text = self._stringify_message(val) if val is not None else ""
                else:
                    text = self._stringify_message(piece)
                if text:
                    yield StreamChunk(delta=text)
        except Exception as e:  # noqa: BLE001
            raise AdapterError(f"LangChain agent streaming failed: {e}") from e
        yield StreamChunk(done=True)

    async def get_capabilities(self) -> AgentCapabilities:
        tools = getattr(self._agent, "tools", []) or []
        available = []
        for t in tools:
            name = getattr(t, "name", None)
            if name:
                available.append({"name": name, "description": getattr(t, "description", "")})
        return AgentCapabilities(
            supports_tool_calls=bool(available),
            supports_streaming=hasattr(self._agent, "astream"),
            supports_multi_turn=True,
            available_tools=available,
        )

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------
    def _extract_content(self, result: Any) -> str:
        """Pull the final text answer out of a LangChain result."""
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            value = result.get(self._output_key)
            if value is None:
                # Fall back to common keys
                value = result.get("output") or result.get("answer") or result.get("text")
            return self._stringify_message(value) if value is not None else str(result)
        # AIMessage / BaseMessage style objects expose `.content`
        if hasattr(result, "content"):
            return self._stringify_message(result)
        return str(result)

    @staticmethod
    def _stringify_message(value: Any) -> str:
        """Normalize a message-like value to plain text."""
        if isinstance(value, str):
            return value
        content = getattr(value, "content", None)
        if content is None:
            return str(value)
        # content can be a string or a list of content blocks
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and "text" in block:
                    parts.append(str(block["text"]))
            return "".join(parts) if parts else str(content)
        return str(content)

    def _extract_tool_calls(self, result: Any) -> List[ToolCall]:
        """Extract tool calls from AgentExecutor ``intermediate_steps``.

        Each intermediate step is an ``(AgentAction, observation)`` tuple where
        ``AgentAction`` has ``.tool`` (name), ``.tool_input`` (args) and the
        observation is the tool's return value.
        """
        if not isinstance(result, dict):
            return []
        steps = result.get("intermediate_steps")
        if not steps:
            return []

        tool_calls: List[ToolCall] = []
        for step in steps:
            try:
                action, observation = step[0], (step[1] if len(step) > 1 else None)
            except (TypeError, IndexError):
                continue

            name = getattr(action, "tool", None)
            if name is None and isinstance(action, dict):
                name = action.get("tool")
            if not name:
                continue

            raw_args = getattr(action, "tool_input", None)
            if raw_args is None and isinstance(action, dict):
                raw_args = action.get("tool_input")
            if isinstance(raw_args, dict):
                arguments = raw_args
            elif raw_args is None:
                arguments = {}
            else:
                arguments = {"input": raw_args}

            tool_calls.append(
                ToolCall(
                    name=str(name),
                    arguments=arguments,
                    result=None if observation is None else str(observation),
                )
            )
        return tool_calls

    def _extract_token_usage(self, result: Any) -> Optional[TokenUsage]:
        """Best-effort token usage extraction from response metadata."""
        if not isinstance(result, dict):
            return None
        # Some chains surface usage under these keys
        usage = result.get("usage_metadata") or result.get("token_usage")
        if not isinstance(usage, dict):
            return None
        input_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
        output_tokens = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
        total = int(usage.get("total_tokens", input_tokens + output_tokens) or 0)
        if input_tokens == 0 and output_tokens == 0 and total == 0:
            return None
        return TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total)

    @staticmethod
    def _to_lc_history(history: List[Message]) -> List[Any]:
        """Convert ATTEST messages to LangChain message objects.

        Falls back to ``(role, content)`` tuples if langchain_core isn't
        importable, which most LangChain agents also accept.
        """
        try:
            from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

            lc_messages: List[Any] = []
            for m in history:
                if m.role == "user":
                    lc_messages.append(HumanMessage(content=m.content))
                elif m.role == "assistant":
                    lc_messages.append(AIMessage(content=m.content))
                elif m.role == "system":
                    lc_messages.append(SystemMessage(content=m.content))
                else:
                    lc_messages.append(HumanMessage(content=m.content))
            return lc_messages
        except ImportError:
            return [(m.role, m.content) for m in history]
