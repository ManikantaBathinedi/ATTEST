"""Base evaluator interface — the plugin contract.

Every evaluator (built-in, Azure SDK, DeepEval, Ragas, or custom) must
implement this interface. This is the boundary between ATTEST core and
any evaluation backend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from attest.core.models import Message, ToolCall


class EvaluationInput(BaseModel):
    """Standard input for all evaluators."""

    query: str  # User question/request
    response: str  # Agent response
    context: Optional[str] = None  # Retrieved context (for RAG)
    expected: Optional[str] = None  # Expected/ground truth answer
    conversation: List[Message] = Field(default_factory=list)
    tool_calls: List[ToolCall] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    """Standard output from all evaluators."""

    name: str  # Metric name
    score: float  # Score (0.0 - 1.0 normalized)
    passed: bool  # Above threshold?
    threshold: float  # Threshold used
    reason: Optional[str] = None  # Explanation
    raw_score: Optional[Any] = None  # Original score before normalization
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BaseEvaluator(ABC):
    """Interface that all evaluators must implement.

    This is the plugin contract. Any evaluation backend (built-in, Azure,
    DeepEval, Ragas, custom) wraps its metrics in an evaluator that
    implements this interface.
    """

    def __init__(self, threshold: float = 0.7):
        self._threshold = threshold

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this evaluator (e.g. 'correctness', 'groundedness')."""
        ...

    @abstractmethod
    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        """Run evaluation and return result.

        Args:
            input: Standardized evaluation input with query, response, context, etc.

        Returns:
            EvaluationResult with score, passed/failed, and optional explanation.
        """
        ...

    @property
    def threshold(self) -> float:
        """Score threshold for pass/fail determination."""
        return self._threshold

    @threshold.setter
    def threshold(self, value: float) -> None:
        self._threshold = value

    @property
    def requires_llm(self) -> bool:
        """Whether this evaluator needs an LLM call. Override to return False for deterministic."""
        return True

    @property
    def requires_azure(self) -> bool:
        """Whether this evaluator needs Azure credentials. Override for Azure-only evaluators."""
        return False

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}', threshold={self.threshold})"
