"""Foundry Portal Result Uploader — push ATTEST results to Azure Foundry.

Uploads test run results, evaluation scores, and metrics to the Azure
Foundry portal so teams can track agent quality alongside deployments.

Usage:
    from attest.adapters.foundry.result_uploader import FoundryResultUploader

    uploader = FoundryResultUploader(endpoint="https://your-resource.services.ai.azure.com/api/projects/your-project")
    await uploader.upload_run(summary)

From CLI:
    attest run --upload-to-foundry

From YAML config:
    reporting:
      foundry_upload: true
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from attest.core.models import RunSummary, TestResult, Status

logger = logging.getLogger(__name__)


class FoundryResultUploader:
    """Upload ATTEST test results to Azure Foundry portal."""

    def __init__(
        self,
        endpoint: str,
        api_key: Optional[str] = None,
    ):
        """
        Args:
            endpoint: Foundry project endpoint URL.
            api_key: API key (optional — falls back to env vars / Azure credential).
        """
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Create an HTTP client with proper auth headers."""
        if self._client:
            return self._client

        headers = {"Content-Type": "application/json"}

        # Try API key first
        key = (
            self._api_key
            or os.environ.get("AZURE_API_KEY")
            or os.environ.get("AZURE_OPENAI_API_KEY")
        )

        if key:
            headers["Authorization"] = f"Bearer {key}"
        else:
            # Token-based auth (SP, WIF, Managed Identity, CLI)
            try:
                from attest.utils.azure_client import get_azure_credential

                credential = get_azure_credential()
                token = credential.get_token("https://management.azure.com/.default")
                headers["Authorization"] = f"Bearer {token.token}"
            except Exception as e:
                logger.warning(f"Could not get Azure credential for Foundry upload: {e}")

        self._client = httpx.AsyncClient(
            base_url=self._endpoint,
            headers=headers,
            timeout=30.0,
        )
        return self._client

    def _format_run_for_upload(self, summary: RunSummary) -> Dict[str, Any]:
        """Convert a RunSummary into the Foundry evaluation format."""
        metrics = {
            "pass_rate": summary.pass_rate,
            "overall_score": summary.overall_score,
            "total_tests": summary.total,
            "passed": summary.passed,
            "failed": summary.failed,
            "errors": summary.errors,
            "duration_seconds": summary.duration_seconds,
        }

        # Per-test details
        test_results = []
        for result in summary.results:
            test_entry = {
                "test_name": result.scenario,
                "suite": result.suite,
                "status": result.status.value,
                "latency_ms": result.latency_ms,
                "agent": result.agent,
                "tags": result.tags,
            }

            # Add evaluation scores
            if result.scores:
                test_entry["scores"] = {
                    name: {
                        "score": score.score,
                        "passed": score.passed,
                        "threshold": score.threshold,
                        "backend": score.backend,
                        "reason": score.reason,
                    }
                    for name, score in result.scores.items()
                }

            # Add assertion results
            if result.assertions:
                test_entry["assertions"] = [
                    {
                        "name": a.name,
                        "passed": a.passed,
                        "message": a.message,
                    }
                    for a in result.assertions
                ]

            # Add routing info if present
            if result.handled_by:
                test_entry["handled_by"] = result.handled_by
            if result.routing_path:
                test_entry["routing_path"] = result.routing_path

            test_results.append(test_entry)

        return {
            "run_id": summary.run_id,
            "timestamp": summary.timestamp.isoformat() if summary.timestamp else datetime.utcnow().isoformat(),
            "metrics": metrics,
            "results": test_results,
            "source": "attest",
            "version": "1.0",
        }

    async def upload_run(self, summary: RunSummary) -> Dict[str, Any]:
        """Upload a complete test run to Foundry.

        Args:
            summary: The RunSummary from a test execution.

        Returns:
            Response from Foundry API with upload confirmation.
        """
        client = await self._get_client()
        payload = self._format_run_for_upload(summary)

        try:
            # Try the evaluations endpoint first (Foundry standard)
            response = await client.post(
                "/evaluations",
                json=payload,
            )

            if response.status_code in (200, 201, 202):
                logger.info(
                    f"Successfully uploaded run '{summary.run_id}' to Foundry "
                    f"({summary.total} tests, {summary.pass_rate:.0%} pass rate)"
                )
                return response.json() if response.text else {"status": "uploaded"}

            # Fallback: try the runs endpoint
            response = await client.post(
                "/runs",
                json=payload,
            )

            if response.status_code in (200, 201, 202):
                logger.info(f"Uploaded run '{summary.run_id}' to Foundry via /runs endpoint")
                return response.json() if response.text else {"status": "uploaded"}

            logger.warning(
                f"Foundry upload returned status {response.status_code}: {response.text[:200]}"
            )
            return {"status": "failed", "code": response.status_code, "detail": response.text[:200]}

        except httpx.ConnectError as e:
            logger.warning(f"Could not connect to Foundry for result upload: {e}")
            return {"status": "connection_error", "detail": str(e)}
        except Exception as e:
            logger.warning(f"Foundry upload failed: {e}")
            return {"status": "error", "detail": str(e)}

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
