"""LLM-as-a-Judge infrastructure.

This module handles the actual LLM calls for evaluation. It uses LiteLLM
so any model works — OpenAI, Anthropic, Azure OpenAI, local models, etc.

The LLM judge:
1. Receives a prompt with the query, response, and evaluation criteria
2. Asks the LLM to score it (typically 1-5)
3. Parses the score and reason from the LLM's response
4. Normalizes the score to 0.0-1.0

Usage:
    from attest.evaluation.llm_judge import LLMJudge

    judge = LLMJudge(model="openai/gpt-4.1-mini")
    score, reason = await judge.score(
        prompt="Rate the correctness of this response...",
    )
"""

from __future__ import annotations

import json
import re
from typing import Optional, Tuple

from attest.core.exceptions import EvaluationError


class LLMJudge:
    """Calls an LLM to score agent responses.

    Uses LiteLLM under the hood, so any model provider works.
    The judge sends a scoring prompt and parses the result.
    """

    def __init__(
        self,
        model: str = "openai/gpt-4.1-mini",
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def score(self, prompt: str) -> Tuple[float, str]:
        """Send a scoring prompt to the LLM and parse the result.

        The prompt should ask the LLM to respond with JSON:
            {"score": <1-5>, "reason": "<explanation>"}

        Args:
            prompt: The full evaluation prompt with criteria and data.

        Returns:
            Tuple of (normalized_score 0.0-1.0, reason string).

        Raises:
            EvaluationError if the LLM call fails or response can't be parsed.
        """
        try:
            import os
            import litellm

            # For Azure models, set the required env vars that LiteLLM expects
            if self.model.startswith("azure/"):
                api_base = os.environ.get("AZURE_API_BASE")
                api_key = os.environ.get("AZURE_API_KEY_OPENAI") or os.environ.get("AZURE_API_KEY")
                api_version = os.environ.get("AZURE_API_VERSION", "2025-04-01-preview")

                # If no API key, try Entra ID via our shared client
                if not api_key:
                    try:
                        from attest.utils.azure_client import get_azure_openai_client, get_deployment_name
                        client = get_azure_openai_client(endpoint=api_base, api_version=api_version)
                        deploy_name = get_deployment_name(self.model)
                        response = client.chat.completions.create(
                            model=deploy_name,
                            messages=[{"role": "user", "content": prompt}],
                            temperature=self.temperature,
                            max_tokens=self.max_tokens,
                        )
                        raw_text = response.choices[0].message.content.strip()
                        return self._parse_score(raw_text)
                    except Exception as e:
                        raise EvaluationError(f"Azure Entra ID auth failed: {e}") from e

                response = await litellm.acompletion(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    api_base=api_base,
                    api_key=api_key,
                    api_version=api_version,
                )
            else:
                response = await litellm.acompletion(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )

            raw_text = response.choices[0].message.content.strip()
            return self._parse_score(raw_text)

        except ImportError:
            raise EvaluationError(
                "LiteLLM is required for LLM-as-judge evaluation. "
                "Install it with: pip install litellm"
            )
        except EvaluationError:
            raise
        except Exception as e:
            raise EvaluationError(f"LLM judge call failed: {e}") from e

    def _parse_score(self, raw_text: str) -> Tuple[float, str]:
        """Parse the LLM's response to extract score and reason.

        Tries multiple formats:
        1. JSON: {"score": 4, "reason": "..."}
        2. Markdown JSON: ```json {"score": 4, "reason": "..."} ```
        3. Plain text with score pattern: "Score: 4/5"
        """
        # Try 1: Parse as JSON directly
        score, reason = self._try_parse_json(raw_text)
        if score is not None:
            return score, reason

        # Try 2: Extract JSON from markdown code block
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
        if json_match:
            score, reason = self._try_parse_json(json_match.group(1))
            if score is not None:
                return score, reason

        # Try 3: Find JSON object anywhere in the text
        json_match = re.search(r"\{[^{}]*\"score\"[^{}]*\}", raw_text, re.DOTALL)
        if json_match:
            score, reason = self._try_parse_json(json_match.group(0))
            if score is not None:
                return score, reason

        # Try 4: Look for "Score: X/5" or "Score: X" pattern
        score_match = re.search(r"[Ss]core:\s*(\d+(?:\.\d+)?)\s*(?:/\s*5)?", raw_text)
        if score_match:
            raw_score = float(score_match.group(1))
            # Normalize: if score > 1, assume it's on a 1-5 scale
            normalized = raw_score / 5.0 if raw_score > 1.0 else raw_score
            return min(normalized, 1.0), raw_text

        # Fallback: couldn't parse
        raise EvaluationError(
            f"Could not parse LLM judge response. Expected JSON with 'score' field. "
            f"Got: {raw_text[:200]}"
        )

    def _try_parse_json(self, text: str) -> Tuple[Optional[float], str]:
        """Try to parse text as JSON with score and reason fields."""
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "score" in data:
                raw_score = float(data["score"])
                reason = str(data.get("reason", ""))

                # Normalize: if score > 1, assume it's on a 1-5 scale
                if raw_score > 1.0:
                    normalized = raw_score / 5.0
                else:
                    normalized = raw_score

                return min(max(normalized, 0.0), 1.0), reason
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        return None, ""
