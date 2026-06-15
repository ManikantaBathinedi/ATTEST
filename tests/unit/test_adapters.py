"""Unit tests for ATTEST agent adapters (Callable, LangChain, LangGraph).

Uses lightweight mock agents so no network or API keys are needed.

Run:
    pytest tests/unit/test_adapters.py -v
"""

import pytest

from attest.adapters import (
    CallableAgentAdapter,
    LangChainAgentAdapter,
    LangGraphAgentAdapter,
)
from attest.core.exceptions import AdapterError


# ---------------------------------------------------------------------------
# Callable adapter
# ---------------------------------------------------------------------------
async def test_callable_sync_function():
    adapter = CallableAgentAdapter(fn=lambda message: f"echo: {message}")
    r = await adapter.send_message("hi")
    assert r.content == "echo: hi"


async def test_callable_async_function():
    async def agent(message):
        return f"async: {message}"

    adapter = CallableAgentAdapter(fn=agent)
    r = await adapter.send_message("hi")
    assert r.content == "async: hi"


async def test_callable_dict_return_extracts_common_keys():
    adapter = CallableAgentAdapter(fn=lambda message: {"response": "from dict"})
    r = await adapter.send_message("hi")
    assert r.content == "from dict"


# ---------------------------------------------------------------------------
# LangChain adapter
# ---------------------------------------------------------------------------
class _Action:
    def __init__(self, tool, tool_input):
        self.tool = tool
        self.tool_input = tool_input


class _MockExecutor:
    tools = [type("T", (), {"name": "search", "description": "d"})()]

    def invoke(self, payload):
        assert "input" in payload
        return {
            "output": "found Paris",
            "intermediate_steps": [(_Action("search", {"q": "Paris"}), "result-x")],
            "usage_metadata": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }


async def test_langchain_extracts_content_tools_tokens():
    adapter = LangChainAgentAdapter(_MockExecutor())
    r = await adapter.send_message("find Paris")
    assert r.content == "found Paris"
    assert len(r.tool_calls) == 1
    assert r.tool_calls[0].name == "search"
    assert r.tool_calls[0].arguments == {"q": "Paris"}
    assert r.tool_calls[0].result == "result-x"
    assert r.token_usage.total_tokens == 15


async def test_langchain_capabilities_lists_tools():
    adapter = LangChainAgentAdapter(_MockExecutor())
    caps = await adapter.get_capabilities()
    assert caps.supports_tool_calls is True
    assert caps.available_tools[0]["name"] == "search"


def test_langchain_rejects_non_agent():
    with pytest.raises(AdapterError):
        LangChainAgentAdapter(object())


# ---------------------------------------------------------------------------
# LangGraph adapter
# ---------------------------------------------------------------------------
class _AI:
    type = "ai"

    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _Tool:
    type = "tool"

    def __init__(self, content, tool_call_id):
        self.content = content
        self.tool_call_id = tool_call_id


class _MockGraph:
    def invoke(self, state, config=None):
        return {
            "messages": [
                _AI(content="", tool_calls=[{"name": "lookup", "args": {"city": "Tokyo"}, "id": "c1"}]),
                _Tool("Senso-ji", tool_call_id="c1"),
                _AI(content="Visit Senso-ji in Tokyo."),
            ]
        }


async def test_langgraph_extracts_final_message_and_tools():
    adapter = LangGraphAgentAdapter(_MockGraph())
    r = await adapter.send_message("things to do in Tokyo")
    assert "Tokyo" in r.content
    assert len(r.tool_calls) == 1
    assert r.tool_calls[0].name == "lookup"
    assert r.tool_calls[0].result == "Senso-ji"  # paired by tool_call_id


def test_langgraph_rejects_non_graph():
    with pytest.raises(AdapterError):
        LangGraphAgentAdapter(object())


async def test_adapters_health_check_true_for_inprocess():
    assert await CallableAgentAdapter(fn=lambda m: m).health_check() is True
    assert await LangChainAgentAdapter(_MockExecutor()).health_check() is True
    assert await LangGraphAgentAdapter(_MockGraph()).health_check() is True


# ---------------------------------------------------------------------------
# HTTP adapter — multi-agent routing extraction
# ---------------------------------------------------------------------------


def _http_adapter(handled_by_path=None, routing_path_path=None):
    from attest.adapters.http_rest import HttpAgentAdapter
    from attest.core.config_models import AgentConfig, ResponseConfig

    return HttpAgentAdapter(
        AgentConfig(
            type="http",
            endpoint="https://example.test",
            response=ResponseConfig(
                content_path="$.reply",
                handled_by_path=handled_by_path,
                routing_path_path=routing_path_path,
            ),
        )
    )


def test_http_extract_routing_from_paths():
    adapter = _http_adapter(handled_by_path="$.handled_by", routing_path_path="$.routing_path")
    data = {"reply": "ok", "handled_by": "flights_agent", "routing_path": ["orchestrator", "flights_agent"]}
    handled_by, routing_path = adapter._extract_routing(data)
    assert handled_by == "flights_agent"
    assert routing_path == ["orchestrator", "flights_agent"]


def test_http_extract_routing_infers_handled_by_from_path_tail():
    adapter = _http_adapter(routing_path_path="$.routing_path")
    handled_by, routing_path = adapter._extract_routing({"routing_path": ["orchestrator", "hotels_agent"]})
    assert routing_path == ["orchestrator", "hotels_agent"]
    assert handled_by == "hotels_agent"  # inferred as last hop


def test_http_extract_routing_accepts_delimited_string():
    adapter = _http_adapter(routing_path_path="$.path")
    handled_by, routing_path = adapter._extract_routing({"path": "orchestrator > billing_agent"})
    assert routing_path == ["orchestrator", "billing_agent"]
    assert handled_by == "billing_agent"


def test_http_extract_routing_empty_when_unconfigured():
    adapter = _http_adapter()
    handled_by, routing_path = adapter._extract_routing({"reply": "ok"})
    assert handled_by is None
    assert routing_path == []


# ---------------------------------------------------------------------------
# Mock adapter — offline demo agent
# ---------------------------------------------------------------------------


async def test_mock_adapter_default_reply():
    from attest.adapters import MockAgentAdapter
    from attest.core.config_models import MockConfig

    adapter = MockAgentAdapter(MockConfig(default="Echo: {input}", latency_ms=0))
    r = await adapter.send_message("hello world")
    assert r.content == "Echo: hello world"
    assert await adapter.health_check() is True


async def test_mock_adapter_keyword_reply_and_routing():
    from attest.adapters import MockAgentAdapter
    from attest.core.config_models import MockConfig

    adapter = MockAgentAdapter(MockConfig(
        default="default reply",
        replies={"tokyo": "Tokyo, Kyoto and Osaka are great."},
        latency_ms=0,
        handled_by="flights_agent",
        routing_path=["orchestrator", "flights_agent"],
    ))
    r = await adapter.send_message("Best places in Tokyo?")
    assert "Tokyo" in r.content
    assert r.handled_by == "flights_agent"
    assert r.routing_path == ["orchestrator", "flights_agent"]


def test_mock_adapter_created_from_yaml_config():
    from attest.adapters import create_adapter, MockAgentAdapter
    from attest.core.config_models import AgentConfig, MockConfig

    adapter = create_adapter(AgentConfig(type="mock", mock=MockConfig(default="hi")))
    assert isinstance(adapter, MockAgentAdapter)

