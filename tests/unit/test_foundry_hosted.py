"""Unit tests for the Azure Foundry hosted (container) agent adapter.

Covers URL construction, response/tool/usage parsing, header auth selection,
and the prompt-adapter auto-fallback to the hosted endpoint on a 400.

All network calls are mocked — no real Foundry project or credentials needed.

Run:
    pytest tests/unit/test_foundry_hosted.py -v
"""

import pytest

from attest.adapters import create_adapter
from attest.adapters.foundry.hosted_agent import (
    FoundryHostedAgentAdapter,
    _extract_output_text,
    _extract_tool_calls,
    _extract_token_usage,
)
from attest.adapters.foundry.prompt_agent import FoundryPromptAgentAdapter
from attest.core.config_models import AgentConfig


ENDPOINT = "https://res.services.ai.azure.com/api/projects/proj"


def test_agent_url_construction_strips_trailing_slash():
    a = FoundryHostedAgentAdapter(endpoint=ENDPOINT + "/", agent_name="My-Agent")
    assert a._agent_url == (
        f"{ENDPOINT}/agents/My-Agent/endpoint/protocols/openai/responses"
    )


def test_create_adapter_builds_hosted_from_config():
    cfg = AgentConfig(type="foundry_hosted", endpoint=ENDPOINT, agent_name="My-Agent")
    adapter = create_adapter(cfg)
    assert isinstance(adapter, FoundryHostedAgentAdapter)


def test_create_adapter_requires_agent_name():
    from attest.core.exceptions import ConfigError

    cfg = AgentConfig(type="foundry_hosted", endpoint=ENDPOINT)
    with pytest.raises(ConfigError):
        create_adapter(cfg)


def test_extract_output_text_from_message_items():
    data = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Hello world"}],
            }
        ]
    }
    assert _extract_output_text(data) == "Hello world"


def test_extract_output_text_prefers_output_text_field():
    assert _extract_output_text({"output_text": "quick"}) == "quick"


def test_extract_tool_calls_parses_function_call():
    data = {
        "output": [
            {
                "type": "function_call",
                "name": "search",
                "arguments": '{"q": "japan"}',
            },
            {"type": "function_call_output", "output": "result-text"},
        ]
    }
    calls = _extract_tool_calls(data)
    assert len(calls) == 1
    assert calls[0].name == "search"
    assert calls[0].arguments == {"q": "japan"}
    assert calls[0].result == "result-text"


def test_extract_token_usage():
    usage = _extract_token_usage(
        {"usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}
    )
    assert usage is not None
    assert usage.input_tokens == 10
    assert usage.output_tokens == 5
    assert usage.total_tokens == 15


def test_build_headers_uses_api_key(monkeypatch):
    monkeypatch.delenv("AZURE_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    a = FoundryHostedAgentAdapter(endpoint=ENDPOINT, agent_name="A", api_key="secret")
    headers = a._build_headers()
    assert headers == {"api-key": "secret"}


async def test_send_message_posts_to_hosted_endpoint(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "hi there"}],
                    }
                ],
                "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
            }

    class _FakeAsyncClient:
        def __init__(self, timeout=None):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json=None, params=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["params"] = params
            captured["headers"] = headers
            return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    a = FoundryHostedAgentAdapter(endpoint=ENDPOINT, agent_name="A", api_key="k")
    r = await a.send_message("hello")

    assert r.content == "hi there"
    assert r.token_usage.total_tokens == 5
    assert captured["params"] == {"api-version": "v1"}
    assert captured["json"] == {"input": [{"role": "user", "content": "hello"}]}
    assert captured["url"].endswith("/agents/A/endpoint/protocols/openai/responses")
    assert captured["headers"] == {"api-key": "k"}
    assert captured["timeout"] == 420.0


async def test_prompt_adapter_falls_back_to_hosted(monkeypatch):
    """A hosted-agent 400 on responses.create() should transparently retry
    against the hosted endpoint."""

    class _FailingResponses:
        def create(self, **kwargs):
            raise Exception(
                "Error code: 400 - Hosted agents can only be called "
                "through the agent endpoint"
            )

    class _FakeClient:
        responses = _FailingResponses()

    p = FoundryPromptAgentAdapter(
        endpoint=ENDPOINT, agent_name="A", agent_version="1", api_key="k"
    )
    p._openai_client = _FakeClient()
    p._connected = True

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"output_text": "from hosted"}

    class _FakeAsyncClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **kwargs):
            return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    r = await p.send_message("hi")
    assert r.content == "from hosted"
    assert p._hosted_detected is True

    # The detected mode is sticky: the known-invalid prompt request is not retried.
    p._openai_client.responses.create = lambda **kwargs: (_ for _ in ()).throw(
        AssertionError("prompt endpoint retried after hosted detection")
    )
    r2 = await p.send_message("again")
    assert r2.content == "from hosted"


def test_prompt_adapter_does_not_fallback_on_generic_bad_request():
    p = FoundryPromptAgentAdapter(
        endpoint=ENDPOINT, agent_name="A", agent_version="1", api_key="k"
    )
    assert p._is_hosted_agent_error(Exception("400 bad_request: invalid input")) is False
