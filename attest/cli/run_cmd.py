"""Implementation of `attest run` command.

This is the main command users will use. It:
1. Loads attest.yaml config
2. Discovers YAML scenario files
3. Filters by suite/tag if specified
4. Runs all tests through the engine
5. Prints results to console
6. Saves reports (JSON, HTML)
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from rich.console import Console

from attest.core.config import load_config
from attest.core.exceptions import AttestError
from attest.core.models import TestCase, TestResult
from attest.core.runner import TestRunner
from attest.core.scenario_loader import load_scenarios

console = Console()


async def run_tests(
    config_path: Optional[str] = None,
    suite_filter: Optional[str] = None,
    tag_filter: Optional[str] = None,
    verbose: bool = True,
    parallel: int = 1,
    profile: Optional[str] = None,
    return_results: bool = False,
    fail_on_regression: bool = False,
    enforce_gates: bool = False,
) -> Optional[List[TestResult]]:
    """Execute all test scenarios.

    This is the core of `attest run`. It ties everything together:
        config → scenarios → runner → results → reports

    Args:
        config_path: Path to attest.yaml (auto-detected if None).
        suite_filter: Only run tests from this suite name.
        tag_filter: Only run tests with this tag.
        verbose: Print detailed output.
        parallel: Max concurrent tests. 1 = sequential.
        profile: Environment profile (e.g. dev, staging, prod).
        return_results: If True, return list of TestResult instead of None.
        fail_on_regression: If True, exit non-zero when a test that passed in
            the previous run now fails/errors (regression gate for CI).
    """
    # Step 1: Load config
    try:
        config = load_config(config_path, profile=profile)
    except AttestError as e:
        console.print(f"[red]Error loading config:[/red] {e}")
        raise SystemExit(1)

    if not config.agents:
        console.print(
            "[yellow]No agents configured in attest.yaml.[/yellow]\n"
            "  Add an agent under the 'agents:' section, or run: [green]attest init[/green]"
        )
        raise SystemExit(1)

    # Step 2: Discover and load test scenarios
    scenarios_dir = config.tests.scenarios_dir
    test_cases = load_scenarios(directory=scenarios_dir)

    if not test_cases:
        console.print(
            f"[yellow]No test scenarios found in '{scenarios_dir}'.[/yellow]\n"
            "  Create YAML files in that directory, or run: [green]attest init[/green]"
        )
        raise SystemExit(1)

    # Step 3: Apply filters
    if suite_filter:
        test_cases = [tc for tc in test_cases if tc.suite == suite_filter]
        if not test_cases:
            console.print(f"[yellow]No tests found for suite '{suite_filter}'.[/yellow]")
            raise SystemExit(1)

    if tag_filter:
        test_cases = [tc for tc in test_cases if tag_filter in tc.tags]
        if not test_cases:
            console.print(f"[yellow]No tests found with tag '{tag_filter}'.[/yellow]")
            raise SystemExit(1)

    # Step 4: Run tests
    runner = TestRunner(config)
    summary = await runner.run(test_cases, verbose=verbose, parallel=parallel)

    # Step 5: Save reports
    output_dir = Path(config.reporting.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # JSON report (always)
    json_path = output_dir / "results.json"
    json_path.write_text(
        summary.model_dump_json(indent=2),
        encoding="utf-8",
    )

    # HTML report
    from attest.reporting.html_report import generate_html_report

    html_path = output_dir / "report.html"
    generate_html_report(summary, output_path=str(html_path))

    # JUnit XML report (for CI/CD)
    from attest.reporting.junit_xml import generate_junit_xml

    junit_path = output_dir / "junit.xml"
    generate_junit_xml(summary, output_path=str(junit_path))

    # Markdown report (for PR comments / CI job summary) — diff vs previous run
    from attest.reporting.markdown_report import generate_markdown_report

    previous = _load_previous_summary(output_dir)
    md_path = output_dir / "summary.md"
    generate_markdown_report(summary, output_path=str(md_path), previous=previous)

    if verbose:
        console.print(f"\n  [dim]JSON report:  {json_path}[/dim]")
        console.print(f"  [dim]HTML report:  {html_path}[/dim]")
        console.print(f"  [dim]JUnit XML:    {junit_path}[/dim]")
        console.print(f"  [dim]Markdown:     {md_path}[/dim]")
        console.print(f"  [cyan]Open the HTML report in your browser to see visual results.[/cyan]")

    # Step 6: Regression gate — fail if any test went pass -> fail/error
    if fail_on_regression and previous is not None:
        regressions = _find_regressions(summary, previous)
        if regressions:
            console.print(
                f"\n[red]\u274c Regression gate: {len(regressions)} test(s) regressed "
                f"(were passing, now failing):[/red]"
            )
            for name in regressions:
                console.print(f"  [red]- {name}[/red]")
            if not return_results:
                raise SystemExit(2)

    # Step 6b: Notifications (Slack/Teams/generic webhook)
    try:
        from attest.utils.notify import maybe_notify
        maybe_notify(config.notify, summary, previous)
    except Exception as e:  # never let notify break a run
        if verbose:
            console.print(f"  [dim]Notification skipped: {e}[/dim]")

    # Step 6c: Quality gates — enforce configured thresholds (CI)
    if enforce_gates:
        from attest.core.gates import evaluate_gates, gates_are_configured
        if not gates_are_configured(config.gates):
            console.print(
                "[yellow]--gate was set but no gates are configured in attest.yaml "
                "(gates: min_pass_rate, max_p95_latency_ms, ...). Skipping.[/yellow]"
            )
        else:
            passed, violations = evaluate_gates(summary, config.gates)
            if passed:
                console.print("\n[green]\u2705 Quality gates passed.[/green]")
            else:
                console.print(f"\n[red]\u274c Quality gate failed ({len(violations)} violation(s)):[/red]")
                for v in violations:
                    console.print(f"  [red]- {v}[/red]")
                if not return_results:
                    raise SystemExit(3)

    # Exit with non-zero if any tests failed
    if summary.failed > 0 or summary.errors > 0:
        if not return_results:
            raise SystemExit(1)

    if return_results:
        return summary.results


def _load_previous_summary(output_dir):
    """Load the most recent prior run from history/ for regression diffing.

    Returns None if no prior run exists.
    """
    try:
        import json
        from attest.core.models import RunSummary

        history_dir = output_dir / "history"
        if not history_dir.exists():
            return None
        runs = sorted(history_dir.glob("run_*.json"), reverse=True)
        if not runs:
            return None
        data = json.loads(runs[0].read_text(encoding="utf-8"))
        return RunSummary(**data)
    except Exception:
        return None


def _find_regressions(summary, previous) -> List[str]:
    """Return scenario names that were passing previously and now fail/error."""
    from attest.core.models import Status

    prev_status = {
        f"{r.agent}::{r.scenario}": r.status for r in previous.results
    }
    regressed: List[str] = []
    for r in summary.results:
        key = f"{r.agent}::{r.scenario}"
        was = prev_status.get(key)
        if was == Status.PASSED and r.status in (Status.FAILED, Status.ERROR):
            regressed.append(r.scenario)
    return regressed
