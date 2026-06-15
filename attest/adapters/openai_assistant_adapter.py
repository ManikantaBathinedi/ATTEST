"""OpenAI Assistants API adapter.

Tests an agent built on OpenAI's Assistants API (threads + runs). You pass an
existing OpenAI client and an ``assistant_id``; the adapter creates a thread,
adds the user message, runs the assistant, polls to completion, and returns the
final assistant message plus any tool calls the run required.

Because it wraps an OpenAI SDK client (an in-process object), use it directly
in Python:

    from openai import OpenAI
    from attest.adapters import OpenAIAssistantAdapter

    client = OpenAI()
    adapter = OpenAIAssistantAdapter(client, assistant_id="asst_123")
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from attest.adapters.base import AgentCapabilities, BaseAgentAdapter
from attest.core.exceptions import AdapterError
from attest.core.models import AgentResponse, Message, ToolCall, TokenUsage


class OpenAIAssistantAdapter(BaseAgentAdapter):
    """Adapter for the OpenAI Assistants API."""

    def __init__(
        self,
        client: Any,
        assistant_id: str,
        poll_interval: float = 0.5,
        max_wait_seconds: float = 120.0,
    ):
        """
        Args:
            client: An ``openai.OpenAI`` (or Azure) client instance.
            assistant_id: The id of the assistant to run (``asst_...``).
            poll_interval: Seconds between run-status polls.
            max_wait_seconds: Give up after this long waiting for a run.
        """
        if client is None or not assistant_id:
            raise AdapterError("OpenAIAssistantAdapter requires a client and assistant_id.")
        if not hasattr(client, "beta") or not hasattr(client.beta, "threads"):
            raise AdapterError(
                "Object passed to OpenAIAssistantAdapter is not an OpenAI client "
                "(missing client.beta.threads)."
            )
        self._client = client
        self._assistant_id = assistant_id
        self._poll = poll_interval
        self._max_wait = max_wait_seconds

    async def send_message(
        self,
        message: str,
        conversation_history: Optional[List[Message]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResponse:
        start = time.perf_counter()
        try:
            return await asyncio.to_thread(self._run_sync, message, conversation_history)
        except AdapterError:
            raise
        except Exception as e:  # noqa: BLE001
            raise AdapterError(f"OpenAI Assistants run failed: {e}") from e
        finally:
            # latency is set inside _run_sync; nothing to do here
            _ = start

    def _run_sync(self, message: str, history: Optional[List[Message]]) -> AgentResponse:
        start = time.perf_counter()
        threads = self._client.beta.threads

        # Seed a thread with prior history, then the new user message.
        initial: List[Dict[str, str]] = []
        for m in history or []:
            role = "assistant" if m.role == "assistant" else "user"
            initial.append({"role": role, "content": m.content})
        thread = threads.create(messages=initial or None)
        threads.messages.create(thread_id=thread.id, role="user", content=message)

        run = threads.runs.create(thread_id=thread.id, assistant_id=self._assistant_id)

        deadline = start + self._max_wait
        tool_calls: List[ToolCall] = []
        while True:
            run = threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
            status = getattr(run, "status", "")
            if status in ("completed", "failed", "cancelled", "expired"):
                break
            if status == "requires_action":
                tool_calls.extend(self._extract_required_tool_calls(run))
                # We don't execute tools here — ATTEST observes what the agent
                # *wanted* to call. Cancel to end the run cleanly.
                try:
                    threads.runs.cancel(thread_id=thread.id, run_id=run.id)
                except Exception:
                    pass
                break
            if time.perf_counter() > deadline:
                raise AdapterError("OpenAI Assistants run timed out.")
            time.sleep(self._poll)

        content = self._latest_assistant_text(threads, thread.id)
        token_usage = self._extract_usage(run)
        latency_ms = (time.perf_counter() - start) * 1000

        return AgentResponse(
            content=content,
            tool_calls=tool_calls,
            latency_ms=latency_ms,
            token_usage=token_usage,
            raw_response=run,
        )

    async def health_check(self) -> bool:
        try:
            await asyncio.to_thread(
                self._client.beta.assistants.retrieve, self._assistant_id
            )
            return True
        except Exception:
            return False

    async def get_capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(supports_tool_calls=True, supports_multi_turn=True)

    # ------------------------------------------------------------------
    @staticmethod
    def _extract_required_tool_calls(run: Any) -> List[ToolCall]:
        calls: List[ToolCall] = []
        try:
            action = run.required_action
            submit = getattr(action, "submit_tool_outputs", None)
            for tc in getattr(submit, "tool_calls", []) or []:
                fn = getattr(tc, "function", None)
                name = getattr(fn, "name", None)
                args = getattr(fn, "arguments", "{}")
                if name:
                    import json as _json

                    try:
                        parsed = _json.loads(args) if isinstance(args, str) else dict(args)
                    except Exception:
                        parsed = {"raw": args}
                    calls.append(ToolCall(name=str(name), arguments=parsed))
        except Exception:
            pass
        return calls

    @staticmethod
    def _latest_assistant_text(threads: Any, thread_id: str) -> str:
        try:
            msgs = threads.messages.list(thread_id=thread_id, order="desc", limit=10)
            for m in getattr(msgs, "data", []) or []:
                if getattr(m, "role", "") != "assistant":
                    continue
                parts: List[str] = []
                for block in getattr(m, "content", []) or []:
                    text = getattr(block, "text", None)
                    if text is not None:
                        parts.append(getattr(text, "value", "") or "")
                if parts:
                    return "".join(parts)
        except Exception:
            pass
        return ""

    @staticmethod
    def _extract_usage(run: Any) -> Optional[TokenUsage]:
        usage = getattr(run, "usage", None)
        if usage is None:
            return None
        try:
            return TokenUsage(
                input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
            )
        except Exception:
            return None
