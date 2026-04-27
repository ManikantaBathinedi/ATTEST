"""Azure AI Evaluation SDK evaluator wrappers.

Each class wraps one Azure evaluator into ATTEST's BaseEvaluator interface.
This means Azure evaluators work with the same YAML syntax and registry
as built-in evaluators.

The wrappers handle:
    1. Creating the Azure evaluator with the right config
    2. Mapping ATTEST's EvaluationInput to Azure's expected parameters
    3. Mapping Azure's result back to ATTEST's EvaluationResult
    4. Normalizing scores to 0.0-1.0

Categories:
    Quality (AI-assisted):  Groundedness, Relevance, Coherence, Fluency, Similarity
    Agent-specific:         TaskAdherence, IntentResolution, ToolCallAccuracy,
                           ResponseCompleteness
    Safety:                 Violence, Sexual, SelfHarm, HateUnfairness,
                           IndirectAttack, ProtectedMaterial
    NLP (local, free):      F1Score, BleuScore, RougeScore, MeteorScore
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from attest.evaluation.interface import BaseEvaluator, EvaluationInput, EvaluationResult


# ---------------------------------------------------------------------------
# Base class for all Azure evaluator wrappers
# ---------------------------------------------------------------------------


class AzureEvaluatorBase(BaseEvaluator):
    """Base class for Azure AI Evaluation SDK evaluator wrappers.

    Handles common logic:
    - Lazy import of azure SDK (only when actually called)
    - Score normalization (Azure scores are 1-5, we need 0.0-1.0)
    - Error handling
    """

    def __init__(
        self,
        threshold: float = 0.7,
        model_config: Optional[Dict[str, str]] = None,
        azure_ai_project: Optional[Any] = None,
        **kwargs,
    ):
        super().__init__(threshold=threshold)
        self._model_config = model_config or self._build_model_config()
        self._azure_ai_project = azure_ai_project
        self._azure_evaluator = None  # Lazy init

    @staticmethod
    def _build_model_config() -> Dict[str, str]:
        """Auto-build model_config from env vars with Entra ID fallback.

        Priority:
        1. API key (AZURE_API_KEY_OPENAI or AZURE_API_KEY)
        2. Azure Entra ID (DefaultAzureCredential, no keys needed)
        """
        import os

        endpoint = os.environ.get("AZURE_API_BASE", "")
        api_key = os.environ.get("AZURE_API_KEY_OPENAI") or os.environ.get("AZURE_API_KEY", "")
        api_version = os.environ.get("AZURE_API_VERSION", "2025-04-01-preview")

        if not endpoint:
            return {}

        config: Dict[str, str] = {
            "azure_endpoint": endpoint,
            "api_version": api_version,
        }

        if api_key:
            config["api_key"] = api_key
        else:
            # Try Entra ID (keyless)
            try:
                from azure.identity import DefaultAzureCredential, get_bearer_token_provider
                credential = DefaultAzureCredential()
                token_provider = get_bearer_token_provider(
                    credential, "https://cognitiveservices.azure.com/.default"
                )
                config["azure_ad_token_provider"] = token_provider
            except Exception:
                pass  # Will fail at eval time with clear error

        return config

    @property
    def requires_azure(self) -> bool:
        return True

    def _normalize_score(self, raw_score: Any, scale: int = 5) -> float:
        """Normalize Azure score to 0.0-1.0.

        Azure quality evaluators return 1-5 scores.
        Azure safety evaluators return severity 0-7 (higher = worse).
        """
        try:
            score = float(raw_score)
            if scale == 5:
                return max(0.0, min(score / 5.0, 1.0))
            elif scale == 7:
                # Safety: 0 = safe, 7 = very unsafe → invert
                return max(0.0, 1.0 - (score / 7.0))
            return max(0.0, min(score, 1.0))
        except (TypeError, ValueError):
            return 0.0

    def _extract_score(self, result: dict, metric_name: str) -> tuple:
        """Extract score and reason from Azure evaluator result dict.

        Azure returns dicts like:
            {"groundedness": 4.0, "groundedness_reason": "Well grounded..."}
            {"gpt_groundedness": 4.0}
        """
        # Try various key patterns Azure uses
        score = None
        reason = ""

        for key_pattern in [metric_name, f"gpt_{metric_name}", f"{metric_name}_score"]:
            if key_pattern in result:
                score = result[key_pattern]
                break

        for reason_key in [f"{metric_name}_reason", f"{metric_name}_result", "reason"]:
            if reason_key in result:
                reason = str(result[reason_key])
                break

        return score, reason


# ---------------------------------------------------------------------------
# Quality evaluators (AI-assisted, costs LLM tokens)
# ---------------------------------------------------------------------------


class AzureGroundednessEvaluator(AzureEvaluatorBase):
    """Checks if the response is grounded in the provided context.

    Essential for RAG — makes sure the agent doesn't make up info
    beyond what's in the retrieved documents.
    """

    @property
    def name(self) -> str:
        return "groundedness"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from azure.ai.evaluation import GroundednessEvaluator

        if self._azure_evaluator is None:
            self._azure_evaluator = GroundednessEvaluator(self._model_config)

        result = self._azure_evaluator(
            query=input.query,
            response=input.response,
            context=input.context or "",
        )

        raw_score, reason = self._extract_score(result, "groundedness")
        score = self._normalize_score(raw_score)

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=reason,
            raw_score=raw_score,
            metadata={"backend": "azure", "raw_result": result},
        )


class AzureRelevanceEvaluator(AzureEvaluatorBase):
    """Checks if the response is relevant to the query."""

    @property
    def name(self) -> str:
        return "azure_relevance"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from azure.ai.evaluation import RelevanceEvaluator

        if self._azure_evaluator is None:
            self._azure_evaluator = RelevanceEvaluator(self._model_config)

        result = self._azure_evaluator(
            query=input.query,
            response=input.response,
        )

        raw_score, reason = self._extract_score(result, "relevance")
        score = self._normalize_score(raw_score)

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=reason,
            raw_score=raw_score,
            metadata={"backend": "azure"},
        )


class AzureCoherenceEvaluator(AzureEvaluatorBase):
    """Checks if the response is logically consistent and well-structured."""

    @property
    def name(self) -> str:
        return "coherence"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from azure.ai.evaluation import CoherenceEvaluator

        if self._azure_evaluator is None:
            self._azure_evaluator = CoherenceEvaluator(self._model_config)

        result = self._azure_evaluator(
            query=input.query,
            response=input.response,
        )

        raw_score, reason = self._extract_score(result, "coherence")
        score = self._normalize_score(raw_score)

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=reason,
            raw_score=raw_score,
            metadata={"backend": "azure"},
        )


class AzureFluencyEvaluator(AzureEvaluatorBase):
    """Checks language quality — grammar, readability, naturalness."""

    @property
    def name(self) -> str:
        return "fluency"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from azure.ai.evaluation import FluencyEvaluator

        if self._azure_evaluator is None:
            self._azure_evaluator = FluencyEvaluator(self._model_config)

        result = self._azure_evaluator(response=input.response)

        raw_score, reason = self._extract_score(result, "fluency")
        score = self._normalize_score(raw_score)

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=reason,
            raw_score=raw_score,
            metadata={"backend": "azure"},
        )


class AzureSimilarityEvaluator(AzureEvaluatorBase):
    """Checks semantic similarity between response and ground truth."""

    @property
    def name(self) -> str:
        return "similarity"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from azure.ai.evaluation import SimilarityEvaluator

        if self._azure_evaluator is None:
            self._azure_evaluator = SimilarityEvaluator(self._model_config)

        result = self._azure_evaluator(
            query=input.query,
            response=input.response,
            ground_truth=input.expected or "",
        )

        raw_score, reason = self._extract_score(result, "similarity")
        score = self._normalize_score(raw_score)

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=reason,
            raw_score=raw_score,
            metadata={"backend": "azure"},
        )


# ---------------------------------------------------------------------------
# Agent-specific evaluators
# ---------------------------------------------------------------------------


class AzureTaskAdherenceEvaluator(AzureEvaluatorBase):
    """Checks if the agent followed its instructions and completed the task."""

    @property
    def name(self) -> str:
        return "task_adherence"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from azure.ai.evaluation import TaskAdherenceEvaluator

        if self._azure_evaluator is None:
            self._azure_evaluator = TaskAdherenceEvaluator(self._model_config)

        result = self._azure_evaluator(
            query=input.query,
            response=input.response,
        )

        raw_score, reason = self._extract_score(result, "task_adherence")
        score = self._normalize_score(raw_score)

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=reason,
            raw_score=raw_score,
            metadata={"backend": "azure"},
        )


class AzureIntentResolutionEvaluator(AzureEvaluatorBase):
    """Checks if the agent correctly understood and resolved the user's intent."""

    @property
    def name(self) -> str:
        return "intent_resolution"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from azure.ai.evaluation import IntentResolutionEvaluator

        if self._azure_evaluator is None:
            self._azure_evaluator = IntentResolutionEvaluator(self._model_config)

        result = self._azure_evaluator(
            query=input.query,
            response=input.response,
        )

        raw_score, reason = self._extract_score(result, "intent_resolution")
        score = self._normalize_score(raw_score)

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=reason,
            raw_score=raw_score,
            metadata={"backend": "azure"},
        )


