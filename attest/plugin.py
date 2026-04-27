"""Pytest plugin for ATTEST.

Provides fixtures and markers so teams can write ATTEST tests using pytest.

Usage:
    # tests/test_my_agent.py
    import pytest

    @pytest.mark.agent_test
    def test_greeting(attest_runner):
        result = attest_runner.run_sync(
            input="Hello!",
            assertions=[{"response_not_empty": True}],
        )
        assert result.passed

Run with:
    pytest tests/ -v
"""

from __future__ import annotations

import asyncio
from typing import Optional

import pytest

from attest.core.config import load_config
from attest.core.config_models import AttestConfig
from attest.core.models import TestCase, TestResult
from attest.core.runner import TestRunner


# ---------------------------------------------------------------------------
# Pytest options
# ---------------------------------------------------------------------------


def pytest_addoption(parser):
    """Add ATTEST CLI options to pytest."""
    parser.addoption(
        "--attest-config",
        action="store",
        default=None,
        help="Path to attest.yaml config file",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def attest_config(request) -> AttestConfig:
    """Load ATTEST config (session-scoped — loaded once for all tests)."""
    config_path = request.config.getoption("--attest-config")
    return load_config(config_path)


@pytest.fixture(scope="session")
def attest_runner(attest_config) -> "SyncTestRunner":
    """Provide a synchronous test runner for use in pytest tests."""
    return SyncTestRunner(attest_config)


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "agent_test: marks a test as an ATTEST agent test",
    )


# ---------------------------------------------------------------------------
# Sync wrapper for the async runner
# ---------------------------------------------------------------------------


class SyncTestRunner:
    """Wraps the async TestRunner for use in synchronous pytest tests.

    Usage:
        def test_something(attest_runner):
            result = attest_runner.run_sync(
                input="Hello",
                agent="my_agent",
                assertions=[{"response_not_empty": True}],
            )
            assert result.passed
    """

    def __init__(self, config: AttestConfig):
        self._config = config
        self._runner = TestRunner(config)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        """Get or create an event loop."""
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop

    def run_sync(
        self,
        input: str,
        agent: str = "default",
        assertions: list = None,
        evaluators: list = None,
        expected_output: str = None,
        context: str = None,
        name: str = None,
    ) -> TestResult:
        """Run a single test synchronously.

        Args:
            input: Message to send to the agent.
            agent: Agent name from config.
            assertions: List of assertion dicts.
            evaluators: List of evaluator specs.
            expected_output: Expected answer (for correctness eval).
            context: Context/docs (for groundedness eval).
            name: Test name (auto-generated if None).

        Returns:
            TestResult with pass/fail, scores, and conversation.
        """
        test_case = TestCase(
            name=name or f"pytest_{hash(input) % 10000:04d}",
            input=input,
            agent=agent,
            assertions=assertions or [],
            evaluators=evaluators or [],
            expected_output=expected_output,
            context=context,
        )

        loop = self._get_loop()
        summary = loop.run_until_complete(
            self._runner.run([test_case], verbose=False)
        )

        return summary.results[0] if summary.results else TestResult(
            scenario=test_case.name,
        )
