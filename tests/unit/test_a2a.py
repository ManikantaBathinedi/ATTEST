"""Unit tests for the A2A (Agent2Agent) adapter.

Uses httpx.MockTransport so no network is needed.
"""
import httpx
import pytest

from attest.adapters import create_adapter, A2AAgentAdapter
from attest.core.config_models import AgentConfig
from attest.core.exceptions import ConfigError, AdapterError


def _adapter_with_handler(handler, endpoint="https://agent.example.com", path="/"):
    cfg = AgentConfig(type="a2a", endpoint=endpoint)
    cfg.request.path = path
    adapter = A2AAgentAdapter(cfg)
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return adapter


def test_factory_creates_a2a():
    cfg = AgentConfig(type="a2a", endpoint="https://x.example.com")
    assert isinstance(create_adapter(cfg), A2AAgentAdapter)


def test_factory_requires_endpoint():
    cfg = AgentConfig(type="a2a")
    with pytest.raises(ConfigError):
        create_adapter(cfg)


async def test_message_send_direct_message_parts():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        assert '"method": "message/send"' in body or '"method":"message/send"' in body
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": "1",
            "result": {"role": "agent", "parts": [{"kind": "text", "text": "Hello from A2A"}]},
        })

    adapter = _adapter_with_handler(handler)
    r = await adapter.send_message("hi")
    assert r.content == "Hello from A2A"


async def test_message_send_task_with_artifacts():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": "1",
            "result": {
                "id": "task-1", "contextId": "ctx-9",
                "status": {"state": "completed"},
                "artifacts": [{"parts": [{"kind": "text", "text": "artifact answer"}]}],
            },
        })

    adapter = _adapter_with_handler(handler)
    r = await adapter.send_message("do it")
    assert r.content == "artifact answer"


async def test_context_id_is_tracked():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": "1",
            "result": {"contextId": "ctx-42", "parts": [{"kind": "text", "text": "ok"}]},
        })

    adapter = _adapter_with_handler(handler)
    await adapter.send_message("hi")
    assert adapter._context_id == "ctx-42"


async def test_jsonrpc_error_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": "1",
            "error": {"code": -32601, "message": "Method not found"},
        })

    adapter = _adapter_with_handler(handler)
    with pytest.raises(AdapterError):
        await adapter.send_message("hi")


async def test_health_check_reads_agent_card():
    def handler(request: httpx.Request) -> httpx.Response:
        if "agent" in request.url.path:
            return httpx.Response(200, json={"name": "Demo", "capabilities": {"streaming": True}})
        return httpx.Response(404)

    adapter = _adapter_with_handler(handler)
    assert await adapter.health_check() is True
    caps = await adapter.get_capabilities()
    assert caps.supports_streaming is True
