"""Tests for SDK-native Foundry evaluation result publication."""

import json
import sys
import types

import pytest

from attest.adapters.foundry.sdk_result_uploader import (
    FoundrySdkResultUploader,
    FoundrySdkUploadError,
    _replay_attest_metrics,
    build_foundry_dataset,
)
from attest.core.config_models import (
    AgentConfig,
    AttestConfig,
    AzureEvalConfig,
    EvaluationConfig,
    ReportingConfig,
)
from attest.core.models import (
    AssertionResult,
    EvalScore,
    Message,
    RunSummary,
    Status,
    TestResult,
    TokenUsage,
)
from attest.core.runner import TestRunner
from attest.evaluation.registry import EvaluatorRegistry
from attest.evaluation.interface import EvaluationInput
from attest.plugins.azure_eval.evaluators import (
    AzureGroundednessEvaluator,
    AzureViolenceEvaluator,
)

# The Azure evaluation SDK is an optional extra (``pip install attest[azure]``).
# These tests assert the real SDK contract, so skip them when it is absent.
try:
    import azure.ai.evaluation  # noqa: F401

    _AZURE_SDK_INSTALLED = True
except ImportError:
    _AZURE_SDK_INSTALLED = False

requires_azure_sdk = pytest.mark.skipif(
    not _AZURE_SDK_INSTALLED,
    reason="azure-ai-evaluation is not installed",
)


def _install_fake_evaluation_module(monkeypatch, evaluate):
    module = types.ModuleType("azure.ai.evaluation")
    module.evaluate = evaluate
    monkeypatch.setitem(sys.modules, "azure.ai.evaluation", module)


def _summary() -> RunSummary:
    result = TestResult(
        scenario="travel question",
        suite="smoke",
        status=Status.PASSED,
        messages=[
            Message(role="user", content="Where should I go?"),
            Message(role="assistant", content="Try Kyoto."),
        ],
        scores={
            "relevance": EvalScore(
                name="relevance",
                score=0.8,
                passed=True,
                threshold=0.7,
                reason="Relevant",
            )
        },
        assertions=[AssertionResult(name="contains:Kyoto", passed=True)],
        latency_ms=125.0,
        token_usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        agent="travel_agent",
        tags=["smoke"],
    )
    summary = RunSummary(run_id="run-123")
    summary.add_result(result)
    return summary


def test_build_foundry_dataset_preserves_inputs_and_metrics():
    rows = build_foundry_dataset(_summary())

    assert len(rows) == 1
    assert rows[0]["query"] == "Where should I go?"
    assert rows[0]["response"] == "Try Kyoto."
    assert rows[0]["test_name"] == "travel question"

    metrics = json.loads(rows[0]["attest_metrics_json"])
    assert metrics["passed"] == 1.0
    assert metrics["score_builtin_relevance"] == 0.8
    assert metrics["assertion_pass_rate"] == 1.0
    assert metrics["total_tokens"] == 15.0


def test_all_scope_namespaces_each_evaluator_backend():
    summary = _summary()
    result = summary.results[0]
    result.scores["groundedness"] = EvalScore(
        name="groundedness",
        score=0.9,
        passed=True,
        threshold=0.7,
        backend="azure",
    )
    result.scores["violence"] = EvalScore(
        name="violence",
        score=1.0,
        passed=True,
        threshold=0.7,
        backend="azure_safety",
    )
    result.scores["f1_score"] = EvalScore(
        name="f1_score",
        score=0.85,
        passed=True,
        threshold=0.7,
        backend="azure_nlp",
    )
    result.scores["deepeval_faithfulness"] = EvalScore(
        name="deepeval_faithfulness",
        score=0.7,
        passed=True,
        threshold=0.7,
        backend="deepeval",
    )

    row = build_foundry_dataset(summary, metric_scope="all")[0]
    metrics = json.loads(row["attest_metrics_json"])

    assert metrics["score_builtin_relevance"] == 0.8
    assert metrics["score_azure_groundedness"] == 0.9
    assert metrics["score_deepeval_faithfulness"] == 0.7
    assert row["metric_scope"] == "all"


