"""User Simulator — LLM-powered synthetic user for multi-turn agent testing.

Instead of hand-writing every conversation turn, describe a persona and goal,
and the simulator runs a realistic back-and-forth with the agent under test.

How it works:
    1. You define: persona, goal, max_turns, and optional stop_conditions
    2. The simulator generates the first user message using the LLM
    3. That message is sent to the agent via the adapter
    4. The agent's response is fed back to the simulator LLM
    5. The simulator decides: continue with next message, or stop
    6. Repeat until max_turns or a stop condition is met
    7. The full conversation is returned for evaluation

Usage in YAML:
    tests:
      - name: frustrated_customer_refund
        type: simulation
        persona: "Frustrated customer who received a damaged laptop. Gets increasingly impatient."
        goal: "Get a full refund and return label."
        max_turns: 8
        evaluators: [relevancy, completeness, tone]

Usage in Python:
    from attest.simulation import UserSimulator

    sim = UserSimulator(model="azure/gpt-4.1-mini")
    result = await sim.run(
        adapter=agent_adapter,
        persona="Frustrated customer wanting a refund",
        goal="Get a full refund",
        max_turns=8,
    )
    print(result.conversation)  # Full message history
    print(result.summary)       # LLM-generated conversation summary
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from attest.adapters.base import BaseAgentAdapter
from attest.core.models import AgentResponse, Message


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


@dataclass
class SimulationTurn:
    """A single turn in the simulated conversation."""

    turn_number: int
    user_message: str
    agent_response: str
    latency_ms: float = 0.0
    user_intent: str = ""  # What the simulator was trying to achieve this turn


@dataclass
class SimulationResult:
    """Complete result of a user simulation run."""

    name: str
    persona: str
    goal: str
    turns: List[SimulationTurn] = field(default_factory=list)
    messages: List[Message] = field(default_factory=list)
    total_latency_ms: float = 0.0
    stop_reason: str = ""  # "max_turns", "goal_achieved", "conversation_ended"
    goal_achieved: bool = False
    summary: str = ""  # LLM-generated summary of how the conversation went

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    @property
    def agent_responses(self) -> List[str]:
        return [t.agent_response for t in self.turns]


# ---------------------------------------------------------------------------
# System prompts for the simulator LLM
# ---------------------------------------------------------------------------

_SIMULATOR_SYSTEM_PROMPT = """You are simulating a user interacting with an AI agent.

PERSONA: {persona}

GOAL: {goal}

RULES:
- Stay in character as described in the persona
- Work toward your goal naturally over multiple messages
- Be realistic — real users don't send perfect requests. They may be vague, 
  change their mind, ask follow-up questions, or get frustrated
- If the agent asks for clarification, provide it (sometimes with extra details, 
  sometimes reluctantly, like a real person)
- If the agent solves your problem, acknowledge it naturally
- Do NOT break character or mention that you are a simulation

RESPOND WITH ONLY your next message as the user. Nothing else."""

_FIRST_MESSAGE_PROMPT = """Based on your persona and goal, write your FIRST message to the agent.
This should be a natural opening — how a real person with this persona would 
start the conversation. Keep it realistic and concise.

RESPOND WITH ONLY the user's message. Nothing else."""

_NEXT_MESSAGE_PROMPT = """Here is the conversation so far:

{conversation_history}

The agent just responded. Based on your persona and goal, write your NEXT message.

Consider:
- Has your goal been achieved? If yes, respond naturally (thank them, confirm, etc.)
- Do you need to provide more information or ask follow-up questions?
- Would your persona push back, escalate, or change direction?

If the conversation has reached a natural conclusion (goal achieved or clearly 
impossible), respond with exactly: [CONVERSATION_ENDED]

Otherwise, respond with ONLY your next message as the user."""

_SUMMARY_PROMPT = """Analyze this conversation between a user and an AI agent.

PERSONA: {persona}
GOAL: {goal}

CONVERSATION:
{conversation}

Provide a brief assessment in this JSON format:
{{
    "goal_achieved": true/false,
    "summary": "2-3 sentence summary of what happened",
    "strengths": ["things the agent did well"],
    "weaknesses": ["things the agent could improve"]
}}

RESPOND WITH ONLY THE JSON. No markdown fences."""


# ---------------------------------------------------------------------------
# UserSimulator class
# ---------------------------------------------------------------------------


