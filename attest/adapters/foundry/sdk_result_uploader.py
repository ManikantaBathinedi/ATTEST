"""Upload ATTEST results through the official Azure AI Evaluation SDK.

The uploader converts an ATTEST ``RunSummary`` to a JSONL evaluation dataset,
then calls ``azure.ai.evaluation.evaluate`` with the Foundry project endpoint.
The SDK creates an evaluation run in the Foundry portal and returns its
``studio_url``.

ATTEST has already run its configured evaluators before this uploader executes.
A small pass-through evaluator replays those numeric scores into the SDK run,
avoiding duplicate LLM calls and duplicate evaluation cost.

Usage:
    uploader = FoundrySdkResultUploader(
        endpoint="https://resource.services.ai.azure.com/api/projects/project",
        output_dir="reports/foundry",
    )
    result = await uploader.upload_run(summary)
    print(result["studio_url"])
"""

from __future__ import annotations

import asyncio
import json
import re
import typing
from pathlib import Path
from typing import Any, Literal

from attest.core.models import RunSummary, TestResult
from attest.version import __version__


class FoundrySdkUploadError(RuntimeError):
    """Raised when the Evaluation SDK cannot publish a run to Foundry."""


def _safe_metric_name(value: str) -> str:
    """Convert an evaluator or assertion name to a stable metric key."""
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()
    return normalized or "unnamed"


def _score_metric_name(backend: str, name: str) -> str:
    """Build a portal metric name that makes evaluator provenance explicit."""
    safe_backend = _safe_metric_name(backend or "builtin")
    safe_name = _safe_metric_name(name)
    if safe_name == safe_backend or safe_name.startswith(f"{safe_backend}_"):
        return f"score_{safe_name}"
    return f"score_{safe_backend}_{safe_name}"


def _is_azure_backend(backend: str) -> bool:
    """Return whether a score came from any Azure evaluator family."""
    return _safe_metric_name(backend).startswith("azure")


def _replay_attest_metrics(attest_metrics_json: str) -> dict[str, float]:
    """Return ATTEST's pre-computed numeric metrics to the Evaluation SDK.

    This function is module-level so the Evaluation SDK's worker process can
    import and pickle it on Windows.
    """
    metrics = json.loads(attest_metrics_json)
    if not isinstance(metrics, dict):
        raise ValueError("attest_metrics_json must decode to an object")
    return {
        str(name): float(value)
        for name, value in metrics.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }


def _last_message(result: TestResult, role: str) -> str:
    for message in reversed(result.messages):
        if message.role == role:
            return message.content
    return ""


def _numeric_metrics(
    result: TestResult,
    metric_scope: Literal["all", "azure_only"] = "all",
) -> dict[str, float]:
    """Build numeric per-test metrics for Foundry aggregation."""
    status = result.status.value
    metrics: dict[str, float] = {
        "passed": 1.0 if status == "passed" else 0.0,
        "failed": 1.0 if status == "failed" else 0.0,
        "error": 1.0 if status == "error" else 0.0,
        "skipped": 1.0 if status == "skipped" else 0.0,
        "latency_ms": float(result.latency_ms),
        "estimated_cost": float(result.estimated_cost),
    }

    if result.time_to_first_token_ms is not None:
        metrics["time_to_first_token_ms"] = float(result.time_to_first_token_ms)

    if result.token_usage is not None:
        metrics.update(
            {
                "input_tokens": float(result.token_usage.input_tokens),
                "output_tokens": float(result.token_usage.output_tokens),
                "total_tokens": float(result.token_usage.total_tokens),
            }
        )

    selected_scores = {
        name: score
        for name, score in result.scores.items()
        if metric_scope == "all" or _is_azure_backend(score.backend)
    }
    if selected_scores:
        metrics["evaluator_pass_rate"] = sum(
            1.0 for score in selected_scores.values() if score.passed
        ) / len(selected_scores)
        for name, score in selected_scores.items():
            metrics[_score_metric_name(score.backend, name)] = float(score.score)

    if metric_scope == "all" and result.assertions:
        metrics["assertion_pass_rate"] = sum(
            1.0 for assertion in result.assertions if assertion.passed
        ) / len(result.assertions)

    return metrics


def _result_details(
    result: TestResult,
    metric_scope: Literal["all", "azure_only"] = "all",
) -> dict[str, Any]:
    """Build non-aggregated details retained on each Foundry evaluation row."""
    return {
        "error": result.error,
        "handled_by": result.handled_by,
        "routing_path": result.routing_path,
        "tags": result.tags,
        "tool_calls": [tool.model_dump(mode="json") for tool in result.tool_calls],
        "scores": {
            name: score.model_dump(mode="json")
            for name, score in result.scores.items()
            if metric_scope == "all" or _is_azure_backend(score.backend)
        },
        "assertions": (
            [assertion.model_dump(mode="json") for assertion in result.assertions]
            if metric_scope == "all"
            else []
        ),
    }


