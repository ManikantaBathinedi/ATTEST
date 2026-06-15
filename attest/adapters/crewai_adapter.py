"""CrewAI adapter.

Tests a CrewAI ``Crew`` (or any object with a ``kickoff`` method). The adapter
calls ``kickoff(inputs=...)`` and extracts the final text result plus any tool
usage CrewAI exposes on the result.

CrewAI runs in-process, so use this adapter directly in Python:

    from crewai import Crew
    from attest.adapters import CrewAIAgentAdapter

    crew = Crew(agents=[...], tasks=[...])
    adapter = CrewAIAgentAdapter(crew, input_key="topic")
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from attest.adapters.base import AgentCapabilities, BaseAgentAdapter
from attest.core.exceptions import AdapterError
from attest.core.models import AgentResponse, Message, ToolCall, TokenUsage


class CrewAIAgentAdapter(BaseAgentAdapter):
    """Adapter for CrewAI crews / agents."""

    def __init__(self, crew: Any, input_key: str = "input"):
        """
        Args:
            crew: A CrewAI ``Crew`` (or anything with ``kickoff``).
            input_key: The key in the ``inputs`` dict passed to ``kickoff``
                that carries the user message (CrewAI tasks reference inputs by
                name, e.g. ``{topic}`` → ``input_key="topic"``).
        """
        if crew is None:
            raise AdapterError("CrewAIAgentAdapter requires a crew object.")
        if not (hasattr(crew, "kickoff") or hasattr(crew, "kickoff_async")):
            raise AdapterError(
                "Object passed to CrewAIAgentAdapter does not look like a CrewAI "
                "crew (no 'kickoff' / 'kickoff_async' method)."
            )
        self._crew = crew
        self._input_key = input_key

    async def send_message(
        self,
        message: str,
        conversation_history: Optional[List[Message]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResponse:
        inputs = {self._input_key: message}
        start = time.perf_counter()
        try:
            if hasattr(self._crew, "kickoff_async"):
                result = await self._crew.kickoff_async(inputs=inputs)
            else:
                result = await asyncio.to_thread(self._crew.kickoff, inputs=inputs)
        except TypeError:
            # Some versions accept no inputs kwarg.
            try:
                result = await asyncio.to_thread(self._crew.kickoff)
            except Exception as e:  # noqa: BLE001
                raise AdapterError(f"CrewAI kickoff failed: {e}") from e
        except Exception as e:  # noqa: BLE001
            raise AdapterError(f"CrewAI kickoff failed: {e}") from e
        latency_ms = (time.perf_counter() - start) * 1000

        return AgentResponse(
            content=self._extract_text(result),
            tool_calls=self._extract_tool_calls(result),
            latency_ms=latency_ms,
            token_usage=self._extract_usage(result),
            raw_response=result,
        )

    async def health_check(self) -> bool:
        return True

    async def get_capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(supports_tool_calls=True, supports_multi_turn=False)

    # ------------------------------------------------------------------
    @staticmethod
    def _extract_text(result: Any) -> str:
        if isinstance(result, str):
            return result
        # CrewOutput exposes `.raw` (and often `.tasks_output`)
        for attr in ("raw", "result", "output"):
            val = getattr(result, attr, None)
            if isinstance(val, str) and val:
                return val
        return str(result)

    @staticmethod
    def _extract_tool_calls(result: Any) -> List[ToolCall]:
        calls: List[ToolCall] = []
        # CrewAI surfaces tool usage on task outputs in some versions.
        tasks = getattr(result, "tasks_output", None) or []
        for t in tasks:
            for tc in getattr(t, "tools_used", []) or []:
                name = tc if isinstance(tc, str) else getattr(tc, "name", None)
                if name:
                    calls.append(ToolCall(name=str(name)))
        return calls

    @staticmethod
    def _extract_usage(result: Any) -> Optional[TokenUsage]:
        usage = getattr(result, "token_usage", None)
        if usage is None:
            return None
        try:
            total = int(getattr(usage, "total_tokens", 0) or 0)
            prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion = int(getattr(usage, "completion_tokens", 0) or 0)
            if total == 0 and prompt == 0 and completion == 0:
                return None
            return TokenUsage(input_tokens=prompt, output_tokens=completion, total_tokens=total)
        except Exception:
            return None
