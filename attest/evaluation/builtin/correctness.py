"""Correctness evaluator.

Judges whether the agent's response is factually correct compared to
the expected output or ground truth.

When to use:
    When you have an expected answer and want to check if the agent
    gave the right information (not necessarily word-for-word).
"""

from attest.evaluation.interface import BaseEvaluator, EvaluationInput, EvaluationResult
from attest.evaluation.llm_judge import LLMJudge

PROMPT_TEMPLATE = """\
You are an expert evaluator. Score the CORRECTNESS of an AI assistant's response.

**User Query:** {query}

**AI Response:** {response}

**Expected Answer:** {expected}

**Scoring criteria:**
1 = Completely wrong or irrelevant
2 = Mostly wrong, with minor correct elements
3 = Partially correct, but missing key information
4 = Mostly correct, with minor inaccuracies
5 = Fully correct and complete

Respond ONLY with JSON (no other text):
{{"score": <1-5>, "reason": "<brief explanation>"}}
"""


class CorrectnessEvaluator(BaseEvaluator):
    """Judges factual correctness of the response against expected output."""

    def __init__(self, threshold: float = 0.7, model: str = "openai/gpt-4.1-mini"):
        super().__init__(threshold=threshold)
        self._judge = LLMJudge(model=model)

    @property
    def name(self) -> str:
        return "correctness"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        expected = input.expected or input.metadata.get("ground_truth", "No expected answer provided")

        prompt = PROMPT_TEMPLATE.format(
            query=input.query,
            response=input.response,
            expected=expected,
        )

        score, reason = await self._judge.score(prompt)

        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=reason,
        )
