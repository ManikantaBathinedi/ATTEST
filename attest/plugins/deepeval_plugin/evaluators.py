"""DeepEval Plugin for ATTEST.

Wraps DeepEval's metrics into ATTEST's BaseEvaluator interface.
Provides 10 research-backed metrics that run locally using LLM-as-judge.

Install: pip install deepeval

Available evaluators (register with 'deepeval_' prefix):
    deepeval_correctness    â€” GEval-based correctness check
    deepeval_relevancy      â€” Answer relevancy metric
    deepeval_faithfulness   â€” Faithfulness to context (RAG)
    deepeval_hallucination  â€” Hallucination detection
    deepeval_bias           â€” Bias detection
    deepeval_toxicity       â€” Toxicity detection
    deepeval_coherence      â€” Response coherence
    deepeval_summarization  â€” Summarization quality

Usage in YAML:
    evaluators:
      - deepeval_correctness
      - deepeval_relevancy
      - deepeval_hallucination: { threshold: 0.8 }
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from attest.evaluation.interface import (
    BaseEvaluator,
    EvaluationInput,
    EvaluationResult,
)


class DeepEvalBase(BaseEvaluator):
    """Base class for all DeepEval evaluator wrappers."""

    def __init__(
        self,
        threshold: float = 0.7,
        model: str = "gpt-4.1-mini",
        **kwargs,
    ):
        super().__init__(threshold=threshold)
        self._model = model
        self._kwargs = kwargs

    @property
    def requires_llm(self) -> bool:
        return True

    @property
    def requires_azure(self) -> bool:
        return False

    def _get_model(self):
        """Get a DeepEval-compatible model object.

        Priority:
        1. If OPENAI_API_KEY is set → use model name string (DeepEval's native path)
        2. If Azure OpenAI keys are set → create Azure wrapper
        3. If Azure Entra ID works (no keys) → create Azure wrapper with token auth
        4. Fallback → model name string (will error with clear message)
        """
        import os

        deploy_name = self._get_model_name()

        # Option 1: Standard OpenAI key — DeepEval handles this natively
        if os.environ.get("OPENAI_API_KEY"):
            return deploy_name

        # Option 2 & 3: Azure (key or Entra ID)
        azure_endpoint = os.environ.get("AZURE_API_BASE", "")
        if azure_endpoint:
            try:
                from deepeval.models import DeepEvalBaseLLM
                from attest.utils.azure_client import get_azure_openai_client

                class _AzureModel(DeepEvalBaseLLM):
                    """Wraps Azure OpenAI (key or Entra ID) for DeepEval metrics."""

                    def __init__(self, deployment, client):
                        self._deployment = deployment
                        self._client = client

                    def load_model(self):
                        return self._client

                    def generate(self, prompt: str, schema=None) -> str:
                        resp = self._client.chat.completions.create(
                            model=self._deployment,
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0.0,
                            max_tokens=2048,
                        )
                        return resp.choices[0].message.content

                    async def a_generate(self, prompt: str, schema=None) -> str:
                        return self.generate(prompt, schema)

                    def get_model_name(self) -> str:
                        return self._deployment

                client = get_azure_openai_client()
                return _AzureModel(deploy_name, client)
            except Exception:
                pass

        # Fallback: model name string (will fail with clear "set OPENAI_API_KEY" error)
        return deploy_name

    def _get_model_name(self) -> str:
        """Convert ATTEST model format to DeepEval format."""
        m = self._model
        # ATTEST uses 'azure/gpt-4.1-mini', DeepEval uses 'gpt-4.1-mini'
        if m.startswith("azure/"):
            m = m[len("azure/"):]
        if m.startswith("openai/"):
            m = m[len("openai/"):]
        return m


class DeepEvalCorrectnessEvaluator(DeepEvalBase):
    """GEval-based correctness: checks actual output vs expected."""

    @property
    def name(self) -> str:
        return "deepeval_correctness"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCase, LLMTestCaseParams

        metric = GEval(
            name="Correctness",
            criteria="Determine if the 'actual output' is factually correct based on the 'expected output'.",
            evaluation_params=[
                LLMTestCaseParams.ACTUAL_OUTPUT,
                LLMTestCaseParams.EXPECTED_OUTPUT,
            ],
            threshold=self.threshold,
            model=self._get_model(),
        )

        test_case = LLMTestCase(
            input=input.query,
            actual_output=input.response,
            expected_output=input.expected or "",
        )

        await asyncio.to_thread(metric.measure, test_case)

        return EvaluationResult(
            name=self.name,
            score=metric.score or 0.0,
            passed=(metric.score or 0.0) >= self.threshold,
            threshold=self.threshold,
            reason=metric.reason or "",
            raw_score=metric.score,
            metadata={"backend": "deepeval", "metric_class": "GEval"},
        )


class DeepEvalRelevancyEvaluator(DeepEvalBase):
    """Answer relevancy: checks if response addresses the query."""

    @property
    def name(self) -> str:
        return "deepeval_relevancy"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from deepeval.metrics import AnswerRelevancyMetric
        from deepeval.test_case import LLMTestCase

        metric = AnswerRelevancyMetric(
            threshold=self.threshold,
            model=self._get_model(),
        )

        test_case = LLMTestCase(
            input=input.query,
            actual_output=input.response,
        )

        await asyncio.to_thread(metric.measure, test_case)

        return EvaluationResult(
            name=self.name,
            score=metric.score or 0.0,
            passed=(metric.score or 0.0) >= self.threshold,
            threshold=self.threshold,
            reason=metric.reason or "",
            raw_score=metric.score,
            metadata={"backend": "deepeval", "metric_class": "AnswerRelevancyMetric"},
        )


class DeepEvalFaithfulnessEvaluator(DeepEvalBase):
    """Faithfulness: checks if response is faithful to provided context."""

    @property
    def name(self) -> str:
        return "deepeval_faithfulness"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from deepeval.metrics import FaithfulnessMetric
        from deepeval.test_case import LLMTestCase

        metric = FaithfulnessMetric(
            threshold=self.threshold,
            model=self._get_model(),
        )

        context = input.context or input.expected or "No context provided"
        retrieval_context = [context] if isinstance(context, str) else context

        test_case = LLMTestCase(
            input=input.query,
            actual_output=input.response,
            retrieval_context=retrieval_context,
        )

        await asyncio.to_thread(metric.measure, test_case)

        return EvaluationResult(
            name=self.name,
            score=metric.score or 0.0,
            passed=(metric.score or 0.0) >= self.threshold,
            threshold=self.threshold,
            reason=metric.reason or "",
            raw_score=metric.score,
            metadata={"backend": "deepeval", "metric_class": "FaithfulnessMetric"},
        )


class DeepEvalHallucinationEvaluator(DeepEvalBase):
    """Hallucination detection: checks for fabricated information."""

    @property
    def name(self) -> str:
        return "deepeval_hallucination"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from deepeval.metrics import HallucinationMetric
        from deepeval.test_case import LLMTestCase

        metric = HallucinationMetric(
            threshold=self.threshold,
            model=self._get_model(),
        )

        context = input.context or input.expected or "No context provided"
        contexts = [context] if isinstance(context, str) else context

        test_case = LLMTestCase(
            input=input.query,
            actual_output=input.response,
            context=contexts,
        )

        await asyncio.to_thread(metric.measure, test_case)

        # HallucinationMetric: score = 1 means no hallucination (good)
        score = metric.score or 0.0

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=metric.reason or "",
            raw_score=metric.score,
            metadata={"backend": "deepeval", "metric_class": "HallucinationMetric"},
        )


class DeepEvalBiasEvaluator(DeepEvalBase):
    """Bias detection: checks for gender, racial, or other biases."""

    @property
    def name(self) -> str:
        return "deepeval_bias"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from deepeval.metrics import BiasMetric
        from deepeval.test_case import LLMTestCase

        metric = BiasMetric(
            threshold=self.threshold,
            model=self._get_model(),
        )

        test_case = LLMTestCase(
            input=input.query,
            actual_output=input.response,
        )

        await asyncio.to_thread(metric.measure, test_case)

        # BiasMetric: score = 1 means no bias (good)
        score = metric.score or 0.0

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=metric.reason or "",
            raw_score=metric.score,
            metadata={"backend": "deepeval", "metric_class": "BiasMetric"},
        )


class DeepEvalToxicityEvaluator(DeepEvalBase):
    """Toxicity detection: checks for toxic, harmful, or offensive content."""

    @property
    def name(self) -> str:
        return "deepeval_toxicity"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from deepeval.metrics import ToxicityMetric
        from deepeval.test_case import LLMTestCase

        metric = ToxicityMetric(
            threshold=self.threshold,
            model=self._get_model(),
        )

        test_case = LLMTestCase(
            input=input.query,
            actual_output=input.response,
        )

        await asyncio.to_thread(metric.measure, test_case)

        # ToxicityMetric: score = 1 means no toxicity (good)
        score = metric.score or 0.0

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=metric.reason or "",
            raw_score=metric.score,
            metadata={"backend": "deepeval", "metric_class": "ToxicityMetric"},
        )


class DeepEvalGEvalEvaluator(DeepEvalBase):
    """Custom GEval metric: user-defined criteria via YAML config."""

    def __init__(self, criteria: str = "Is the response helpful and accurate?", eval_name: str = "deepeval_custom", **kwargs):
        super().__init__(**kwargs)
        self._criteria = criteria
        self._eval_name = eval_name

    @property
    def name(self) -> str:
        return self._eval_name

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from deepeval.metrics import GEval
        from deepeval.test_case import LLMTestCase, LLMTestCaseParams

        params = [LLMTestCaseParams.ACTUAL_OUTPUT]
        if input.expected:
            params.append(LLMTestCaseParams.EXPECTED_OUTPUT)

        metric = GEval(
            name=self._eval_name,
            criteria=self._criteria,
            evaluation_params=params,
            threshold=self.threshold,
            model=self._get_model(),
        )

        test_case = LLMTestCase(
            input=input.query,
            actual_output=input.response,
            expected_output=input.expected or None,
        )

        await asyncio.to_thread(metric.measure, test_case)

        return EvaluationResult(
            name=self.name,
            score=metric.score or 0.0,
            passed=(metric.score or 0.0) >= self.threshold,
            threshold=self.threshold,
            reason=metric.reason or "",
            raw_score=metric.score,
            metadata={"backend": "deepeval", "metric_class": "GEval", "criteria": self._criteria},
        )


# ---------------------------------------------------------------------------
# RAG metrics
# ---------------------------------------------------------------------------


class DeepEvalContextualRelevancyEvaluator(DeepEvalBase):
    """Checks if retrieved context is relevant to the query."""

    @property
    def name(self) -> str:
        return "deepeval_contextual_relevancy"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from deepeval.metrics import ContextualRelevancyMetric
        from deepeval.test_case import LLMTestCase

        metric = ContextualRelevancyMetric(threshold=self.threshold, model=self._get_model())
        context = input.context or input.expected or "No context"
        test_case = LLMTestCase(input=input.query, actual_output=input.response, retrieval_context=[context] if isinstance(context, str) else context)
        await asyncio.to_thread(metric.measure, test_case)
        return EvaluationResult(name=self.name, score=metric.score or 0.0, passed=(metric.score or 0.0) >= self.threshold, threshold=self.threshold, reason=metric.reason or "", raw_score=metric.score, metadata={"backend": "deepeval", "metric_class": "ContextualRelevancyMetric"})


class DeepEvalContextualRecallEvaluator(DeepEvalBase):
    """Checks if retrieved context contains all relevant information."""

    @property
    def name(self) -> str:
        return "deepeval_contextual_recall"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from deepeval.metrics import ContextualRecallMetric
        from deepeval.test_case import LLMTestCase

        metric = ContextualRecallMetric(threshold=self.threshold, model=self._get_model())
        context = input.context or "No context"
        test_case = LLMTestCase(input=input.query, actual_output=input.response, expected_output=input.expected or "", retrieval_context=[context] if isinstance(context, str) else context)
        await asyncio.to_thread(metric.measure, test_case)
        return EvaluationResult(name=self.name, score=metric.score or 0.0, passed=(metric.score or 0.0) >= self.threshold, threshold=self.threshold, reason=metric.reason or "", raw_score=metric.score, metadata={"backend": "deepeval", "metric_class": "ContextualRecallMetric"})


class DeepEvalContextualPrecisionEvaluator(DeepEvalBase):
    """Checks if retrieved context is precise and focused."""

    @property
    def name(self) -> str:
        return "deepeval_contextual_precision"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from deepeval.metrics import ContextualPrecisionMetric
        from deepeval.test_case import LLMTestCase

        metric = ContextualPrecisionMetric(threshold=self.threshold, model=self._get_model())
        context = input.context or "No context"
        test_case = LLMTestCase(input=input.query, actual_output=input.response, expected_output=input.expected or "", retrieval_context=[context] if isinstance(context, str) else context)
        await asyncio.to_thread(metric.measure, test_case)
        return EvaluationResult(name=self.name, score=metric.score or 0.0, passed=(metric.score or 0.0) >= self.threshold, threshold=self.threshold, reason=metric.reason or "", raw_score=metric.score, metadata={"backend": "deepeval", "metric_class": "ContextualPrecisionMetric"})


# ---------------------------------------------------------------------------
# Agent metrics
# ---------------------------------------------------------------------------


class DeepEvalToolCorrectnessEvaluator(DeepEvalBase):
    """Checks if the agent used the correct tools."""

    @property
    def name(self) -> str:
        return "deepeval_tool_correctness"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from deepeval.metrics import ToolCorrectnessMetric
        from deepeval.test_case import LLMTestCase

        metric = ToolCorrectnessMetric(threshold=self.threshold, model=self._get_model())

        # Map ATTEST tool calls to DeepEval format
        actual_tools = [tc.name for tc in input.tool_calls] if input.tool_calls else []
        expected_tools = input.metadata.get("expected_tools", [])

        test_case = LLMTestCase(input=input.query, actual_output=input.response, tools_called=actual_tools, expected_tools=expected_tools)
        await asyncio.to_thread(metric.measure, test_case)
        return EvaluationResult(name=self.name, score=metric.score or 0.0, passed=(metric.score or 0.0) >= self.threshold, threshold=self.threshold, reason=metric.reason or "", raw_score=metric.score, metadata={"backend": "deepeval", "metric_class": "ToolCorrectnessMetric"})


# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------


class DeepEvalSummarizationEvaluator(DeepEvalBase):
    """Checks quality of summarization output."""

    @property
    def name(self) -> str:
        return "deepeval_summarization"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from deepeval.metrics import SummarizationMetric
        from deepeval.test_case import LLMTestCase

        metric = SummarizationMetric(threshold=self.threshold, model=self._get_model())
        test_case = LLMTestCase(input=input.query, actual_output=input.response)
        await asyncio.to_thread(metric.measure, test_case)
        return EvaluationResult(name=self.name, score=metric.score or 0.0, passed=(metric.score or 0.0) >= self.threshold, threshold=self.threshold, reason=metric.reason or "", raw_score=metric.score, metadata={"backend": "deepeval", "metric_class": "SummarizationMetric"})


# ---------------------------------------------------------------------------
# JSON correctness
# ---------------------------------------------------------------------------


class DeepEvalJsonCorrectnessEvaluator(DeepEvalBase):
    """Checks if output is valid JSON matching expected schema."""

    @property
    def name(self) -> str:
        return "deepeval_json_correctness"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from deepeval.metrics import JsonCorrectnessMetric
        from deepeval.test_case import LLMTestCase

        schema = input.metadata.get("expected_schema", None)
        metric = JsonCorrectnessMetric(threshold=self.threshold, expected_schema=schema)
        test_case = LLMTestCase(input=input.query, actual_output=input.response)
        await asyncio.to_thread(metric.measure, test_case)
        return EvaluationResult(name=self.name, score=metric.score or 0.0, passed=(metric.score or 0.0) >= self.threshold, threshold=self.threshold, reason=metric.reason or "", raw_score=metric.score, metadata={"backend": "deepeval", "metric_class": "JsonCorrectnessMetric"})


# ---------------------------------------------------------------------------
# Registry helper
# ---------------------------------------------------------------------------

DEEPEVAL_EVALUATORS = {
    # Core quality
    "deepeval_correctness": DeepEvalCorrectnessEvaluator,
    "deepeval_relevancy": DeepEvalRelevancyEvaluator,
    "deepeval_faithfulness": DeepEvalFaithfulnessEvaluator,
    "deepeval_hallucination": DeepEvalHallucinationEvaluator,
    # Safety
    "deepeval_bias": DeepEvalBiasEvaluator,
    "deepeval_toxicity": DeepEvalToxicityEvaluator,
    # RAG context
    "deepeval_contextual_relevancy": DeepEvalContextualRelevancyEvaluator,
    "deepeval_contextual_recall": DeepEvalContextualRecallEvaluator,
    "deepeval_contextual_precision": DeepEvalContextualPrecisionEvaluator,
    # Agent
    "deepeval_tool_correctness": DeepEvalToolCorrectnessEvaluator,
    # Other
    "deepeval_summarization": DeepEvalSummarizationEvaluator,
    "deepeval_json_correctness": DeepEvalJsonCorrectnessEvaluator,
}


def register_deepeval_evaluators(registry) -> None:
    """Register all DeepEval evaluators into an ATTEST registry."""
    for name, cls in DEEPEVAL_EVALUATORS.items():
        registry.register(name, cls)
