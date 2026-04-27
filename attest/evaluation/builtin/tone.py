"""Tone evaluator.

Judges whether the agent's response has the appropriate tone for the
situation (professional, empathetic, friendly, etc.).

When to use:
    Customer-facing agents where tone matters — support bots, sales
    assistants, healthcare agents.
"""

from attest.evaluation.interface import BaseEvaluator, EvaluationInput, EvaluationResult
from attest.evaluation.llm_judge import LLMJudge

PROMPT_TEMPLATE = """\
You are an expert evaluator. Score the TONE of an AI assistant's response.

**User Query:** {query}

**AI Response:** {response}

**Scoring criteria:**
1 = Inappropriate tone — rude, dismissive, or completely wrong for the situation
2 = Poor tone — somewhat off, could irritate the user
3 = Acceptable tone — neutral, neither good nor bad
4 = Good tone — professional and appropriate for the situation
5 = Excellent tone — perfectly calibrated, empathetic if needed, professional

Respond ONLY with JSON (no other text):
{{"score": <1-5>, "reason": "<brief explanation>"}}
"""


class ToneEvaluator(BaseEvaluator):
    """Judges tone appropriateness of the response."""

    def __init__(self, threshold: float = 0.6, model: str = "openai/gpt-4.1-mini"):
        super().__init__(threshold=threshold)
        self._judge = LLMJudge(model=model)

    @property
    def name(self) -> str:
        return "tone"

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
