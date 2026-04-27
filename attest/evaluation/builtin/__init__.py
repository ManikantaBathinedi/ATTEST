"""Built-in evaluators — work with any LLM via LiteLLM, zero extra deps."""

from attest.evaluation.builtin.correctness import CorrectnessEvaluator
from attest.evaluation.builtin.relevancy import RelevancyEvaluator
from attest.evaluation.builtin.hallucination import HallucinationEvaluator
from attest.evaluation.builtin.completeness import CompletenessEvaluator
from attest.evaluation.builtin.tone import ToneEvaluator

__all__ = [
    "CorrectnessEvaluator",
    "RelevancyEvaluator",
    "HallucinationEvaluator",
    "CompletenessEvaluator",
    "ToneEvaluator",
]
