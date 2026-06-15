"""RAGAS Plugin for ATTEST.

Provides RAG-focused evaluation metrics from the RAGAS framework.
Uses 'ragas_' prefix to distinguish from built-in evaluators.

Install: pip install ragas langchain-openai

Available metrics:
    ragas_faithfulness, ragas_answer_relevancy,
    ragas_context_precision, ragas_context_recall
"""

from attest.plugins.ragas_plugin.evaluators import (
    RAGAS_EVALUATORS,
    RagasAnswerRelevancyEvaluator,
    RagasContextPrecisionEvaluator,
    RagasContextRecallEvaluator,
    RagasFaithfulnessEvaluator,
    register_ragas_evaluators,
)

__all__ = [
    "RAGAS_EVALUATORS",
    "register_ragas_evaluators",
    "RagasFaithfulnessEvaluator",
    "RagasAnswerRelevancyEvaluator",
    "RagasContextPrecisionEvaluator",
    "RagasContextRecallEvaluator",
]
