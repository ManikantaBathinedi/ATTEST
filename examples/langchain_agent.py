"""Example: test a LangChain agent with ATTEST.

This uses a small mock LangChain-style agent so it runs without API keys.
Swap `MockTravelAgent` for your real `AgentExecutor` to test production code.

Run:
    pip install -e ".[langchain]"
    python examples/langchain_agent.py
"""

import asyncio

from attest.adapters import LangChainAgentAdapter
from attest.core.assertions import (
    assert_response_contains,
    assert_tool_called,
    assert_latency_under,
    assert_no_pii,
    run_assertions,
)


# ---------------------------------------------------------------------------
# A mock agent that mimics a LangChain AgentExecutor result.
# Replace this with your real executor:
#     from langchain.agents import AgentExecutor
#     executor = AgentExecutor(agent=..., tools=..., return_intermediate_steps=True)
#     adapter = LangChainAgentAdapter(executor)
# ---------------------------------------------------------------------------
class _AgentAction:
    def __init__(self, tool, tool_input):
        self.tool = tool
        self.tool_input = tool_input


class MockTravelAgent:
    tools = [type("T", (), {"name": "search_flights", "description": "find flights"})()]

    def invoke(self, payload):
        return {
            "output": "I found a direct flight to Paris for around 450 USD on Air France.",
            "intermediate_steps": [
                (_AgentAction("search_flights", {"destination": "Paris"}), "AF123 450 USD"),
            ],
        }


async def main():
    adapter = LangChainAgentAdapter(MockTravelAgent())

    response = await adapter.send_message("Find me a flight to Paris")

    # Deterministic checks — no LLM needed, instant.
    assertions = [
        assert_response_contains("Paris"),
        assert_tool_called("search_flights"),
        assert_latency_under(5000),
        assert_no_pii(),
    ]
    results = run_assertions(response, assertions)

    print(f"Agent said: {response.content}\n")
    passed = sum(1 for r in results if r.passed)
    for r in results:
        icon = "PASS" if r.passed else "FAIL"
        print(f"  [{icon}] {r.name}  {r.message if not r.passed else ''}")
    print(f"\n{passed}/{len(results)} assertions passed.")


if __name__ == "__main__":
    asyncio.run(main())
