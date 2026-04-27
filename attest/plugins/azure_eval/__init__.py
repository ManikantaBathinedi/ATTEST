"""Azure AI Evaluation SDK Plugin for ATTEST.

Wraps Microsoft's azure-ai-evaluation SDK evaluators into ATTEST's
BaseEvaluator interface. Same YAML syntax, same registry, but uses
Azure's production-grade evaluation models.

Install: pip install attest[azure]

Evaluator categories:
    FREE (no LLM cost):
        f1_score, bleu_score         → Run locally, zero API calls
        violence, sexual, self_harm,
        hate_unfairness              → Azure Content Safety (free with Foundry)

    LLM token cost:
        groundedness, azure_relevance,
        coherence, fluency, similarity → Call your Azure OpenAI deployment
        task_adherence, intent_resolution,
        tool_call_accuracy, response_completeness

Usage:
    from attest.plugins.azure_eval import AzureEvalPlugin

    plugin = AzureEvalPlugin(
        model_config={"azure_endpoint": "...", "azure_deployment": "gpt-4o"},
        azure_ai_project="https://...",
    )
    plugin.register_all(registry)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from attest.evaluation.registry import EvaluatorRegistry


class AzureEvalPlugin:
    """Plugin that registers all Azure AI Evaluation SDK evaluators."""

    def __init__(
        self,
        model_config: Optional[Dict[str, str]] = None,
        azure_ai_project: Optional[Any] = None,
    ):
        self.model_config = model_config or {}
        self.azure_ai_project = azure_ai_project
        self._sdk_available = self._check_sdk()

    def _check_sdk(self) -> bool:
        try:
            import azure.ai.evaluation  # noqa: F401
            return True
        except ImportError:
            return False

    @property
    def is_available(self) -> bool:
        return self._sdk_available

    def register_all(self, registry: EvaluatorRegistry) -> int:
        """Register all Azure evaluators into the ATTEST registry.

        Returns the number of evaluators registered.
        """
        if not self._sdk_available:
            return 0

        from attest.plugins.azure_eval.evaluators import (
            AzureGroundednessEvaluator,
            AzureRelevanceEvaluator,
            AzureCoherenceEvaluator,
            AzureFluencyEvaluator,
            AzureSimilarityEvaluator,
            AzureTaskAdherenceEvaluator,
            AzureIntentResolutionEvaluator,
            AzureToolCallAccuracyEvaluator,
            AzureResponseCompletenessEvaluator,
            AzureViolenceEvaluator,
            AzureSexualEvaluator,
            AzureSelfHarmEvaluator,
            AzureHateUnfairnessEvaluator,
            AzureF1ScoreEvaluator,
            AzureBleuScoreEvaluator,
        )

        # Map: registry name → (class, needs_model_config, needs_project)
        evaluators = {
            # Quality (LLM cost)
            "groundedness":          (AzureGroundednessEvaluator, True, False),
            "azure_relevance":       (AzureRelevanceEvaluator, True, False),
            "coherence":             (AzureCoherenceEvaluator, True, False),
            "fluency":               (AzureFluencyEvaluator, True, False),
            "similarity":            (AzureSimilarityEvaluator, True, False),
            # Agent (LLM cost)
            "task_adherence":        (AzureTaskAdherenceEvaluator, True, False),
            "intent_resolution":     (AzureIntentResolutionEvaluator, True, False),
            "tool_call_accuracy":    (AzureToolCallAccuracyEvaluator, True, False),
            "response_completeness": (AzureResponseCompletenessEvaluator, True, False),
            # Safety (FREE with Foundry)
            "violence":              (AzureViolenceEvaluator, False, True),
            "sexual":                (AzureSexualEvaluator, False, True),
            "self_harm":             (AzureSelfHarmEvaluator, False, True),
            "hate_unfairness":       (AzureHateUnfairnessEvaluator, False, True),
            # NLP (100% FREE, local)
            "f1_score":              (AzureF1ScoreEvaluator, False, False),
            "bleu_score":            (AzureBleuScoreEvaluator, False, False),
        }

        count = 0
        for name, (cls, needs_model, needs_project) in evaluators.items():
            # Create a factory that injects the right config
            kwargs = {}
            if needs_model:
                kwargs["model_config"] = self.model_config
            if needs_project:
                kwargs["azure_ai_project"] = self.azure_ai_project

            # Register a wrapper that passes config at creation time
            _cls = cls
            _kwargs = kwargs

            class _Factory:
                """Captures cls and kwargs for deferred creation."""
                def __init__(self, eval_cls, eval_kwargs):
                    self._cls = eval_cls
                    self._kwargs = eval_kwargs

                def __call__(self, **override_kwargs):
                    merged = {**self._kwargs, **override_kwargs}
                    return self._cls(**merged)

            registry.register(name, _Factory(_cls, _kwargs))
            count += 1

        return count

    # Convenience: list what's available
    QUALITY_EVALUATORS = [
        "groundedness", "azure_relevance", "coherence", "fluency", "similarity",
    ]
    AGENT_EVALUATORS = [
        "task_adherence", "intent_resolution", "tool_call_accuracy", "response_completeness",
    ]
    SAFETY_EVALUATORS = [
        "violence", "sexual", "self_harm", "hate_unfairness",
    ]
    NLP_EVALUATORS = [
        "f1_score", "bleu_score",
    ]
    ALL_EVALUATORS = QUALITY_EVALUATORS + AGENT_EVALUATORS + SAFETY_EVALUATORS + NLP_EVALUATORS