class UserSimulator:
    """Simulates a user persona interacting with an agent under test.

    Uses an LLM to generate realistic user messages based on a persona
    and goal. The simulated user converses with the agent for multiple
    turns, producing a full conversation for evaluation.
    """

    def __init__(
        self,
        model: str = "azure/gpt-4.1-mini",
        temperature: float = 0.7,
    ):
        self.model = model
        self.temperature = temperature

    async def run(
        self,
        adapter: BaseAgentAdapter,
        persona: str,
        goal: str,
        max_turns: int = 8,
        name: str = "simulation",
        first_message: Optional[str] = None,
    ) -> SimulationResult:
        """Run a simulated conversation.

        Args:
            adapter: Agent adapter to talk to.
            persona: Description of the simulated user's personality/situation.
            goal: What the simulated user is trying to accomplish.
            max_turns: Maximum conversation turns before stopping.
            name: Test name for reporting.
            first_message: Optional fixed first message (skips LLM for turn 1).

        Returns:
            SimulationResult with the full conversation and assessment.
        """
        result = SimulationResult(name=name, persona=persona, goal=goal)
        conversation_history: List[Message] = []
        start_time = time.perf_counter()

        system_prompt = _SIMULATOR_SYSTEM_PROMPT.format(
            persona=persona,
            goal=goal,
        )

        for turn_num in range(1, max_turns + 1):
            # Step 1: Generate user message
            if turn_num == 1 and first_message:
                user_message = first_message
            elif turn_num == 1:
                user_message = await self._generate_message(
                    system_prompt=system_prompt,
                    user_prompt=_FIRST_MESSAGE_PROMPT,
                )
            else:
                history_text = self._format_history(conversation_history)
                user_prompt = _NEXT_MESSAGE_PROMPT.format(
                    conversation_history=history_text,
                )
                user_message = await self._generate_message(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )

            # Check if simulator decided conversation is over
            if "[CONVERSATION_ENDED]" in user_message:
                result.stop_reason = "conversation_ended"
                break

            # Step 2: Send to agent
            user_msg = Message(role="user", content=user_message)
            conversation_history.append(user_msg)
            result.messages.append(user_msg)

            try:
                response = await adapter.send_message(
                    message=user_message,
                    conversation_history=conversation_history[:-1],  # History before this message
                )
            except Exception as e:
                # Agent error — record and stop
                agent_msg = Message(role="assistant", content=f"[ERROR: {e}]")
                conversation_history.append(agent_msg)
                result.messages.append(agent_msg)
                result.stop_reason = f"agent_error: {e}"
                break

            agent_msg = Message(role="assistant", content=response.content)
            conversation_history.append(agent_msg)
            result.messages.append(agent_msg)

            # Record turn
            turn = SimulationTurn(
                turn_number=turn_num,
                user_message=user_message,
                agent_response=response.content,
                latency_ms=response.latency_ms,
            )
            result.turns.append(turn)
            result.total_latency_ms += response.latency_ms

        else:
            # Loop completed without break — hit max turns
            result.stop_reason = "max_turns"

        # Step 3: Generate summary and goal assessment
        if result.turns:
            summary_data = await self._generate_summary(
                persona=persona,
                goal=goal,
                conversation=conversation_history,
            )
            result.goal_achieved = summary_data.get("goal_achieved", False)
            result.summary = summary_data.get("summary", "")
            if result.stop_reason == "conversation_ended":
                result.goal_achieved = True  # Natural ending usually means success

        result.total_latency_ms = (time.perf_counter() - start_time) * 1000
        return result

    # ------------------------------------------------------------------
    # LLM call helpers
    # ------------------------------------------------------------------

    async def _generate_message(
        self, system_prompt: str, user_prompt: str
    ) -> str:
        """Call LLM to generate the simulated user's next message."""
        client = self._get_client()
        deploy_name = self._get_deploy_name()

        response = client.chat.completions.create(
            model=deploy_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.temperature,
            max_tokens=512,
        )
        return response.choices[0].message.content.strip()

    async def _generate_summary(
        self,
        persona: str,
        goal: str,
        conversation: List[Message],
    ) -> Dict[str, Any]:
        """Generate a summary and goal-achievement assessment."""
        conv_text = self._format_history(conversation)
        prompt = _SUMMARY_PROMPT.format(
            persona=persona,
            goal=goal,
            conversation=conv_text,
        )

        client = self._get_client()
        deploy_name = self._get_deploy_name()

        response = client.chat.completions.create(
            model=deploy_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=1024,
        )
        raw = response.choices[0].message.content.strip()

        # Parse JSON from response
        try:
            # Handle markdown fences
            cleaned = raw
            if "```" in cleaned:
                cleaned = re.sub(r"```(?:json)?\s*", "", cleaned).strip()
            json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, AttributeError):
            pass

        return {"goal_achieved": False, "summary": raw}

    def _get_client(self):
        """Create Azure OpenAI client with keyless auth support."""
        from attest.utils.azure_client import get_azure_openai_client
        return get_azure_openai_client()

    def _get_deploy_name(self) -> str:
        """Extract deployment name from model string."""
        from attest.utils.azure_client import get_deployment_name
        return get_deployment_name(self.model)

    @staticmethod
    def _format_history(messages: List[Message]) -> str:
        """Format conversation history as readable text."""
        lines = []
        for msg in messages:
            role = "User" if msg.role == "user" else "Agent"
            lines.append(f"{role}: {msg.content}")
        return "\n\n".join(lines)
