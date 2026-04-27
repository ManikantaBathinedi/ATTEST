"""Core data models for the ATTEST framework.

These models represent the fundamental data structures used throughout the system:
- Messages and tool calls (agent interaction)
- Test cases (what to test)
- Agent responses (what the agent returned)
- Evaluation scores and test results (how it was judged)
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Status(str, enum.Enum):
    """Test result status."""

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


class ScenarioType(str, enum.Enum):
    """Type of test scenario."""

    SINGLE_TURN = "single_turn"
    MULTI_TURN = "multi_turn"
    CONVERSATION = "conversation"
    PROTOCOL = "protocol"
    SECURITY = "security"


# ---------------------------------------------------------------------------
# Agent Interaction Models
# ---------------------------------------------------------------------------


class Message(BaseModel):
    """A single message in a conversation."""

    role: str  # "user", "assistant", "system", "tool"
    content: str
    name: Optional[str] = None  # tool name or agent name
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    """A tool/function call made by the agent."""

    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[str] = None
    error: Optional[str] = None


class TokenUsage(BaseModel):
    """Token usage for a single agent interaction."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class Attachment(BaseModel):
    """A file or data attachment sent with input."""

    filename: str
    content_type: str  # MIME type
    data: Optional[str] = None  # base64 encoded or URL
    url: Optional[str] = None


# ---------------------------------------------------------------------------
# Agent Response
# ---------------------------------------------------------------------------


class AgentResponse(BaseModel):
    """Standardized response from any agent adapter."""

    content: str  # Text response
    tool_calls: List[ToolCall] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0
    token_usage: Optional[TokenUsage] = None
    raw_response: Optional[Any] = None  # Original response object (excluded from serialization)

    model_config = {"arbitrary_types_allowed": True}


# ---------------------------------------------------------------------------
# Expected Tool Call (for assertions)
# ---------------------------------------------------------------------------


class ExpectedToolCall(BaseModel):
    """Defines an expected tool call for test assertions."""

    name: str
    args: Dict[str, Any] = Field(default_factory=dict)
    partial_match: bool = True  # Match a subset of args (default) vs exact match


# ---------------------------------------------------------------------------
# Test Case
# ---------------------------------------------------------------------------


class TestCase(BaseModel):
    """The universal test case model.

    Every test — whether defined in YAML, Python, dataset file, or the UI —
    is normalized into this model before execution.
    """

    # Identity
    name: str
    suite: str = "default"
    tags: List[str] = Field(default_factory=list)
    description: Optional[str] = None

    # Input
    input: str  # User message to send
    input_attachments: List[Attachment] = Field(default_factory=list)

    # Expected (all optional — more fields = more precise evaluation)
    expected_output: Optional[str] = None
    expected_tool_calls: List[ExpectedToolCall] = Field(default_factory=list)
    expected_intent: Optional[str] = None

    # Context for evaluation
    context: Optional[str] = None  # Retrieved docs / grounding data
    ground_truth: Optional[str] = None  # Authoritative correct answer
    system_prompt: Optional[str] = None  # Agent's system prompt (if known)

    # Conversation (for multi-turn)
    conversation_history: List[Message] = Field(default_factory=list)
    conversation_script: List[Dict[str, Any]] = Field(default_factory=list)  # Multi-turn script
    persona: Optional[str] = None  # User simulator persona
    max_turns: Optional[int] = None
    type: str = "single_turn"  # single_turn or conversation

    # What to check
    assertions: List[Dict[str, Any]] = Field(default_factory=list)
    evaluators: List[Any] = Field(default_factory=list)  # str or dict, e.g. ["correctness", {"relevancy": 0.8}]
    thresholds: Dict[str, float] = Field(default_factory=dict)

    # Execution
    agent: str = "default"
    timeout: int = 30
    retries: int = 0


# ---------------------------------------------------------------------------
# Evaluation Score
# ---------------------------------------------------------------------------


class EvalScore(BaseModel):
    """Result from a single evaluator."""

    name: str
    score: float  # Normalized 0.0 - 1.0
    passed: bool
    threshold: float
    reason: Optional[str] = None  # LLM judge explanation
    backend: str = "builtin"  # "builtin", "azure", "deepeval", etc.
    raw_score: Optional[Any] = None  # Original score before normalization
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Assertion Result
# ---------------------------------------------------------------------------


class AssertionResult(BaseModel):
    """Result from a single deterministic assertion."""

    name: str  # e.g. "tool_called:lookup_order"
    passed: bool
    message: str = ""  # Explanation on failure
    expected: Optional[Any] = None
    actual: Optional[Any] = None


# ---------------------------------------------------------------------------
# Test Result
# ---------------------------------------------------------------------------


class TestResult(BaseModel):
    """Complete result of running a single test case."""

    # Identity
    scenario: str
    suite: str = "default"
    status: Status = Status.PASSED

    # Agent interaction
    messages: List[Message] = Field(default_factory=list)
    tool_calls: List[ToolCall] = Field(default_factory=list)

    # Evaluation
    scores: Dict[str, EvalScore] = Field(default_factory=dict)
    assertions: List[AssertionResult] = Field(default_factory=list)

    # Performance
    latency_ms: float = 0.0
    token_usage: Optional[TokenUsage] = None
    estimated_cost: float = 0.0

    # Metadata
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    duration_ms: float = 0.0
    error: Optional[str] = None
    agent: str = "default"
    tags: List[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == Status.PASSED

    @property
    def all_assertions_passed(self) -> bool:
        return all(a.passed for a in self.assertions)

    @property
    def all_evaluators_passed(self) -> bool:
        return all(s.passed for s in self.scores.values())


# ---------------------------------------------------------------------------
# Run Summary
# ---------------------------------------------------------------------------


class RunSummary(BaseModel):
    """Summary of an entire test run (multiple test cases)."""

    run_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    duration_seconds: float = 0.0

    # Counts
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0

    # Scores
    overall_score: float = 0.0  # Average across all tests
    total_cost: float = 0.0

    # Individual results
    results: List[TestResult] = Field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total > 0 else 0.0

    def add_result(self, result: TestResult) -> None:
        """Add a test result and update summary counts."""
        self.results.append(result)
        self.total += 1
        if result.status == Status.PASSED:
            self.passed += 1
        elif result.status == Status.FAILED:
            self.failed += 1
        elif result.status == Status.ERROR:
            self.errors += 1
        elif result.status == Status.SKIPPED:
            self.skipped += 1
        self.total_cost += result.estimated_cost

        # Recalculate overall score
        scores = [
            sum(s.score for s in r.scores.values()) / len(r.scores)
            for r in self.results
            if r.scores
        ]
        self.overall_score = sum(scores) / len(scores) if scores else 0.0