def test_azure_only_scope_filters_external_scores_and_assertions():
    summary = _summary()
    result = summary.results[0]
    result.scores["groundedness"] = EvalScore(
        name="groundedness",
        score=0.9,
        passed=True,
        threshold=0.7,
        backend="azure",
    )
    result.scores["violence"] = EvalScore(
        name="violence",
        score=1.0,
        passed=True,
        threshold=0.7,
        backend="azure_safety",
    )
    result.scores["f1_score"] = EvalScore(
        name="f1_score",
        score=0.85,
        passed=True,
        threshold=0.7,
        backend="azure_nlp",
    )

    row = build_foundry_dataset(summary, metric_scope="azure_only")[0]
    metrics = json.loads(row["attest_metrics_json"])
    details = json.loads(row["attest_details_json"])

    assert metrics["score_azure_groundedness"] == 0.9
    assert metrics["score_azure_safety_violence"] == 1.0
    assert metrics["score_azure_nlp_f1_score"] == 0.85
    assert "score_builtin_relevance" not in metrics
    assert "assertion_pass_rate" not in metrics
    assert set(details["scores"]) == {"groundedness", "violence", "f1_score"}
    assert details["assertions"] == []
    assert row["metric_scope"] == "azure_only"


def test_replay_attest_metrics_returns_only_numeric_values():
    result = _replay_attest_metrics(
        json.dumps({"score": 0.75, "passed": 1, "label": "good", "flag": True})
    )
    assert result == {"score": 0.75, "passed": 1.0}


@requires_azure_sdk
def test_registry_injects_foundry_project_into_azure_safety_evaluator():
    endpoint = "https://resource.services.ai.azure.com/api/projects/project"
    registry = EvaluatorRegistry(azure_ai_project=endpoint)
    evaluator = registry.get("violence")
    assert evaluator._azure_ai_project == endpoint


@requires_azure_sdk
def test_runner_prefers_canonical_azure_evaluation_project():
    canonical = "https://resource.services.ai.azure.com/api/projects/eval-project"
    reporting = "https://resource.services.ai.azure.com/api/projects/report-project"
    runner = TestRunner(
        AttestConfig(
            evaluation=EvaluationConfig(azure=AzureEvalConfig(project=canonical)),
            reporting=ReportingConfig(foundry_endpoint=reporting),
        )
    )
    evaluator = runner._registry.get("violence")
    assert evaluator._azure_ai_project == canonical


@requires_azure_sdk
def test_runner_injects_azure_quality_model_configuration():
    runner = TestRunner(
        AttestConfig(
            evaluation=EvaluationConfig(
                judge={"model": "azure/gpt-4.1-mini"},
                azure=AzureEvalConfig(
                    model_config={
                        "azure_endpoint": "https://models.openai.azure.com",
                        "azure_deployment": "judge-deployment",
                        "api_key": "test-key",
                    }
                ),
            )
        )
    )
    evaluator = runner._registry.get("groundedness")
    assert evaluator._model_config["azure_endpoint"] == (
        "https://models.openai.azure.com"
    )
    assert evaluator._model_config["azure_deployment"] == "judge-deployment"
    assert evaluator._model_config["api_key"] == "test-key"


@requires_azure_sdk
async def test_quality_evaluator_passes_keyless_credential_separately(monkeypatch):
    captured = {}
    credential = object()

    class _Groundedness:
        def __init__(self, model_config, credential=None, **kwargs):
            captured["model_config"] = model_config
            captured["credential"] = credential

        def __call__(self, **kwargs):
            return {"groundedness": 5, "groundedness_reason": "grounded"}

    import azure.ai.evaluation

    monkeypatch.setattr(azure.ai.evaluation, "GroundednessEvaluator", _Groundedness)
    evaluator = AzureGroundednessEvaluator(
        model_config={
            "azure_endpoint": "https://models.openai.azure.com",
            "azure_deployment": "judge",
        },
        credential=credential,
    )

    result = await evaluator.evaluate(
        EvaluationInput(query="q", response="a", context="source")
    )

    assert result.passed is True
    assert captured["credential"] is credential
    assert "credential" not in captured["model_config"]


@requires_azure_sdk
async def test_safety_evaluator_passes_required_credential(monkeypatch):
    captured = {}
    credential = object()

    class _Violence:
        def __init__(self, credential, azure_ai_project, **kwargs):
            captured["credential"] = credential
            captured["project"] = azure_ai_project

        def __call__(self, **kwargs):
            return {"violence": 0, "violence_reason": "safe"}

    import azure.ai.evaluation

    monkeypatch.setattr(azure.ai.evaluation, "ViolenceEvaluator", _Violence)
    evaluator = AzureViolenceEvaluator(
        azure_ai_project="https://resource.services.ai.azure.com/api/projects/p",
        credential=credential,
    )

    result = await evaluator.evaluate(EvaluationInput(query="q", response="a"))

    assert result.passed is True
    assert captured["credential"] is credential
    assert captured["project"].endswith("/projects/p")