def build_foundry_dataset(
    summary: RunSummary,
    metric_scope: Literal["all", "azure_only"] = "all",
) -> list[dict[str, Any]]:
    """Convert an ATTEST run to rows accepted by ``evaluate()``."""
    rows: list[dict[str, Any]] = []
    for result in summary.results:
        rows.append(
            {
                "query": _last_message(result, "user") or result.scenario,
                "response": _last_message(result, "assistant"),
                "test_name": result.scenario,
                "suite": result.suite,
                "status": result.status.value,
                "agent": result.agent,
                "metric_scope": metric_scope,
                "attest_metrics_json": json.dumps(
                    _numeric_metrics(result, metric_scope),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "attest_details_json": json.dumps(
                    _result_details(result, metric_scope),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    return rows


class FoundrySdkResultUploader:
    """Publish ATTEST results through ``azure.ai.evaluation.evaluate``."""

    def __init__(
        self,
        endpoint: str,
        output_dir: typing.Union[str, Path] = "reports/foundry",  # noqa: UP007
        metric_scope: Literal["all", "azure_only"] = "all",
    ):
        """Initialize the uploader.

        Args:
            endpoint: Foundry project endpoint URL.
            output_dir: Local directory for the SDK input and output artifacts.
            metric_scope: Publish all namespaced ATTEST metrics, or only metrics
                produced by the Azure evaluator backend.
        """
        self._endpoint = endpoint.rstrip("/")
        self._output_dir = Path(output_dir)
        self._metric_scope = metric_scope

    @staticmethod
    def is_available() -> bool:
        """Return whether the optional Azure Evaluation SDK is installed."""
        try:
            from azure.ai.evaluation import evaluate  # noqa: F401

            return True
        except ImportError:
            return False

    async def upload_run(self, summary: RunSummary) -> dict[str, Any]:
        """Create a Foundry evaluation run and return its portal URL.

        Args:
            summary: Completed ATTEST run.

        Returns:
            Normalized upload result containing ``studio_url``, local artifact
            paths, SDK metrics, and uploaded row count.

        Raises:
            FoundrySdkUploadError: If the SDK is absent, evaluation fails, or
                no portal URL is returned.
        """
        return await asyncio.to_thread(self._upload_sync, summary)

    def _upload_sync(self, summary: RunSummary) -> dict[str, Any]:
        try:
            from azure.ai.evaluation import evaluate
        except ImportError as exc:
            raise FoundrySdkUploadError(
                "Azure AI Evaluation SDK is not installed. Install the 'azure' "
                "extra or run: pip install azure-ai-evaluation"
            ) from exc

        self._output_dir.mkdir(parents=True, exist_ok=True)
        safe_run_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", summary.run_id)
        dataset_path = self._output_dir / f"{safe_run_id}_dataset.jsonl"
        output_path = self._output_dir / f"{safe_run_id}_evaluation.json"

        rows = build_foundry_dataset(summary, self._metric_scope)
        if not rows:
            raise FoundrySdkUploadError("Cannot upload an empty ATTEST run")

        with dataset_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        try:
            sdk_result = evaluate(
                data=str(dataset_path),
                evaluators={"attest": _replay_attest_metrics},
                evaluation_name=f"ATTEST {summary.run_id}",
                azure_ai_project=self._endpoint,
                output_path=str(output_path),
                fail_on_evaluator_errors=False,
                tags={
                    "source": "attest",
                    "attest_version": __version__,
                    "run_id": summary.run_id,
                    "total_tests": str(summary.total),
                    "pass_rate": f"{summary.pass_rate:.6f}",
                    "metric_scope": self._metric_scope,
                },
                user_agent=f"attest/{__version__}",
            )
        except Exception as exc:
            raise FoundrySdkUploadError(
                f"Azure AI Evaluation SDK upload failed: {exc}"
            ) from exc

        studio_url = None
        metrics: dict[str, Any] = {}
        if isinstance(sdk_result, dict):
            studio_url = sdk_result.get("studio_url")
            metrics = sdk_result.get("metrics") or {}
        else:
            studio_url = getattr(sdk_result, "studio_url", None)
            metrics = getattr(sdk_result, "metrics", {}) or {}

        if not studio_url:
            raise FoundrySdkUploadError(
                "Evaluation completed locally, but Foundry returned no studio_url. "
                "Verify the project endpoint, Azure login, and RBAC permissions. "
                f"Local result: {output_path}"
            )

        if "attest.passed" not in metrics:
            raise FoundrySdkUploadError(
                "Foundry created an evaluation run, but ATTEST metric replay failed. "
                f"Inspect the local result: {output_path}"
            )

        return {
            "status": "uploaded",
            "backend": "sdk",
            "studio_url": studio_url,
            "metrics": metrics,
            "rows_uploaded": len(rows),
            "metric_scope": self._metric_scope,
            "dataset_path": str(dataset_path),
            "output_path": str(output_path),
        }