class AzureToolCallAccuracyEvaluator(AzureEvaluatorBase):
    """Checks if the agent called the right tools with correct parameters."""

    @property
    def name(self) -> str:
        return "tool_call_accuracy"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from azure.ai.evaluation import ToolCallAccuracyEvaluator

        if self._azure_evaluator is None:
            self._azure_evaluator = ToolCallAccuracyEvaluator(self._model_config)

        result = self._azure_evaluator(
            query=input.query,
            response=input.response,
        )

        raw_score, reason = self._extract_score(result, "tool_call_accuracy")
        score = self._normalize_score(raw_score)

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=reason,
            raw_score=raw_score,
            metadata={"backend": "azure"},
        )


class AzureResponseCompletenessEvaluator(AzureEvaluatorBase):
    """Checks if the response fully addresses the query."""

    @property
    def name(self) -> str:
        return "response_completeness"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from azure.ai.evaluation import ResponseCompletenessEvaluator

        if self._azure_evaluator is None:
            self._azure_evaluator = ResponseCompletenessEvaluator(self._model_config)

        result = self._azure_evaluator(
            query=input.query,
            response=input.response,
        )

        raw_score, reason = self._extract_score(result, "response_completeness")
        score = self._normalize_score(raw_score)

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=reason,
            raw_score=raw_score,
            metadata={"backend": "azure"},
        )


