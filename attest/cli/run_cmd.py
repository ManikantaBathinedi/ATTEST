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
from typing import Optional

from rich.console import Console

from attest.core.config import load_config
from attest.core.exceptions import AttestError
from attest.core.models import TestCase
from attest.core.runner import TestRunner
from attest.core.scenario_loader import load_scenarios

console = Console()


async def run_tests(
    config_path: Optional[str] = None,
    suite_filter: Optional[str] = None,
    tag_filter: Optional[str] = None,
    verbose: bool = True,
) -> None:
    """Execute all test scenarios.

    This is the core of `attest run`. It ties everything together:
        config → scenarios → runner → results → reports

    Args:
        config_path: Path to attest.yaml (auto-detected if None).
        suite_filter: Only run tests from this suite name.
        tag_filter: Only run tests with this tag.
        verbose: Print detailed output.
    """
    # Step 1: Load config
    try:
        config = load_config(config_path)
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
    summary = await runner.run(test_cases, verbose=verbose)

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

    if verbose:
        console.print(f"\n  [dim]JSON report:  {json_path}[/dim]")
        console.print(f"  [dim]HTML report:  {html_path}[/dim]")
        console.print(f"  [dim]JUnit XML:    {junit_path}[/dim]")
        console.print(f"  [cyan]Open the HTML report in your browser to see visual results.[/cyan]")

    # Exit with non-zero if any tests failed
    if summary.failed > 0 or summary.errors > 0:
        raise SystemExit(1)
