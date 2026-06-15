"""Example: test a LangGraph agent with ATTEST.

This uses a small mock LangGraph-style graph so it runs without API keys.
Swap `MockGraph` for your real compiled graph to test production code:

    from langgraph.prebuilt import create_react_agent
    graph = create_react_agent(model, tools)
    adapter = LangGraphAgentAdapter(graph)

Run:
    pip install -e ".[langgraph]"
    python examples/langgraph_agent.py
"""

import asyncio

from attest.adapters import LangGraphAgentAdapter
from attest.core.assertions import (
    assert_response_contains,
    assert_tool_called,
    assert_language_is,
    run_assertions,
)


# ---------------------------------------------------------------------------
# Mock LangGraph message objects + graph (ReAct-style message flow).
# ---------------------------------------------------------------------------
class AIMessage:
    type = "ai"

    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class ToolMessage:
    type = "tool"

    def __init__(self, content, tool_call_id):
        self.content = content
        self.tool_call_id = tool_call_id


class HumanMessage:
    type = "human"

    def __init__(self, content):
        self.content = content


class MockGraph:
    def invoke(self, state, config=None):
        return {
            "messages": [
                HumanMessage("What can I do in Tokyo?"),
                AIMessage(
                    content="",
                    tool_calls=[{"name": "lookup_activities", "args": {"city": "Tokyo"}, "id": "c1"}],
                ),
                ToolMessage("Senso-ji, Shibuya, teamLab", tool_call_id="c1"),
                AIMessage(content="In Tokyo you can visit Senso-ji temple, Shibuya, and teamLab."),
            ]
        }


async def main():
    adapter = LangGraphAgentAdapter(MockGraph())

    response = await adapter.send_message("What can I do in Tokyo?")

    assertions = [
        assert_response_contains("Tokyo"),
        assert_tool_called("lookup_activities"),
        assert_language_is("en"),
    ]
    results = run_assertions(response, assertions)

    print(f"Agent said: {response.content}")
    print(f"Tool calls: {[t.name for t in response.tool_calls]}\n")
    passed = sum(1 for r in results if r.passed)
    for r in results:
        icon = "PASS" if r.passed else "FAIL"
        print(f"  [{icon}] {r.name}  {r.message if not r.passed else ''}")
    print(f"\n{passed}/{len(results)} assertions passed.")


if __name__ == "__main__":
    asyncio.run(main())
