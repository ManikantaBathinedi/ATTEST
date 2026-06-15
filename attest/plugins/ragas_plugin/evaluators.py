"""RAGAS Plugin for ATTEST.

Wraps RAGAS RAG-evaluation metrics into ATTEST's BaseEvaluator interface.
RAGAS is the de-facto standard for evaluating Retrieval-Augmented Generation
pipelines, so these metrics are valuable for any agent that grounds answers in
retrieved context.

Install: pip install ragas langchain-openai

Available evaluators (register with 'ragas_' prefix):
    ragas_faithfulness        — Is the answer grounded in the retrieved context?
    ragas_answer_relevancy    — Does the answer address the question?
    ragas_context_precision   — Is the retrieved context focused/relevant?
    ragas_context_recall      — Does the context cover the reference answer?

Usage in YAML:
    evaluators:
      - ragas_faithfulness
      - ragas_answer_relevancy: { threshold: 0.8 }

These metrics need ``context`` (retrieved docs) on the test case. Context-recall
and context-precision also use ``expected`` / ``ground_truth`` as the reference.
"""

from __future__ import annotations

import os
from typing import Any, List, Optional

from attest.evaluation.interface import (
    BaseEvaluator,
    EvaluationInput,
    EvaluationResult,
)


class RagasBase(BaseEvaluator):
    """Base class for RAGAS evaluator wrappers."""

    def __init__(self, threshold: float = 0.7, model: str = "gpt-4.1-mini", **kwargs):
        super().__init__(threshold=threshold)
        self._model = model
        self._kwargs = kwargs

    @property
    def requires_llm(self) -> bool:
        return True

    # -- model / embedding wiring -------------------------------------------------
    def _model_name(self) -> str:
        m = self._model
        for prefix in ("azure/", "openai/"):
            if m.startswith(prefix):
                m = m[len(prefix):]
        return m

    def _get_llm(self):
        """Build a RAGAS-compatible LLM wrapper from env credentials.

        Supports Azure OpenAI (AZURE_API_BASE + AZURE_API_KEY) and OpenAI
        (OPENAI_API_KEY). Raises if neither is configured.
        """
        from ragas.llms import LangchainLLMWrapper

        name = self._model_name()
        azure_endpoint = os.environ.get("AZURE_API_BASE", "")
        azure_key = os.environ.get("AZURE_API_KEY", "")

        if azure_endpoint and azure_key:
            from langchain_openai import AzureChatOpenAI

            llm = AzureChatOpenAI(
                azure_endpoint=azure_endpoint,
                api_key=azure_key,
                azure_deployment=name,
                api_version=os.environ.get("AZURE_API_VERSION", "2024-08-01-preview"),
                temperature=0.0,
            )
            return LangchainLLMWrapper(llm)

        if os.environ.get("OPENAI_API_KEY"):
            from langchain_openai import ChatOpenAI

            return LangchainLLMWrapper(ChatOpenAI(model=name, temperature=0.0))

        raise RuntimeError(
            "RAGAS needs an LLM. Set AZURE_API_BASE + AZURE_API_KEY (Azure) "
            "or OPENAI_API_KEY (OpenAI)."
        )

    def _get_embeddings(self):
        """Build a RAGAS-compatible embeddings wrapper from env credentials."""
        from ragas.embeddings import LangchainEmbeddingsWrapper

        azure_endpoint = os.environ.get("AZURE_API_BASE", "")
        azure_key = os.environ.get("AZURE_API_KEY", "")
        embed_deploy = os.environ.get("AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")

        if azure_endpoint and azure_key:
            from langchain_openai import AzureOpenAIEmbeddings

            emb = AzureOpenAIEmbeddings(
                azure_endpoint=azure_endpoint,
                api_key=azure_key,
                azure_deployment=embed_deploy,
                api_version=os.environ.get("AZURE_API_VERSION", "2024-08-01-preview"),
            )
            return LangchainEmbeddingsWrapper(emb)

        if os.environ.get("OPENAI_API_KEY"):
            from langchain_openai import OpenAIEmbeddings

            return LangchainEmbeddingsWrapper(OpenAIEmbeddings(model="text-embedding-3-small"))

        return None

    def _contexts(self, input: EvaluationInput) -> List[str]:
        ctx = input.context or input.expected or ""
        if isinstance(ctx, list):
            return [str(c) for c in ctx]
        return [str(ctx)] if ctx else []

    async def _score_metric(self, metric, input: EvaluationInput, metric_class: str) -> EvaluationResult:
        """Shared scoring path using RAGAS SingleTurnSample async API."""
        from ragas.dataset_schema import SingleTurnSample

        sample = SingleTurnSample(
            user_input=input.query,
            response=input.response,
            retrieved_contexts=self._contexts(input),
            reference=input.expected or input.metadata.get("ground_truth", "") or None,
        )

        try:
            score = await metric.single_turn_ascore(sample)
        except Exception as e:  # noqa: BLE001
            return EvaluationResult(
                name=self.name,
                score=0.0,
                passed=False,
                threshold=self.threshold,
                reason=f"RAGAS scoring failed: {e}",
                metadata={"backend": "ragas", "metric_class": metric_class, "error": True},
            )

        score = float(score or 0.0)
        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=f"{metric_class} score {score:.3f} (threshold {self.threshold:.2f}).",
            raw_score=score,
            metadata={"backend": "ragas", "metric_class": metric_class},
        )


class RagasFaithfulnessEvaluator(RagasBase):
    """Is the response grounded in (faithful to) the retrieved context?"""

    @property
    def name(self) -> str:
        return "ragas_faithfulness"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from ragas.metrics import Faithfulness

        metric = Faithfulness(llm=self._get_llm())
        return await self._score_metric(metric, input, "Faithfulness")


class RagasAnswerRelevancyEvaluator(RagasBase):
    """Does the response actually address the user's question?"""

    @property
    def name(self) -> str:
        return "ragas_answer_relevancy"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from ragas.metrics import ResponseRelevancy

        metric = ResponseRelevancy(llm=self._get_llm(), embeddings=self._get_embeddings())
        return await self._score_metric(metric, input, "ResponseRelevancy")


class RagasContextPrecisionEvaluator(RagasBase):
    """Is the retrieved context precise (relevant chunks ranked high)?"""

    @property
    def name(self) -> str:
        return "ragas_context_precision"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from ragas.metrics import LLMContextPrecisionWithReference

        metric = LLMContextPrecisionWithReference(llm=self._get_llm())
        return await self._score_metric(metric, input, "LLMContextPrecisionWithReference")


class RagasContextRecallEvaluator(RagasBase):
    """Does the retrieved context cover the reference answer?"""

    @property
    def name(self) -> str:
        return "ragas_context_recall"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        from ragas.metrics import LLMContextRecall

        metric = LLMContextRecall(llm=self._get_llm())
        return await self._score_metric(metric, input, "LLMContextRecall")


RAGAS_EVALUATORS = {
    "ragas_faithfulness": RagasFaithfulnessEvaluator,
    "ragas_answer_relevancy": RagasAnswerRelevancyEvaluator,
    "ragas_context_precision": RagasContextPrecisionEvaluator,
    "ragas_context_recall": RagasContextRecallEvaluator,
}


def register_ragas_evaluators(registry) -> None:
    """Register all RAGAS evaluators into an ATTEST registry."""
    for name, cls in RAGAS_EVALUATORS.items():
        registry.register(name, cls)
