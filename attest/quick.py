"""Quick start helpers.

Makes it dead simple to start testing — no attest.yaml needed.
Users can get going with just a URL, or even just a Python function.

Usage:
    from attest.quick import test_agent

    # Just give a URL — we figure out the rest
    results = await test_agent("http://localhost:8000/chat", inputs=[
        "Hello",
        "What's your return policy?",
        "Track order #123",
    ])

    # Give a Python function
    results = await test_agent(my_agent_function, inputs=["Hello"])
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Union

from attest.adapters import create_adapter
from attest.adapters.auto_detect import detect_agent_api
from attest.adapters.callable_adapter import CallableAgentAdapter
from attest.adapters.http_rest import HttpAgentAdapter
from attest.core.config_models import AgentConfig
from attest.core.exceptions import AttestError
from attest.core.models import AgentResponse


async def quick_connect(
    agent: Union[str, Callable],
    **kwargs,
) -> Union[HttpAgentAdapter, CallableAgentAdapter]:
    """Connect to an agent with minimal configuration.

    Accepts either a URL string or a Python callable.
    For URLs, auto-detects the API format.

    Args:
        agent: URL string ("http://...") or a Python callable.

    Returns:
        Ready-to-use adapter.

    Raises:
        AttestError if we can't connect or detect the format.

    Examples:
        # From a URL (auto-detects API format)
        adapter = await quick_connect("http://localhost:8000/chat")

        # From a function
        adapter = await quick_connect(my_agent_fn)
    """
    if callable(agent) and not isinstance(agent, str):
        # It's a Python function — use callable adapter
        return CallableAgentAdapter(fn=agent, input_param=None)

    if isinstance(agent, str):
        # It's a URL — try to auto-detect
        config = await detect_agent_api(agent)
        if config:
            adapter = HttpAgentAdapter(config)
            await adapter.setup()
            return adapter

        # Auto-detect failed — try with basic defaults
        config = AgentConfig(type="http", endpoint=agent)
        adapter = HttpAgentAdapter(config)
        await adapter.setup()

        # Test if it works at all
        if await adapter.health_check():
            return adapter

        raise AttestError(
            f"Could not connect to agent at {agent}. "
            f"Make sure the agent is running and the URL is correct."
        )

    raise AttestError(
        f"Invalid agent: expected a URL string or callable, got {type(agent).__name__}"
    )


async def quick_test(
    agent: Union[str, Callable],
    inputs: List[str],
) -> List[AgentResponse]:
    """Quick smoke test — send messages to an agent and get responses.

    No evaluation, no assertions — just sends messages and shows what comes back.
    Good for a first check: "Is this agent even working?"

    Args:
        agent: URL string or Python callable.
        inputs: List of messages to send.

    Returns:
        List of AgentResponse objects.

    Example:
        responses = await quick_test("http://localhost:8000/chat", [
            "Hello",
            "What's your return policy?",
        ])
        for r in responses:
            print(f"  → {r.content[:100]}")
    """
    adapter = await quick_connect(agent)

    responses = []
    for message in inputs:
        try:
            response = await adapter.send_message(message)
            responses.append(response)
        except Exception as e:
            responses.append(AgentResponse(content=f"ERROR: {e}", latency_ms=0))

    if isinstance(adapter, HttpAgentAdapter):
        await adapter.teardown()

    return responses