# ---------------------------------------------------------------------------
# Safety evaluators (FREE with Foundry project)
# ---------------------------------------------------------------------------


class AzureSafetyEvaluatorBase(AzureEvaluatorBase):
    """Base for Azure safety evaluators.

    Safety evaluators score severity 0-7 (lower = safer).
    We invert to 0.0-1.0 where 1.0 = completely safe.
    """

    def _normalize_safety_score(self, raw_score: Any) -> float:
        return self._normalize_score(raw_score, scale=7)


class AzureViolenceEvaluator(AzureSafetyEvaluatorBase):
    """Detects violent content in the response. FREE with Foundry project."""

    @property
    def name(self) -> str:
        return "violence"

    @property
    def requires_llm(self) -> bool:
        return False  # Uses Azure Content Safety, not LLM tokens

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from azure.ai.evaluation import ViolenceEvaluator

        if self._azure_evaluator is None:
            self._azure_evaluator = ViolenceEvaluator(
                azure_ai_project=self._azure_ai_project,
            )

        result = self._azure_evaluator(
            query=input.query,
            response=input.response,
        )

        raw_score, reason = self._extract_score(result, "violence")
        score = self._normalize_safety_score(raw_score)

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=reason or result.get("violence_result", ""),
            raw_score=raw_score,
            metadata={"backend": "azure_safety"},
        )


class AzureSexualEvaluator(AzureSafetyEvaluatorBase):
    """Detects sexual content. FREE with Foundry project."""

    @property
    def name(self) -> str:
        return "sexual"

    @property
    def requires_llm(self) -> bool:
        return False

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from azure.ai.evaluation import SexualEvaluator

        if self._azure_evaluator is None:
            self._azure_evaluator = SexualEvaluator(
                azure_ai_project=self._azure_ai_project,
            )

        result = self._azure_evaluator(
            query=input.query,
            response=input.response,
        )

        raw_score, reason = self._extract_score(result, "sexual")
        score = self._normalize_safety_score(raw_score)

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=reason or result.get("sexual_result", ""),
            raw_score=raw_score,
            metadata={"backend": "azure_safety"},
        )


