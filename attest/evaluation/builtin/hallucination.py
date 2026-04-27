"""Hallucination evaluator.

Detects whether the agent made up information that isn't supported by
the provided context or expected answer. Critical for RAG applications.

When to use:
    When you provide context/documents and want to make sure the agent
    doesn't fabricate facts not in those documents.
"""

from attest.evaluation.interface import BaseEvaluator, EvaluationInput, EvaluationResult
from attest.evaluation.llm_judge import LLMJudge

PROMPT_TEMPLATE = """\
You are an expert evaluator. Check if the AI assistant's response contains HALLUCINATIONS.

A hallucination is when the AI states something as fact that is NOT supported by the provided context or expected answer.

**User Query:** {query}

**AI Response:** {response}

**Context / Source of Truth:** {context}

**Scoring criteria (INVERTED — higher = less hallucination):**
1 = Severe hallucination — most of the response is fabricated
2 = Significant hallucination — several unsupported claims
3 = Some hallucination — one or two unsupported claims mixed with correct info
4 = Minor hallucination — mostly accurate with small unsupported details
5 = No hallucination — everything in the response is supported by the context

Respond ONLY with JSON (no other text):
{{"score": <1-5>, "reason": "<brief explanation of any hallucinated content>"}}
"""


class HallucinationEvaluator(BaseEvaluator):
    """Detects fabricated information not supported by context."""

    def __init__(self, threshold: float = 0.7, model: str = "openai/gpt-4.1-mini"):
        super().__init__(threshold=threshold)
        self._judge = LLMJudge(model=model)

    @property
    def name(self) -> str:
        return "hallucination"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        context = input.context or input.expected or "No context provided"

        prompt = PROMPT_TEMPLATE.format(
            query=input.query,
            response=input.response,
            context=context,
        )

        score, reason = await self._judge.score(prompt)

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=reason,
        )