async def test_sdk_uploader_calls_evaluate_and_returns_studio_url(tmp_path, monkeypatch):
    captured = {}

    def fake_evaluate(**kwargs):
        captured.update(kwargs)
        rows = [json.loads(line) for line in open(kwargs["data"], encoding="utf-8")]
        assert rows[0]["response"] == "Try Kyoto."
        with open(kwargs["output_path"], "w", encoding="utf-8") as handle:
            json.dump({"rows": rows}, handle)
        return {
            "rows": rows,
            "metrics": {"attest.passed": 1.0},
            "studio_url": "https://ai.azure.com/project/evaluations/run-123",
        }

    _install_fake_evaluation_module(monkeypatch, fake_evaluate)

    uploader = FoundrySdkResultUploader(
        endpoint="https://resource.services.ai.azure.com/api/projects/project",
        output_dir=tmp_path,
    )
    result = await uploader.upload_run(_summary())

    assert result["status"] == "uploaded"
    assert result["backend"] == "sdk"
    assert result["rows_uploaded"] == 1
    assert result["studio_url"].endswith("run-123")
    assert captured["azure_ai_project"].endswith("/projects/project")
    assert captured["fail_on_evaluator_errors"] is False
    assert captured["evaluation_name"] == "ATTEST run-123"
    assert captured["tags"]["metric_scope"] == "all"
    assert (tmp_path / "run-123_dataset.jsonl").exists()
    assert (tmp_path / "run-123_evaluation.json").exists()


async def test_sdk_uploader_rejects_missing_studio_url(tmp_path, monkeypatch):
    def fake_evaluate(**kwargs):
        return {"rows": [], "metrics": {}, "studio_url": None}

    _install_fake_evaluation_module(monkeypatch, fake_evaluate)

    uploader = FoundrySdkResultUploader(
        endpoint="https://resource.services.ai.azure.com/api/projects/project",
        output_dir=tmp_path,
    )
    with pytest.raises(FoundrySdkUploadError, match="no studio_url"):
        await uploader.upload_run(_summary())


async def test_runner_prefers_sdk_and_returns_portal_url(tmp_path, monkeypatch):
    async def fake_upload(self, summary):
        return {
            "status": "uploaded",
            "backend": "sdk",
            "studio_url": "https://ai.azure.com/evaluations/123",
        }

    monkeypatch.setattr(FoundrySdkResultUploader, "upload_run", fake_upload)

    config = AttestConfig(
        agents={
            "agent": AgentConfig(
                type="foundry_hosted",
                endpoint="https://resource.services.ai.azure.com/api/projects/project",
                agent_name="agent",
            )
        },
        reporting=ReportingConfig(
            output_dir=str(tmp_path),
            foundry_upload=True,
            foundry_upload_backend="sdk",
        ),
    )
    result = await TestRunner(config, registry=object())._upload_to_foundry(
        _summary(), verbose=False
    )

    assert result["backend"] == "sdk"
    assert result["studio_url"].endswith("/123")


async def test_runner_uses_rest_only_when_fallback_enabled(tmp_path, monkeypatch):
    async def fail_sdk(self, summary):
        raise FoundrySdkUploadError("SDK failed")

    async def fake_rest(summary, endpoint):
        return {"status": "uploaded", "backend": "rest"}

    monkeypatch.setattr(FoundrySdkResultUploader, "upload_run", fail_sdk)

    config = AttestConfig(
        agents={
            "agent": AgentConfig(
                type="foundry_hosted",
                endpoint="https://resource.services.ai.azure.com/api/projects/project",
                agent_name="agent",
            )
        },
        reporting=ReportingConfig(
            output_dir=str(tmp_path),
            foundry_upload=True,
            foundry_upload_backend="sdk",
            foundry_rest_fallback=True,
        ),
    )
    runner = TestRunner(config, registry=object())
    monkeypatch.setattr(runner, "_upload_to_foundry_rest", fake_rest)

    result = await runner._upload_to_foundry(_summary(), verbose=False)
    assert result == {"status": "uploaded", "backend": "rest"}


async def test_runner_does_not_silently_fallback_to_rest(tmp_path, monkeypatch):
    async def fail_sdk(self, summary):
        raise FoundrySdkUploadError("SDK failed")

    monkeypatch.setattr(FoundrySdkResultUploader, "upload_run", fail_sdk)

    config = AttestConfig(
        agents={
            "agent": AgentConfig(
                type="foundry_hosted",
                endpoint="https://resource.services.ai.azure.com/api/projects/project",
                agent_name="agent",
            )
        },
        reporting=ReportingConfig(
            output_dir=str(tmp_path),
            foundry_upload=True,
            foundry_upload_backend="sdk",
            foundry_rest_fallback=False,
        ),
    )
    result = await TestRunner(config, registry=object())._upload_to_foundry(
        _summary(), verbose=False
    )

    assert result["status"] == "failed"
    assert result["backend"] == "sdk"
    assert "SDK failed" in result["detail"]