class AzureSelfHarmEvaluator(AzureSafetyEvaluatorBase):
    """Detects self-harm content. FREE with Foundry project."""

    @property
    def name(self) -> str:
        return "self_harm"

    @property
    def requires_llm(self) -> bool:
        return False

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from azure.ai.evaluation import SelfHarmEvaluator

        if self._azure_evaluator is None:
            self._azure_evaluator = SelfHarmEvaluator(
                azure_ai_project=self._azure_ai_project,
            )

        result = self._azure_evaluator(
            query=input.query,
            response=input.response,
        )

        raw_score, reason = self._extract_score(result, "self_harm")
        score = self._normalize_safety_score(raw_score)

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=reason or result.get("self_harm_result", ""),
            raw_score=raw_score,
            metadata={"backend": "azure_safety"},
        )


class AzureHateUnfairnessEvaluator(AzureSafetyEvaluatorBase):
    """Detects hate speech and unfairness. FREE with Foundry project."""

    @property
    def name(self) -> str:
        return "hate_unfairness"

    @property
    def requires_llm(self) -> bool:
        return False

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from azure.ai.evaluation import HateUnfairnessEvaluator

        if self._azure_evaluator is None:
            self._azure_evaluator = HateUnfairnessEvaluator(
                azure_ai_project=self._azure_ai_project,
            )

        result = self._azure_evaluator(
            query=input.query,
            response=input.response,
        )

        raw_score, reason = self._extract_score(result, "hate_unfairness")
        score = self._normalize_safety_score(raw_score)

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=reason or result.get("hate_unfairness_result", ""),
            raw_score=raw_score,
            metadata={"backend": "azure_safety"},
        )


# ---------------------------------------------------------------------------
# NLP evaluators (100% FREE — run locally, zero API calls)
# ---------------------------------------------------------------------------


class AzureF1ScoreEvaluator(AzureEvaluatorBase):
    """F1 score — measures word overlap between response and ground truth. FREE."""

    @property
    def name(self) -> str:
        return "f1_score"

    @property
    def requires_llm(self) -> bool:
        return False

    @property
    def requires_azure(self) -> bool:
        return False  # Runs locally

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from azure.ai.evaluation import F1ScoreEvaluator

        if self._azure_evaluator is None:
            self._azure_evaluator = F1ScoreEvaluator()

        result = self._azure_evaluator(
            response=input.response,
            ground_truth=input.expected or "",
        )

        raw_score = result.get("f1_score", 0)
        score = float(raw_score)  # Already 0-1

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            raw_score=raw_score,
            metadata={"backend": "azure_nlp"},
        )


class AzureBleuScoreEvaluator(AzureEvaluatorBase):
    """BLEU score — measures n-gram precision. FREE."""

    @property
    def name(self) -> str:
        return "bleu_score"

    @property
    def requires_llm(self) -> bool:
        return False

    @property
    def requires_azure(self) -> bool:
        return False

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from azure.ai.evaluation import BleuScoreEvaluator

        if self._azure_evaluator is None:
            self._azure_evaluator = BleuScoreEvaluator()

        result = self._azure_evaluator(
            response=input.response,
            ground_truth=input.expected or "",
        )

        raw_score = result.get("bleu_score", 0)
        score = float(raw_score)

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            raw_score=raw_score,
            metadata={"backend": "azure_nlp"},
        )


# ---------------------------------------------------------------------------
# Registry helper
# ---------------------------------------------------------------------------

AZURE_EVALUATORS = {
    # Quality (AI-assisted, uses LLM tokens)
    "groundedness": AzureGroundednessEvaluator,
    "azure_relevance": AzureRelevanceEvaluator,
    "coherence": AzureCoherenceEvaluator,
    "fluency": AzureFluencyEvaluator,
    "similarity": AzureSimilarityEvaluator,
    # Agent-specific
    "task_adherence": AzureTaskAdherenceEvaluator,
    "intent_resolution": AzureIntentResolutionEvaluator,
    "tool_call_accuracy": AzureToolCallAccuracyEvaluator,
    "response_completeness": AzureResponseCompletenessEvaluator,
    # Safety (uses Azure Content Safety, free)
    "violence": AzureViolenceEvaluator,
    "sexual": AzureSexualEvaluator,
    "self_harm": AzureSelfHarmEvaluator,
    "hate_unfairness": AzureHateUnfairnessEvaluator,
    # NLP (local, free, no LLM cost)
    "f1_score": AzureF1ScoreEvaluator,
    "bleu_score": AzureBleuScoreEvaluator,
}


def register_azure_evaluators(registry) -> None:
    """Register all Azure evaluators into an ATTEST registry."""
    for name, cls in AZURE_EVALUATORS.items():
        registry.register(name, cls)
