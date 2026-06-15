"""Unit tests for the additional framework adapters
(CrewAI, AutoGen, OpenAI Assistants, MCP).

All use lightweight mocks — no real frameworks or servers needed.

Run:
    pytest tests/unit/test_adapters_extra.py -v
"""

import pytest

from attest.adapters import (
    CrewAIAgentAdapter,
    AutoGenAgentAdapter,
    OpenAIAssistantAdapter,
    MCPAgentAdapter,
    create_adapter,
)
from attest.core.config_models import AgentConfig
from attest.core.exceptions import AdapterError, ConfigError


# ---------------------------------------------------------------------------
# CrewAI
# ---------------------------------------------------------------------------
class _CrewOutput:
    def __init__(self, raw):
        self.raw = raw


class _MockCrew:
    def kickoff(self, inputs=None):
        assert inputs and "topic" in inputs
        return _CrewOutput(f"Report about {inputs['topic']}")


async def test_crewai_extracts_raw_output():
    adapter = CrewAIAgentAdapter(_MockCrew(), input_key="topic")
    r = await adapter.send_message("space travel")
    assert r.content == "Report about space travel"


def test_crewai_rejects_non_crew():
    with pytest.raises(AdapterError):
        CrewAIAgentAdapter(object())


# ---------------------------------------------------------------------------
# AutoGen
# ---------------------------------------------------------------------------
class _Msg:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _TaskResult:
    def __init__(self, messages):
        self.messages = messages


class _MockAutoGenAgent:
    async def run(self, task=None):
        return _TaskResult([
            _Msg("thinking...", tool_calls=[{"name": "calc", "arguments": {"x": 1}}]),
            _Msg("The answer is 42."),
        ])


async def test_autogen_extracts_final_and_tools():
    adapter = AutoGenAgentAdapter(_MockAutoGenAgent())
    r = await adapter.send_message("what is the answer?")
    assert r.content == "The answer is 42."
    assert any(t.name == "calc" for t in r.tool_calls)


def test_autogen_rejects_non_agent():
    with pytest.raises(AdapterError):
        AutoGenAgentAdapter(object())


# ---------------------------------------------------------------------------
# OpenAI Assistants
# ---------------------------------------------------------------------------
class _Text:
    def __init__(self, value):
        self.value = value


class _Block:
    def __init__(self, value):
        self.text = _Text(value)


class _AsstMsg:
    def __init__(self, role, value):
        self.role = role
        self.content = [_Block(value)]


class _MsgList:
    def __init__(self, data):
        self.data = data


class _Run:
    def __init__(self):
        self.id = "run_1"
        self.status = "completed"
        self.usage = type("U", (), {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8})()


class _Messages:
    def create(self, thread_id=None, role=None, content=None):
        return None

    def list(self, thread_id=None, order=None, limit=None):
        return _MsgList([_AsstMsg("assistant", "Hello from the assistant.")])


class _Runs:
    def create(self, thread_id=None, assistant_id=None):
        return _Run()

    def retrieve(self, thread_id=None, run_id=None):
        return _Run()

    def cancel(self, thread_id=None, run_id=None):
        return None


class _Threads:
    def __init__(self):
        self.messages = _Messages()
        self.runs = _Runs()

    def create(self, messages=None):
        return type("T", (), {"id": "thread_1"})()


class _Assistants:
    def retrieve(self, assistant_id):
        return True


class _Beta:
    def __init__(self):
        self.threads = _Threads()
        self.assistants = _Assistants()


class _MockOpenAI:
    def __init__(self):
        self.beta = _Beta()


async def test_openai_assistant_returns_text_and_usage():
    adapter = OpenAIAssistantAdapter(_MockOpenAI(), assistant_id="asst_1")
    r = await adapter.send_message("hi")
    assert r.content == "Hello from the assistant."
    assert r.token_usage.total_tokens == 8


def test_openai_assistant_rejects_non_client():
    with pytest.raises(AdapterError):
        OpenAIAssistantAdapter(object(), assistant_id="asst_1")


# ---------------------------------------------------------------------------
# MCP — construction & config wiring (no live server)
# ---------------------------------------------------------------------------
def test_mcp_requires_command_or_url():
    with pytest.raises(AdapterError):
        MCPAgentAdapter()


def test_mcp_constructs_with_command():
    adapter = MCPAgentAdapter(command="python", args=["server.py"], default_tool="search")
    assert adapter._default_tool == "search"


def test_create_adapter_builds_mcp_from_yaml():
    cfg = AgentConfig(type="mcp", command="python", args=["server.py"], default_tool="search")
    adapter = create_adapter(cfg)
    assert isinstance(adapter, MCPAgentAdapter)


def test_create_adapter_rejects_inprocess_types_from_yaml():
    for t in ("langchain", "crewai", "autogen", "openai_assistant"):
        with pytest.raises(ConfigError):
            create_adapter(AgentConfig(type=t))
