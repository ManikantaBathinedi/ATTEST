"""LangGraph agent adapter.

Wraps a compiled LangGraph graph (``StateGraph.compile()``) so it can be
tested with ATTEST. LangGraph is the graph-based successor to LangChain agents
and is widely used for multi-step / multi-agent workflows.

A compiled LangGraph exposes ``invoke`` / ``ainvoke`` and operates on a state
dict — most commonly ``{"messages": [...]}``. The returned state contains the
full message list, including:
  - ``AIMessage`` objects (the assistant turns, which carry ``tool_calls``)
  - ``ToolMessage`` objects (tool execution results)

This adapter extracts the final assistant text, every tool call (with its
result paired by ``tool_call_id`` when available), and token usage.

Because a compiled graph is an in-process Python object, this adapter is used
directly in Python code, not created from ``attest.yaml``.

Usage::

    from langgraph.prebuilt import create_react_agent
    from attest.adapters import LangGraphAgentAdapter

    graph = create_react_agent(model, tools)
    adapter = LangGraphAgentAdapter(graph)

    # Custom state shape:
    adapter = LangGraphAgentAdapter(graph, messages_key="messages")
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from attest.adapters.base import AgentCapabilities, BaseAgentAdapter
from attest.core.exceptions import AdapterError
from attest.core.models import AgentResponse, Message, ToolCall, TokenUsage


class LangGraphAgentAdapter(BaseAgentAdapter):
    """Adapter for compiled LangGraph graphs.

    Works with any compiled graph that exposes ``invoke`` / ``ainvoke`` and
    uses a message-list state (the LangGraph convention).
    """

    def __init__(
        self,
        graph: Any,
        messages_key: str = "messages",
        pass_history: bool = True,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            graph: A compiled LangGraph graph (result of ``StateGraph.compile()``
                or a prebuilt agent like ``create_react_agent``).
            messages_key: The state key that holds the message list
                (``"messages"`` by convention).
            pass_history: Whether to prepend ATTEST conversation history to the
                messages sent into the graph.
            config: Optional LangGraph runtime config (e.g. ``{"configurable":
                {"thread_id": "..."}}``) forwarded on every invoke.
        """
        if graph is None:
            raise AdapterError("LangGraphAgentAdapter requires a non-None graph.")
        if not (hasattr(graph, "invoke") or hasattr(graph, "ainvoke")):
            raise AdapterError(
                "Object passed to LangGraphAgentAdapter does not look like a "
                "compiled LangGraph graph (no 'invoke' or 'ainvoke' method)."
            )
        self._graph = graph
        self._messages_key = messages_key
        self._pass_history = pass_history
        self._config = config

    async def send_message(
        self,
        message: str,
        conversation_history: Optional[List[Message]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResponse:
        """Invoke the LangGraph graph and return a standardized response."""
        messages = self._build_input_messages(message, conversation_history)
        state = {self._messages_key: messages}

        start_time = time.perf_counter()
        try:
            if hasattr(self._graph, "ainvoke"):
                result = await self._graph.ainvoke(state, self._config)
            else:
                result = await asyncio.to_thread(self._graph.invoke, state, self._config)
        except Exception as e:  # noqa: BLE001 - surface as adapter error
            raise AdapterError(f"LangGraph graph raised an error: {e}") from e
        latency_ms = (time.perf_counter() - start_time) * 1000

        out_messages = self._result_messages(result)
        content = self._extract_final_content(out_messages)
        tool_calls = self._extract_tool_calls(out_messages)
        token_usage = self._extract_token_usage(out_messages)

        return AgentResponse(
            content=content,
            tool_calls=tool_calls,
            latency_ms=latency_ms,
            token_usage=token_usage,
            raw_response=result,
        )

    async def health_check(self) -> bool:
        """Compiled graphs are in-process objects — always reachable."""
        return True

    async def get_capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            supports_tool_calls=True,
            supports_multi_turn=True,
        )

    # ------------------------------------------------------------------
    # Input construction
    # ------------------------------------------------------------------
    def _build_input_messages(
        self, message: str, history: Optional[List[Message]]
    ) -> List[Any]:
        """Build the message list to send into the graph."""
        try:
            from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

            msgs: List[Any] = []
            if self._pass_history and history:
                for m in history:
                    if m.role == "assistant":
                        msgs.append(AIMessage(content=m.content))
                    elif m.role == "system":
                        msgs.append(SystemMessage(content=m.content))
                    else:
                        msgs.append(HumanMessage(content=m.content))
            msgs.append(HumanMessage(content=message))
            return msgs
        except ImportError:
            # Fall back to (role, content) tuples, which LangGraph also accepts.
            msgs = []
            if self._pass_history and history:
                msgs.extend((m.role, m.content) for m in history)
            msgs.append(("user", message))
            return msgs

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------
    def _result_messages(self, result: Any) -> List[Any]:
        """Get the message list out of the returned state."""
        if isinstance(result, dict):
            msgs = result.get(self._messages_key)
            if isinstance(msgs, list):
                return msgs
        # Some graphs return the message list directly
        if isinstance(result, list):
            return result
        return []

    def _extract_final_content(self, messages: List[Any]) -> str:
        """The final assistant text is the last AI message with text content."""
        for msg in reversed(messages):
            if self._message_type(msg) == "ai":
                text = self._stringify_content(getattr(msg, "content", msg))
                if text:
                    return text
        # Fallback: last message of any kind
        if messages:
            return self._stringify_content(getattr(messages[-1], "content", messages[-1]))
        return ""

    def _extract_tool_calls(self, messages: List[Any]) -> List[ToolCall]:
        """Collect tool calls from AIMessages, pairing results from ToolMessages."""
        # Map tool_call_id -> result content from ToolMessages
        results_by_id: Dict[str, str] = {}
        for msg in messages:
            if self._message_type(msg) == "tool":
                call_id = getattr(msg, "tool_call_id", None)
                if call_id:
                    results_by_id[call_id] = self._stringify_content(
                        getattr(msg, "content", "")
                    )

        tool_calls: List[ToolCall] = []
        for msg in messages:
            raw_calls = getattr(msg, "tool_calls", None)
            if not raw_calls:
                continue
            for tc in raw_calls:
                # tc may be a dict {"name","args","id"} or an object
                if isinstance(tc, dict):
                    name = tc.get("name")
                    args = tc.get("args", {})
                    call_id = tc.get("id")
                else:
                    name = getattr(tc, "name", None)
                    args = getattr(tc, "args", {})
                    call_id = getattr(tc, "id", None)
                if not name:
                    continue
                if not isinstance(args, dict):
                    args = {"input": args}
                tool_calls.append(
                    ToolCall(
                        name=str(name),
                        arguments=args,
                        result=results_by_id.get(call_id) if call_id else None,
                    )
                )
        return tool_calls

    def _extract_token_usage(self, messages: List[Any]) -> Optional[TokenUsage]:
        """Sum token usage across AI messages that report ``usage_metadata``."""
        total_in = total_out = total = 0
        found = False
        for msg in messages:
            usage = getattr(msg, "usage_metadata", None)
            if isinstance(usage, dict):
                found = True
                total_in += int(usage.get("input_tokens", 0) or 0)
                total_out += int(usage.get("output_tokens", 0) or 0)
                total += int(usage.get("total_tokens", 0) or 0)
        if not found:
            return None
        if total == 0:
            total = total_in + total_out
        return TokenUsage(input_tokens=total_in, output_tokens=total_out, total_tokens=total)

    # ------------------------------------------------------------------
    # Small utilities
    # ------------------------------------------------------------------
    @staticmethod
    def _message_type(msg: Any) -> str:
        """Best-effort classification: 'ai', 'tool', 'human', 'system', or ''."""
        t = getattr(msg, "type", None)
        if isinstance(t, str):
            return t
        cls = type(msg).__name__.lower()
        if "ai" in cls:
            return "ai"
        if "tool" in cls:
            return "tool"
        if "human" in cls:
            return "human"
        if "system" in cls:
            return "system"
        return ""

    @staticmethod
    def _stringify_content(content: Any) -> str:
        """Normalize message content (str or list of blocks) to text."""
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
