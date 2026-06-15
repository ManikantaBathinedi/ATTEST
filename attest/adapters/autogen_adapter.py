"""AutoGen adapter.

Tests a Microsoft AutoGen agent. Supports the modern AgentChat API
(``AssistantAgent`` / teams with ``run(task=...)`` returning a ``TaskResult``)
and falls back to a generic callable interface for older styles.

AutoGen runs in-process, so use this adapter directly in Python:

    from autogen_agentchat.agents import AssistantAgent
    from attest.adapters import AutoGenAgentAdapter

    agent = AssistantAgent("assistant", model_client=...)
    adapter = AutoGenAgentAdapter(agent)
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from attest.adapters.base import AgentCapabilities, BaseAgentAdapter
from attest.core.exceptions import AdapterError
from attest.core.models import AgentResponse, Message, ToolCall


class AutoGenAgentAdapter(BaseAgentAdapter):
    """Adapter for AutoGen agents / teams (AgentChat ``run`` API)."""

    def __init__(self, agent: Any):
        """
        Args:
            agent: An AutoGen agent or team. Must expose an async ``run`` method
                (AgentChat) — ``run(task=...)`` returning a result with
                ``.messages``.
        """
        if agent is None:
            raise AdapterError("AutoGenAgentAdapter requires an agent object.")
        if not hasattr(agent, "run"):
            raise AdapterError(
                "Object passed to AutoGenAgentAdapter does not look like an "
                "AutoGen AgentChat agent/team (no 'run' method)."
            )
        self._agent = agent

    async def send_message(
        self,
        message: str,
        conversation_history: Optional[List[Message]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResponse:
        start = time.perf_counter()
        try:
            run = self._agent.run
            if asyncio.iscoroutinefunction(run):
                result = await run(task=message)
            else:
                result = await asyncio.to_thread(run, task=message)
        except TypeError:
            # Older/alt signature: run(message) positional
            try:
                run = self._agent.run
                if asyncio.iscoroutinefunction(run):
                    result = await run(message)
                else:
                    result = await asyncio.to_thread(run, message)
            except Exception as e:  # noqa: BLE001
                raise AdapterError(f"AutoGen run failed: {e}") from e
        except Exception as e:  # noqa: BLE001
            raise AdapterError(f"AutoGen run failed: {e}") from e
        latency_ms = (time.perf_counter() - start) * 1000

        content, tool_calls = self._extract(result)
        return AgentResponse(
            content=content,
            tool_calls=tool_calls,
            latency_ms=latency_ms,
            raw_response=result,
        )

    async def health_check(self) -> bool:
        return True

    async def get_capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(supports_tool_calls=True, supports_multi_turn=True)

    # ------------------------------------------------------------------
    def _extract(self, result: Any):
        """Return (final_text, tool_calls) from an AutoGen result."""
        messages = getattr(result, "messages", None)
        if messages is None and isinstance(result, dict):
            messages = result.get("messages")

        if not messages:
            # Result might already be a string or message-like.
            return self._stringify(result), []

        tool_calls: List[ToolCall] = []
        final_text = ""
        for msg in messages:
            # Capture tool calls when present.
            for tc in getattr(msg, "tool_calls", []) or []:
                name = getattr(tc, "name", None) or (tc.get("name") if isinstance(tc, dict) else None)
                if name:
                    args = getattr(tc, "arguments", None)
                    if args is None and isinstance(tc, dict):
                        args = tc.get("arguments")
                    tool_calls.append(
                        ToolCall(name=str(name), arguments=args if isinstance(args, dict) else {})
                    )
            text = self._message_text(msg)
            if text:
                final_text = text  # keep last non-empty text as the answer
        return final_text, tool_calls

    @staticmethod
    def _message_text(msg: Any) -> str:
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [c if isinstance(c, str) else str(getattr(c, "text", "")) for c in content]
            return "".join(p for p in parts if p)
        return "" if content is None else str(content)

    @staticmethod
    def _stringify(result: Any) -> str:
        if isinstance(result, str):
            return result
        return str(getattr(result, "content", result))
