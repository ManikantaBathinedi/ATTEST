"""Relevancy evaluator.

Judges whether the agent's response is relevant to the user's query.
Doesn't need an expected answer — just checks if the response addresses
what was asked.

When to use:
    For any test — checks that the agent didn't go off-topic.
"""

from attest.evaluation.interface import BaseEvaluator, EvaluationInput, EvaluationResult
from attest.evaluation.llm_judge import LLMJudge

PROMPT_TEMPLATE = """\
You are an expert evaluator. Score the RELEVANCY of an AI assistant's response.

**User Query:** {query}

**AI Response:** {response}

**Scoring criteria:**
1 = Completely irrelevant, does not address the question at all
2 = Mostly irrelevant, touches on the topic but misses the point
3 = Partially relevant, addresses some aspects of the question
4 = Mostly relevant, addresses the question with minor tangents
5 = Fully relevant, directly and completely addresses the question

Respond ONLY with JSON (no other text):
{{"score": <1-5>, "reason": "<brief explanation>"}}
"""


class RelevancyEvaluator(BaseEvaluator):
    """Judges whether the response is relevant to the query."""

    def __init__(self, threshold: float = 0.7, model: str = "openai/gpt-4.1-mini"):
        super().__init__(threshold=threshold)
        self._judge = LLMJudge(model=model)

    @property
    def name(self) -> str:
        return "relevancy"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        prompt = PROMPT_TEMPLATE.format(
            query=input.query,
            response=input.response,
        )

        score, reason = await self._judge.score(prompt)

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=reason,
        )
