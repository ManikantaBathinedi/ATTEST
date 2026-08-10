"""Azure AI Content Safety protected-code evaluator.

This evaluator scans an agent's generated code for matches against code in
known GitHub repositories by calling the Protected Material for Code preview
API. A match is not automatically a copyright violation: the API returns source
URLs and license metadata so teams can review reuse and attribution obligations.

Required configuration:
    AZURE_CONTENT_SAFETY_ENDPOINT=https://<resource>.cognitiveservices.azure.com

Authentication:
    1. AZURE_CONTENT_SAFETY_KEY (or CONTENT_SAFETY_KEY), or
    2. Azure Entra ID through ATTEST's credential chain.

Microsoft documents that the service's code index is current through
April 6, 2023. Code added after that date might not be detected.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

import httpx

from attest.evaluation.interface import BaseEvaluator, EvaluationInput, EvaluationResult

API_VERSION = "2024-09-15-preview"
TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"


class AzureProtectedCodeEvaluator(BaseEvaluator):
    """Detect generated code that matches known GitHub repository code."""

    def __init__(
        self,
        threshold: float = 0.7,
        endpoint: Optional[str] = None,  # noqa: UP045
        api_key: Optional[str] = None,  # noqa: UP045
        timeout: float = 30.0,
        **kwargs: Any,
    ):
        super().__init__(threshold=threshold)
        self._endpoint = (
            endpoint
            or os.environ.get("AZURE_CONTENT_SAFETY_ENDPOINT")
            or os.environ.get("CONTENT_SAFETY_ENDPOINT")
            or ""
        ).rstrip("/")
        self._api_key = (
            api_key
            or os.environ.get("AZURE_CONTENT_SAFETY_KEY")
            or os.environ.get("CONTENT_SAFETY_KEY")
        )
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "protected_code"

    @property
    def requires_llm(self) -> bool:
        return False

    @property
    def requires_azure(self) -> bool:
        return True

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Ocp-Apim-Subscription-Key"] = self._api_key
            return headers

        from attest.utils.azure_client import get_azure_credential

        credential = get_azure_credential()
        token = credential.get_token(TOKEN_SCOPE)
        headers["Authorization"] = f"Bearer {token.token}"
        return headers

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        """Scan the generated response for known public-repository code matches."""
        if not self._endpoint:
            raise ValueError(
                "Protected Code Match requires AZURE_CONTENT_SAFETY_ENDPOINT. "
                "Set it in .env or Dashboard > Settings > API Keys."
            )
        if not input.response.strip():
            return EvaluationResult(
                name=self.name,
                score=1.0,
                passed=True,
                threshold=self.threshold,
                reason="No generated code was present to scan.",
                raw_score=False,
                metadata={"backend": "azure", "preview": True, "citations": []},
            )

        url = f"{self._endpoint}/contentsafety/text:detectProtectedMaterialForCode"
        try:
            headers = await asyncio.to_thread(self._headers)
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    url,
                    params={"api-version": API_VERSION},
                    headers=headers,
                    json={"code": input.response},
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500]
            raise RuntimeError(
                f"Protected Code Match request failed ({exc.response.status_code}): {body}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Protected Code Match request failed: {exc}") from exc

        analysis = payload.get("protectedMaterialAnalysis") or {}
        detected = bool(analysis.get("detected", False))
        citations = analysis.get("codeCitations") or []
        source_count = sum(len(item.get("sourceUrls") or []) for item in citations)
        licenses = sorted(
            {
                str(item.get("license"))
                for item in citations
                if item.get("license")
            }
        )

        if detected:
            license_text = ", ".join(licenses) if licenses else "not reported"
            reason = (
                "Generated code matches code indexed from known GitHub repositories. "
                f"Review {source_count} source citation(s) and license metadata "
                f"({license_text}) before reuse. A match alone does not determine "
                "copyright infringement."
            )
        else:
            reason = (
                "No match was found in the service's known GitHub code index. "
                "The preview index only covers code through April 6, 2023, so this "
                "result does not prove originality."
            )

        score = 0.0 if detected else 1.0
        return EvaluationResult(
            name=self.name,
            score=score,
            passed=score >= self.threshold,
            threshold=self.threshold,
            reason=reason,
            raw_score=detected,
            metadata={
                "backend": "azure",
                "preview": True,
                "detected": detected,
                "citations": citations,
                "source_count": source_count,
                "licenses": licenses,
                "index_current_through": "2023-04-06",
                "raw_result": payload,
            },
        )
