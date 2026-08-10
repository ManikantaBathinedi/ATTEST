"""Tests for Azure Content Safety Protected Code Match evaluation."""

import httpx
import pytest

from attest.core.config_models import AttestConfig
from attest.core.models import AgentResponse, TestCase
from attest.core.runner import TestRunner
from attest.evaluation.interface import EvaluationInput
from attest.plugins.azure_eval.protected_code import AzureProtectedCodeEvaluator


class _FakeAsyncClient:
    response_payload = {}
    captured = {}

    def __init__(self, *args, **kwargs):
        self.timeout = kwargs.get("timeout")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, **kwargs):
        type(self).captured = {"url": url, **kwargs}
        request = httpx.Request("POST", url)
        return httpx.Response(200, request=request, json=type(self).response_payload)


@pytest.fixture(autouse=True)
def _reset_fake_client(monkeypatch):
    _FakeAsyncClient.response_payload = {}
    _FakeAsyncClient.captured = {}
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)


async def test_protected_code_passes_when_no_match_detected():
    _FakeAsyncClient.response_payload = {
        "protectedMaterialAnalysis": {"detected": False, "codeCitations": []}
    }
    evaluator = AzureProtectedCodeEvaluator(
        endpoint="https://safety.cognitiveservices.azure.com/",
        api_key="secret",
    )

    result = await evaluator.evaluate(
        EvaluationInput(query="write code", response="print('hello')")
    )

    assert result.score == 1.0
    assert result.passed is True
    assert result.raw_score is False
    assert "does not prove originality" in result.reason
    assert result.metadata["backend"] == "azure"
    assert _FakeAsyncClient.captured["params"] == {
        "api-version": "2024-09-15-preview"
    }
    assert _FakeAsyncClient.captured["json"] == {"code": "print('hello')"}
    assert _FakeAsyncClient.captured["headers"]["Ocp-Apim-Subscription-Key"] == "secret"


async def test_protected_code_fails_with_clear_citations_and_license():
    _FakeAsyncClient.response_payload = {
        "protectedMaterialAnalysis": {
            "detected": True,
            "codeCitations": [
                {
                    "license": "MIT",
                    "sourceUrls": [
                        "https://github.com/org/repo/blob/abc/file.py",
                        "https://github.com/org/other/blob/def/file.py",
                    ],
                }
            ],
        }
    }
    evaluator = AzureProtectedCodeEvaluator(
        endpoint="https://safety.cognitiveservices.azure.com",
        api_key="secret",
    )

    result = await evaluator.evaluate(
        EvaluationInput(query="write code", response="def copied_function(): pass")
    )

    assert result.score == 0.0
    assert result.passed is False
    assert result.raw_score is True
    assert "matches code indexed from known GitHub repositories" in result.reason
    assert "does not determine copyright infringement" in result.reason
    assert result.metadata["source_count"] == 2
    assert result.metadata["licenses"] == ["MIT"]
    assert result.metadata["index_current_through"] == "2023-04-06"


async def test_protected_code_requires_content_safety_endpoint(monkeypatch):
    monkeypatch.delenv("AZURE_CONTENT_SAFETY_ENDPOINT", raising=False)
    monkeypatch.delenv("CONTENT_SAFETY_ENDPOINT", raising=False)
    evaluator = AzureProtectedCodeEvaluator(api_key="secret")

    with pytest.raises(ValueError, match="AZURE_CONTENT_SAFETY_ENDPOINT"):
        await evaluator.evaluate(EvaluationInput(query="q", response="code"))


async def test_protected_code_empty_response_skips_remote_call():
    evaluator = AzureProtectedCodeEvaluator(
        endpoint="https://safety.cognitiveservices.azure.com",
        api_key="secret",
    )

    result = await evaluator.evaluate(EvaluationInput(query="q", response="  "))

    assert result.passed is True
    assert result.reason == "No generated code was present to scan."
    assert _FakeAsyncClient.captured == {}


async def test_runner_preserves_protected_code_citations():
    _FakeAsyncClient.response_payload = {
        "protectedMaterialAnalysis": {
            "detected": True,
            "codeCitations": [
                {
                    "license": "MIT",
                    "sourceUrls": ["https://github.com/org/repo/blob/abc/file.py"],
                }
            ],
        }
    }
    evaluator = AzureProtectedCodeEvaluator(
        endpoint="https://safety.cognitiveservices.azure.com",
        api_key="secret",
    )

    class _Registry:
        def resolve_evaluators(self, specs, default_threshold=0.7):
            return [evaluator]

    runner = TestRunner(AttestConfig(), registry=_Registry())
    scores = await runner._run_evaluators(
        TestCase(name="code", input="write code", evaluators=["protected_code"]),
        AgentResponse(content="def copied_function(): pass"),
    )

    assert scores[0].backend == "azure"
    assert scores[0].metadata["source_count"] == 1
    assert scores[0].metadata["licenses"] == ["MIT"]
