"""Test runner — the engine that orchestrates everything.

The runner takes a list of TestCases and for each one:
1. Picks the right adapter based on agent name in config
2. Sends the input message to the agent
3. Runs deterministic assertions (instant, free)
4. Runs LLM evaluators (async, costs tokens)
5. Determines pass/fail
6. Collects everything into a TestResult
7. Aggregates all results into a RunSummary

Usage:
    from attest.core.runner import TestRunner

    runner = TestRunner(config)
    summary = await runner.run(test_cases)
    print(f"Pass rate: {summary.pass_rate:.0%}")
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from rich.console import Console
from rich.table import Table

from attest.adapters import create_adapter
from attest.adapters.base import BaseAgentAdapter
from attest.core.assertions import resolve_assertions, run_assertions
from attest.core.config_models import AttestConfig
from attest.core.exceptions import AdapterError, AttestError, EvaluationError
from attest.core.models import (
    AgentResponse,
    EvalScore,
    Message,
    RunSummary,
    Status,
    TestCase,
    TestResult,
)
from attest.evaluation.interface import EvaluationInput
from attest.evaluation.registry import EvaluatorRegistry

console = Console()


class TestRunner:
    """Orchestrates test execution: adapter → assertions → evaluators → results.

    The runner is the core of ATTEST. All entry points (CLI, pytest, dashboard)
    use this class to actually run tests.
    """

    def __init__(
        self,
        config: AttestConfig,
        registry: Optional[EvaluatorRegistry] = None,
    ):
        self._config = config
        self._registry = registry or EvaluatorRegistry(
            model=config.evaluation.judge.model
        )
        self._adapters: Dict[str, BaseAgentAdapter] = {}

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run(
        self,
        test_cases: List[TestCase],
        verbose: bool = True,
    ) -> RunSummary:
        """Run all test cases and return aggregated results.

        Args:
            test_cases: List of tests to run.
            verbose: Print progress to console.

        Returns:
            RunSummary with all results and aggregate stats.
        """
        summary = RunSummary(
            run_id=f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        )
        start_time = time.perf_counter()

        if verbose:
            console.print(f"\n[bold]ATTEST[/bold] — Running {len(test_cases)} test(s)\n")

        # Setup adapters
        await self._setup_adapters(test_cases)

        try:
            for i, test_case in enumerate(test_cases, 1):
                if verbose:
                    with console.status(
                        f"  [{i}/{len(test_cases)}] {test_case.name}...",
                        spinner="dots",
                    ):
                        result = await self._run_single(test_case)
                    # Print result on same line after spinner clears
                    console.print(
                        f"  [{i}/{len(test_cases)}] {test_case.name}...", end=" "
                    )
                    self._print_result(result)
                else:
                    result = await self._run_single(test_case)

                summary.add_result(result)

        finally:
            # Always cleanup adapters
            await self._teardown_adapters()

        summary.duration_seconds = time.perf_counter() - start_time

        if verbose:
            self._print_summary(summary)

        return summary

    # ------------------------------------------------------------------
    # Run a single test case
    # ------------------------------------------------------------------

    async def _run_single(self, test_case: TestCase) -> TestResult:
        """Run a single test case through the full pipeline."""
        # Route to conversation runner if it's a multi-turn test
        if test_case.type == "conversation" and test_case.conversation_script:
            return await self._run_conversation(test_case)

        # Route to simulation runner if it's a simulation test
        if test_case.type == "simulation" and test_case.persona:
            return await self._run_simulation(test_case)

        return await self._run_single_turn(test_case)

    async def _run_conversation(self, test_case: TestCase) -> TestResult:
        """Run a multi-turn conversation test with evaluators."""
        result = TestResult(
            scenario=test_case.name,
            suite=test_case.suite,
            agent=test_case.agent,
            tags=test_case.tags,
        )
        start_time = time.perf_counter()

        adapter = self._get_adapter(test_case.agent)
        if adapter is None:
            result.status = Status.ERROR
            result.error = f"No adapter found for agent '{test_case.agent}'"
            return result

        try:
            from attest.conversation.flow import run_conversation

            conv_result = await run_conversation(
                adapter=adapter,
                script=test_case.conversation_script,
                name=test_case.name,
            )

            # Map conversation result to TestResult
            result.messages = conv_result.messages
            result.latency_ms = conv_result.total_latency_ms

            # Collect all assertion results from all turns
            for turn in conv_result.turns:
                for a in turn.assertions:
                    a.name = f"turn{turn.turn_number}:{a.name}"
                    result.assertions.append(a)

            # Run evaluators on the LAST agent response (overall quality)
            if test_case.evaluators and conv_result.turns:
                last_turn = conv_result.turns[-1]
                # Build a mock response for the evaluator
                mock_response = AgentResponse(
                    content=last_turn.agent_response,
                    latency_ms=last_turn.latency_ms,
                )
                # Build evaluation input with full conversation as context
                full_conversation = "\n".join(
                    f"{m.role}: {m.content}" for m in conv_result.messages
                )
                eval_input = EvaluationInput(
                    query=conv_result.turns[0].user_message,
                    response=last_turn.agent_response,
                    context=full_conversation,
                    expected=test_case.expected_output,
                    conversation=conv_result.messages,
                )
                eval_scores = await self._run_evaluators_with_input(
                    test_case, eval_input
                )
                result.scores = {s.name: s for s in eval_scores}

            # Determine status
            conv_passed = conv_result.passed
            evals_passed = all(s.passed for s in result.scores.values()) if result.scores else True
            result.status = Status.PASSED if (conv_passed and evals_passed) else Status.FAILED

        except Exception as e:
            result.status = Status.ERROR
            result.error = str(e)

        result.duration_ms = (time.perf_counter() - start_time) * 1000
        return result

    async def _run_simulation(self, test_case: TestCase) -> TestResult:
        """Run a user simulation test — LLM plays user persona vs agent.

        Pipeline:
            1. Get adapter for the agent
            2. UserSimulator drives a multi-turn conversation
            3. Run evaluators on the full conversation
            4. Goal achievement check as extra pass/fail signal
        """
        result = TestResult(
            scenario=test_case.name,
            suite=test_case.suite,
            agent=test_case.agent,
            tags=test_case.tags,
        )
        start_time = time.perf_counter()

        adapter = self._get_adapter(test_case.agent)
        if adapter is None:
            result.status = Status.ERROR
            result.error = f"No adapter found for agent '{test_case.agent}'"
            return result

        try:
            from attest.simulation.user_simulator import UserSimulator

            model = self._config.evaluation.judge.model
            simulator = UserSimulator(model=model)

            sim_result = await simulator.run(
                adapter=adapter,
                persona=test_case.persona or "A typical end user",
                goal=test_case.input,  # 'input' field doubles as the goal
                max_turns=test_case.max_turns or 8,
                name=test_case.name,
                first_message=test_case.input if test_case.input else None,
            )

            # Map simulation result to TestResult
            result.messages = sim_result.messages
            result.latency_ms = sim_result.total_latency_ms

            # Add goal achievement as an assertion result
            from attest.core.models import AssertionResult
            result.assertions.append(
                AssertionResult(
                    name="goal_achieved",
                    passed=sim_result.goal_achieved,
                    message=sim_result.summary or (
                        "Goal achieved" if sim_result.goal_achieved
                        else "Goal not achieved"
                    ),
                    expected="Goal achieved",
                    actual=f"{'Achieved' if sim_result.goal_achieved else 'Not achieved'} "
                           f"in {sim_result.turn_count} turns ({sim_result.stop_reason})",
                )
            )

            # Run evaluators on the full conversation
            if test_case.evaluators and sim_result.turns:
                last_turn = sim_result.turns[-1]
                full_conversation = "\n".join(
                    f"{m.role}: {m.content}" for m in sim_result.messages
                )
                eval_input = EvaluationInput(
                    query=test_case.input,
                    response=last_turn.agent_response,
                    context=full_conversation,
                    expected=test_case.expected_output,
                    conversation=sim_result.messages,
                )
                eval_scores = await self._run_evaluators_with_input(
                    test_case, eval_input
                )
                result.scores = {s.name: s for s in eval_scores}

            # Determine status
            goal_ok = sim_result.goal_achieved
            evals_ok = all(s.passed for s in result.scores.values()) if result.scores else True
            result.status = Status.PASSED if (goal_ok and evals_ok) else Status.FAILED

        except Exception as e:
            result.status = Status.ERROR
            result.error = str(e)

        result.duration_ms = (time.perf_counter() - start_time) * 1000
        return result

    async def _run_single_turn(self, test_case: TestCase) -> TestResult:
        """Run a single-turn test case through the full pipeline.

        Pipeline:
            1. Get adapter for the agent
            2. Send message → AgentResponse
            3. Run assertions → AssertionResult[]
            4. Run evaluators → EvalScore[]
            5. Determine status (pass/fail)
            6. Build TestResult
        """
        result = TestResult(
            scenario=test_case.name,
            suite=test_case.suite,
            agent=test_case.agent,
            tags=test_case.tags,
        )
        start_time = time.perf_counter()

        # Step 1: Get the adapter
        adapter = self._get_adapter(test_case.agent)
        if adapter is None:
            result.status = Status.ERROR
            result.error = f"No adapter found for agent '{test_case.agent}'"
            return result

        # Step 2: Send message to agent
        try:
            response = await adapter.send_message(
                message=test_case.input,
                conversation_history=test_case.conversation_history or None,
            )
        except AdapterError as e:
            result.status = Status.ERROR
            result.error = str(e)
            result.duration_ms = (time.perf_counter() - start_time) * 1000
            return result

        # Record the conversation
        result.messages = [
            Message(role="user", content=test_case.input),
            Message(role="assistant", content=response.content),
        ]
        result.tool_calls = response.tool_calls
        result.latency_ms = response.latency_ms
        result.token_usage = response.token_usage

        # Step 3: Run deterministic assertions (instant, free)
        if test_case.assertions:
            assertion_fns = resolve_assertions(test_case.assertions)
            result.assertions = run_assertions(response, assertion_fns)

        # Step 4: Run LLM evaluators (async, costs tokens)
        if test_case.evaluators:
            eval_scores = await self._run_evaluators(test_case, response)
            result.scores = {s.name: s for s in eval_scores}

        # Step 5: Determine overall status
        result.status = self._determine_status(result)

        # Step 6: Calculate timing and cost
        result.duration_ms = (time.perf_counter() - start_time) * 1000

        return result

    # ------------------------------------------------------------------
    # Evaluator execution
    # ------------------------------------------------------------------

    async def _run_evaluators(
        self, test_case: TestCase, response: AgentResponse
    ) -> List[EvalScore]:
        """Run all configured evaluators for a test case."""
        scores = []

        # Resolve evaluator specs (strings/dicts) into evaluator instances
        try:
            evaluators = self._registry.resolve_evaluators(
                test_case.evaluators,
                default_threshold=0.7,
            )
        except KeyError as e:
            scores.append(
                EvalScore(
                    name="registry_error",
                    score=0.0,
                    passed=False,
                    threshold=0.0,
                    reason=str(e),
                )
            )
            return scores

        # Build the standard evaluation input
        eval_input = EvaluationInput(
            query=test_case.input,
            response=response.content,
            context=test_case.context,
            expected=test_case.expected_output or test_case.ground_truth,
            tool_calls=response.tool_calls,
            conversation=test_case.conversation_history or [],
        )

        # Run each evaluator
        for evaluator in evaluators:
            try:
                eval_result = await evaluator.evaluate(eval_input)
                scores.append(
                    EvalScore(
                        name=eval_result.name,
                        score=eval_result.score,
                        passed=eval_result.passed,
                        threshold=eval_result.threshold,
                        reason=eval_result.reason,
                        backend=eval_result.metadata.get("backend", "builtin"),
                        raw_score=eval_result.raw_score,
                    )
                )
            except EvaluationError as e:
                scores.append(
                    EvalScore(
                        name=evaluator.name,
                        score=0.0,
                        passed=False,
                        threshold=evaluator.threshold,
                        reason=f"Evaluation error: {e}",
                    )
                )
            except Exception as e:
                scores.append(
                    EvalScore(
                        name=evaluator.name,
                        score=0.0,
                        passed=False,
                        threshold=evaluator.threshold,
                        reason=f"Unexpected error: {e}",
                    )
                )

        return scores

    async def _run_evaluators_with_input(
        self, test_case: TestCase, eval_input: EvaluationInput
    ) -> List[EvalScore]:
        """Run evaluators with a pre-built EvaluationInput (for multi-turn)."""
        scores = []

        try:
            evaluators = self._registry.resolve_evaluators(
                test_case.evaluators,
                default_threshold=0.7,
            )
        except KeyError as e:
            scores.append(
                EvalScore(name="registry_error", score=0.0, passed=False, threshold=0.0, reason=str(e))
            )
            return scores

        for evaluator in evaluators:
            try:
                eval_result = await evaluator.evaluate(eval_input)
                scores.append(
                    EvalScore(
                        name=eval_result.name,
                        score=eval_result.score,
                        passed=eval_result.passed,
                        threshold=eval_result.threshold,
                        reason=eval_result.reason,
                        backend=eval_result.metadata.get("backend", "builtin"),
                        raw_score=eval_result.raw_score,
                    )
                )
            except Exception as e:
                scores.append(
                    EvalScore(
                        name=evaluator.name, score=0.0, passed=False,
                        threshold=evaluator.threshold, reason=f"Error: {e}",
                    )
                )

        return scores

    # ------------------------------------------------------------------
    # Status determination
    # ------------------------------------------------------------------

    def _determine_status(self, result: TestResult) -> Status:
        """Determine if a test passed or failed.

        Rules:
            - ERROR if we already have an error
            - FAILED if any assertion failed
            - FAILED if any evaluator failed (score below threshold)
            - PASSED otherwise
        """
        if result.error:
            return Status.ERROR

        # Check assertions
        if result.assertions and not all(a.passed for a in result.assertions):
            return Status.FAILED

        # Check evaluators
        if result.scores and not all(s.passed for s in result.scores.values()):
            return Status.FAILED

        return Status.PASSED

    # ------------------------------------------------------------------
    # Adapter management
    # ------------------------------------------------------------------

    def _get_adapter(self, agent_name: str) -> Optional[BaseAgentAdapter]:
        """Get the adapter for a named agent."""
        # Try exact name
        if agent_name in self._adapters:
            return self._adapters[agent_name]

        # Try "default" — first agent in config
        if agent_name == "default" and self._adapters:
            return next(iter(self._adapters.values()))

        return None

    async def _setup_adapters(self, test_cases: List[TestCase]) -> None:
        """Create and setup adapters for all agents used in the test cases."""
        # Find all unique agent names
        agent_names = set()
        for tc in test_cases:
            agent_names.add(tc.agent)

        for name in agent_names:
            if name in self._adapters:
                continue

            # "default" means first agent in config
            if name == "default" and self._config.agents:
                actual_name = next(iter(self._config.agents))
            else:
                actual_name = name

            if actual_name not in self._config.agents:
                continue  # Will be caught as error when test runs

            try:
                agent_config = self._config.agents[actual_name]
                adapter = create_adapter(agent_config)
                await adapter.setup()
                self._adapters[name] = adapter
                if name != actual_name:
                    self._adapters[actual_name] = adapter
            except Exception:
                pass  # Error will be reported per test case

    async def _teardown_adapters(self) -> None:
        """Cleanup all adapters."""
        seen = set()
        for adapter in self._adapters.values():
            adapter_id = id(adapter)
            if adapter_id not in seen:
                seen.add(adapter_id)
                try:
                    await adapter.teardown()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Console output
    # ------------------------------------------------------------------

    def _print_result(self, result: TestResult) -> None:
        """Print a single test result to console."""
        if result.status == Status.PASSED:
            console.print("[green]✅ PASSED[/green]", end="")
        elif result.status == Status.FAILED:
            console.print("[red]❌ FAILED[/red]", end="")
        else:
            console.print("[yellow]⚠️  ERROR[/yellow]", end="")

        # Show scores if any
        if result.scores:
            score_parts = []
            for name, score in result.scores.items():
                color = "green" if score.passed else "red"
                score_parts.append(f"[{color}]{name}={score.score:.2f}[/{color}]")
            console.print(f"  ({', '.join(score_parts)})", end="")

        # Show assertion failures
        failed_assertions = [a for a in result.assertions if not a.passed]
        if failed_assertions:
            for a in failed_assertions:
                console.print(f"\n      [red]↳ {a.name}: {a.message}[/red]", end="")

        # Show error
        if result.error:
            console.print(f"\n      [yellow]↳ {result.error}[/yellow]", end="")

        console.print(f"  [dim]({result.latency_ms:.0f}ms)[/dim]")

    def _print_summary(self, summary: RunSummary) -> None:
        """Print the final test run summary."""
        console.print()

        # Build summary table
        table = Table(title="ATTEST Run Summary", show_lines=False)
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")

        table.add_row("Total Tests", str(summary.total))
        table.add_row("Passed", f"[green]{summary.passed}[/green]")
        table.add_row("Failed", f"[red]{summary.failed}[/red]" if summary.failed else "0")
        table.add_row("Errors", f"[yellow]{summary.errors}[/yellow]" if summary.errors else "0")
        table.add_row("Pass Rate", f"{summary.pass_rate:.0%}")
        table.add_row("Overall Score", f"{summary.overall_score:.2f}")
        table.add_row("Duration", f"{summary.duration_seconds:.1f}s")
        table.add_row("Est. Cost", f"${summary.total_cost:.4f}")

        console.print(table)
