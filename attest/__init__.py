"""ATTEST — Agent Testing & Trust Evaluation Suite.

End-to-end testing framework for AI agents, multi-agent systems, A2A, and MCP.

Quick start:
    import attest

    @attest.test
    async def test_my_agent():
        result = await attest.run(
            input="Hello, how can you help?",
            agent="my_agent",
            evaluators=["correctness", "relevancy"],
        )
        assert result.passed
"""

from attest.version import __version__
from attest.core.models import (
    AgentResponse,
    AssertionResult,
    EvalScore,
    Message,
    RunSummary,
    Status,
    TestCase,
    TestResult,
    TokenUsage,
    ToolCall,
)
from attest.core.exceptions import AttestError

__all__ = [
    # Version
    "__version__",
    # Core models
    "AgentResponse",
    "AssertionResult",
    "EvalScore",
    "Message",
    "RunSummary",
    "Status",
    "TestCase",
    "TestResult",
    "TokenUsage",
    "ToolCall",
    # Exceptions
    "AttestError",
]
