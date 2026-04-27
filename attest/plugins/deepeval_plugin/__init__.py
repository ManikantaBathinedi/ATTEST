"""DeepEval Plugin for ATTEST.

Provides research-backed LLM evaluation metrics from the DeepEval framework.
Uses 'deepeval_' prefix to distinguish from built-in evaluators.

Install: pip install deepeval

Available metrics:
    deepeval_correctness, deepeval_relevancy, deepeval_faithfulness,
    deepeval_hallucination, deepeval_bias, deepeval_toxicity
"""

from attest.plugins.deepeval_plugin.evaluators import (
    DEEPEVAL_EVALUATORS,
    DeepEvalBiasEvaluator,
    DeepEvalCorrectnessEvaluator,
    DeepEvalFaithfulnessEvaluator,
    DeepEvalGEvalEvaluator,
    DeepEvalHallucinationEvaluator,
    DeepEvalRelevancyEvaluator,
    DeepEvalToxicityEvaluator,
    register_deepeval_evaluators,
)

__all__ = [
    "DEEPEVAL_EVALUATORS",
    "register_deepeval_evaluators",
    "DeepEvalCorrectnessEvaluator",
    "DeepEvalRelevancyEvaluator",
    "DeepEvalFaithfulnessEvaluator",
    "DeepEvalHallucinationEvaluator",
    "DeepEvalBiasEvaluator",
    "DeepEvalToxicityEvaluator",
    "DeepEvalGEvalEvaluator",
]
