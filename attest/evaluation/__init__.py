"""Evaluation engine — evaluator interface, registry, built-in judges, and LLM infrastructure."""

from attest.evaluation.interface import BaseEvaluator, EvaluationInput, EvaluationResult
from attest.evaluation.registry import EvaluatorRegistry
from attest.evaluation.llm_judge import LLMJudge

__all__ = [
    "BaseEvaluator",
    "EvaluationInput",
    "EvaluationResult",
    "EvaluatorRegistry",
    "LLMJudge",
]
