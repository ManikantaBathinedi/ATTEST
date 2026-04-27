"""Multi-turn conversation runner.

Handles conversation tests where multiple messages are sent in sequence.
Each turn can have its own assertions, and the full conversation history
is maintained between turns.

Usage in YAML:
    tests:
      - name: trip_flow
        type: conversation
        script:
          - user: "I want to visit Japan"
            expect:
              response_not_empty: true
          - user: "What about food?"
            expect:
              response_contains_any: ["sushi", "ramen"]

How it works:
    1. Send first user message → get response → check assertions
    2. Send second message (with full history) → get response → check
    3. Continue until script is done
    4. Return overall pass/fail + per-turn results
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from attest.adapters.base import BaseAgentAdapter
from attest.core.assertions import resolve_assertions, run_assertions
from attest.core.models import AgentResponse, AssertionResult, Message


@dataclass
class TurnResult:
    """Result of a single conversation turn."""

    turn_number: int
    user_message: str
    agent_response: str
    assertions: List[AssertionResult] = field(default_factory=list)
    passed: bool = True
    latency_ms: float = 0.0


@dataclass
class ConversationResult:
    """Result of a full multi-turn conversation test."""

    name: str
    turns: List[TurnResult] = field(default_factory=list)
    messages: List[Message] = field(default_factory=list)
    total_latency_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return all(t.passed for t in self.turns)

    @property
    def failed_turns(self) -> List[TurnResult]:
        return [t for t in self.turns if not t.passed]


async def run_conversation(
    adapter: BaseAgentAdapter,
    script: List[Dict[str, Any]],
    name: str = "conversation",
) -> ConversationResult:
    """Run a multi-turn conversation script against an agent.

    Args:
        adapter: The agent adapter to send messages through.
        script: List of turns, each with 'user' (message) and optional 'expect' (assertions).
        name: Test name for reporting.

    Returns:
        ConversationResult with per-turn results and overall pass/fail.
    """
    result = ConversationResult(name=name)
    conversation_history: List[Message] = []

    for turn_num, turn in enumerate(script, 1):
        user_message = turn.get("user", "")
        expectations = turn.get("expect", {})

        # Send the message with full conversation history
        response = await adapter.send_message(
            message=user_message,
            conversation_history=conversation_history,
        )

        # Record the conversation
        user_msg = Message(role="user", content=user_message)
        agent_msg = Message(role="assistant", content=response.content)
        conversation_history.append(user_msg)
        conversation_history.append(agent_msg)
        result.messages.append(user_msg)
        result.messages.append(agent_msg)

        # Run assertions for this turn
        turn_result = TurnResult(
            turn_number=turn_num,
            user_message=user_message,
            agent_response=response.content,
            latency_ms=response.latency_ms,
        )

        if expectations:
            # Convert expect dict to assertion list format
            assertion_list = []
            for key, value in expectations.items():
                assertion_list.append({key: value})

            assertion_fns = resolve_assertions(assertion_list)
            turn_result.assertions = run_assertions(response, assertion_fns)
            turn_result.passed = all(a.passed for a in turn_result.assertions)

        result.turns.append(turn_result)
        result.total_latency_ms += response.latency_ms

    return result
