"""Completeness evaluator.

Judges whether the agent's response fully addresses all parts of the
user's query, or if it missed something.

When to use:
    When the user asks a multi-part question and you want to ensure
    the agent answered ALL parts, not just the first one.
"""

from attest.evaluation.interface import BaseEvaluator, EvaluationInput, EvaluationResult
from attest.evaluation.llm_judge import LLMJudge

PROMPT_TEMPLATE = """\
You are an expert evaluator. Score the COMPLETENESS of an AI assistant's response.

**User Query:** {query}

**AI Response:** {response}

**Scoring criteria:**
1 = Did not address any part of the question
2 = Addressed only a small part of the question
3 = Addressed about half the question, missed significant parts
4 = Addressed most parts, missed minor details
5 = Fully complete — addressed every part of the question

Respond ONLY with JSON (no other text):
{{"score": <1-5>, "reason": "<what was missed, if anything>"}}
"""


class CompletenessEvaluator(BaseEvaluator):
    """Judges whether the response fully addresses all parts of the query."""

    def __init__(self, threshold: float = 0.7, model: str = "openai/gpt-4.1-mini"):
        super().__init__(threshold=threshold)
        self._judge = LLMJudge(model=model)

    @property
    def name(self) -> str:
        return "completeness"

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
