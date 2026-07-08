"""ATTEST CLI — the command-line interface.

This is the entry point when users type `attest` in the terminal.
Built with Typer for auto-completion, help text, and colored output.

Commands:
    attest init [--preset http|foundry]  — Generate config + sample tests
    attest run [--config path]           — Run all tests
    attest version                       — Show version
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(
    name="attest",
    help="ATTEST — Agent Testing & Trust Evaluation Suite",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()


# ---------------------------------------------------------------------------
# attest version
# ---------------------------------------------------------------------------


@app.command()
def version():
    """Show ATTEST version."""
    from attest.version import __version__

    console.print(f"[bold]ATTEST[/bold] v{__version__}")


@app.command()
def examples(
    run: bool = typer.Option(False, "--run", help="Run the offline example tests against the built-in mock agent."),
):
    """List (or run) the bundled example tests.

    ATTEST ships example scenarios for every test type in
    ``tests/scenarios/example_*.yaml``. The single-turn, JSON, multi-turn,
    safety, and security examples run offline against the built-in ``mock``
    agent — no API key needed. The tool-call, RAG, simulation, and routing
    examples are templates you point at your own agent.
    """
    from pathlib import Path

    scen_dir = Path("tests/scenarios")
    files = sorted(scen_dir.glob("example_*.yaml")) if scen_dir.exists() else []
    if not files:
        console.print("[yellow]No example_*.yaml files found in tests/scenarios.[/yellow]")
        return

    console.print(f"\n[bold]ATTEST examples[/bold] — {len(files)} example suite(s):\n")
    for f in files:
        console.print(f"  • {f.name}")

    if not run:
        console.print("\nRun the offline examples with: [cyan]attest examples --run[/cyan]")
        console.print("Or open the dashboard to explore them visually: [cyan]attest serve[/cyan]\n")
        return

    # Run only the mock-backed (offline) examples.
    import asyncio
    from attest.core.config import load_config
    from attest.core.runner import TestRunner
    from attest.core.scenario_loader import load_scenarios

    config = load_config()
    scenarios = load_scenarios(directory=config.tests.scenarios_dir)
    runnable = [t for t in scenarios if t.agent == "mock_agent"]
    if not runnable:
        console.print("[yellow]No offline (mock_agent) examples to run.[/yellow]")
        return

    console.print(f"\nRunning {len(runnable)} offline example test(s)...\n")
    runner = TestRunner(config)
    summary = asyncio.run(runner.run(runnable, verbose=True))
    console.print(f"\n[bold]Passed {summary.passed}/{summary.total}[/bold]\n")


# ---------------------------------------------------------------------------
# attest init
# ---------------------------------------------------------------------------


@app.command()
def init(
    preset: str = typer.Option(
        "http",
        help="Template to use: http, foundry, minimal",
    ),
    directory: str = typer.Option(
        ".",
        help="Directory to create files in",
    ),
):
    """Generate attest.yaml, sample tests, and .env template.

    Presets:
        http     — For agents with an HTTP API (most common)
        foundry  — For Azure Foundry agents
        minimal  — Bare minimum config
    """
    from attest.cli.init_cmd import run_init

    run_init(preset=preset, directory=directory)


# ---------------------------------------------------------------------------
# attest ci — scaffold a CI/CD pipeline template
# ---------------------------------------------------------------------------


@app.command()
def ci(
    provider: str = typer.Option(
        "github",
        "--provider",
        help="CI provider: github or azure",
    ),
    directory: str = typer.Option(
        ".",
        help="Repository root to scaffold the CI file into.",
    ),
):
    """Scaffold a CI/CD pipeline that runs ATTEST on every push / PR.

    Examples:
        attest ci --provider github   — writes .github/workflows/attest.yml
        attest ci --provider azure    — writes azure-pipelines-attest.yml
    """
    from pathlib import Path

    templates_dir = Path(__file__).resolve().parent.parent.parent / "templates" / "ci"
    repo = Path(directory)

    provider = provider.lower()
    if provider == "github":
        src = templates_dir / "github-actions-attest.yml"
        dest = repo / ".github" / "workflows" / "attest.yml"
    elif provider == "azure":
        src = templates_dir / "azure-pipelines-attest.yml"
        dest = repo / "azure-pipelines-attest.yml"
    else:
        console.print(f"[red]Unknown provider '{provider}'. Use 'github' or 'azure'.[/red]")
        raise typer.Exit(1)

    if not src.exists():
        console.print(f"[red]Template not found: {src}[/red]")
        raise typer.Exit(1)

    if dest.exists():
        console.print(f"[yellow]File already exists, not overwriting:[/yellow] {dest}")
        raise typer.Exit(1)

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    console.print(f"[green]Created[/green] {dest}")
    console.print("[dim]Remember to set AZURE_API_KEY (and optional AZURE_API_BASE / OPENAI_API_KEY) as CI secrets.[/dim]")


# ---------------------------------------------------------------------------
# attest run
# ---------------------------------------------------------------------------


@app.command()
def run(
    config: Optional[str] = typer.Option(
        None,
        "--config", "-c",
        help="Path to attest.yaml. Auto-detected if not specified.",
    ),
    suite: Optional[str] = typer.Option(
        None,
        "--suite", "-s",
        help="Run only tests from a specific suite name.",
    ),
    tag: Optional[str] = typer.Option(
        None,
        "--tag", "-t",
        help="Run only tests with a specific tag.",
    ),
    verbose: bool = typer.Option(
        True,
        "--verbose/--quiet",
        help="Show detailed output.",
    ),
    parallel: int = typer.Option(
        1,
        "--parallel", "-p",
        help="Max concurrent tests. 1 = sequential (default).",
        min=1,
        max=20,
    ),
    profile: Optional[str] = typer.Option(
        None,
        "--profile", "-e",
        help="Environment profile (e.g. dev, staging, prod). Overrides base config.",
    ),
    fail_on_regression: bool = typer.Option(
        False,
        "--fail-on-regression",
        help="Exit non-zero if a test that passed in the previous run now fails (CI gate).",
    ),
    gate: bool = typer.Option(
        False,
        "--gate",
        help="Enforce quality gates from attest.yaml (min_pass_rate, max_p95_latency_ms, ...). Exit non-zero on violation.",
    ),
    trace: bool = typer.Option(
        False,
        "--trace",
        help="Emit OpenTelemetry spans for the run (uses OTEL_EXPORTER_OTLP_ENDPOINT, else console).",
    ),
):
    """Run all test scenarios.

    Loads attest.yaml, discovers test scenarios, runs them against your agent,
    and prints results.

    Examples:
        attest run                         — Run all tests
        attest run --config my_config.yaml — Use specific config
        attest run --suite "Customer Support" — Run one suite
        attest run --tag critical          — Run tagged tests only
        attest run --parallel 5            — Run 5 tests concurrently
        attest run --profile staging       — Run with staging config
    """
    from attest.cli.run_cmd import run_tests

    if trace:
        from attest.utils.tracing import setup_tracing
        setup_tracing()

    asyncio.run(run_tests(
        config_path=config,
        suite_filter=suite,
        tag_filter=tag,
        verbose=verbose,
        parallel=parallel,
        profile=profile,
        fail_on_regression=fail_on_regression,
        enforce_gates=gate,
    ))


# ---------------------------------------------------------------------------
# attest test-connection
# ---------------------------------------------------------------------------


@app.command("test-connection")
def test_connection(
    config: Optional[str] = typer.Option(
        None,
        "--config", "-c",
        help="Path to attest.yaml.",
    ),
    agent: Optional[str] = typer.Option(
        None,
        "--agent", "-a",
        help="Name of a specific agent to test. Tests all if not specified.",
    ),
):
    """Test connection to your agent(s).

    Sends a simple message to each configured agent and shows if it responds.
    Run this first to make sure your agent is reachable before running tests.

    Examples:
        attest test-connection
        attest test-connection --agent my_bot
    """
    from attest.cli.test_connection_cmd import run_test_connection

    asyncio.run(run_test_connection(config_path=config, agent_name=agent))


# ---------------------------------------------------------------------------
# attest doctor — diagnose configuration & environment
# ---------------------------------------------------------------------------


@app.command()
def doctor(
    config: Optional[str] = typer.Option(
        None, "--config", "-c", help="Path to attest.yaml. Auto-detected if not specified.",
    ),
):
    """Diagnose your ATTEST setup — config, scenarios, evaluator backends, and agents.

    A fast health check that surfaces misconfiguration before you run tests:
      - Is attest.yaml valid and are agents configured?
      - Are scenario files present and parseable?
      - Which evaluator backends are installed / configured?
      - Are credentials available for the LLM judge?

    Examples:
        attest doctor
    """
    from attest.cli.doctor_cmd import run_doctor

    raise SystemExit(run_doctor(config_path=config))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
# attest serve
# ---------------------------------------------------------------------------


@app.command()
def serve(
    config: Optional[str] = typer.Option(
        None,
        "--config", "-c",
        help="Path to attest.yaml.",
    ),
    port: int = typer.Option(
        8080,
        "--port", "-p",
        help="Port to serve on.",
    ),
    no_open: bool = typer.Option(
        False,
        "--no-open",
        help="Don't auto-open browser.",
    ),
):
    """Start the web dashboard.

    Opens a browser with a visual UI for viewing results,
    running tests, and managing configuration.

    Example:
        attest serve
        attest serve --port 3000
    """
    import webbrowser
    import uvicorn

    from attest.dashboard.api.app import app as dashboard_app, set_config_path

    set_config_path(config)

    # Bind to 127.0.0.1 so the browser's localhost (which may resolve to IPv6
    # ::1 on Windows) always reaches the server.
    url = f"http://127.0.0.1:{port}"
    console.print(f"\n[bold]ATTEST Dashboard[/bold] starting on [cyan]{url}[/cyan]")
    console.print("[dim]New here? The Dashboard page has a Getting Started guide.[/dim]\n")

    if not no_open:
        # Open browser after a short delay (server needs to start first)
        import threading
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run(dashboard_app, host="127.0.0.1", port=port, log_level="warning")


# ---------------------------------------------------------------------------
# attest baseline
# ---------------------------------------------------------------------------

baseline_app = typer.Typer(help="Manage baseline / golden responses for regression testing.")
app.add_typer(baseline_app, name="baseline")


@baseline_app.command("save")
def baseline_save(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to attest.yaml."),
    output: str = typer.Option("baselines", "--output", "-o", help="Directory to save baselines."),
    profile: Optional[str] = typer.Option(None, "--profile", "-e", help="Environment profile."),
):
    """Run all tests and save responses as golden baselines.

    These baselines are used by the `matches_baseline` assertion
    to detect regressions in future runs.

    Example:
        attest baseline save
        attest baseline save --output my_baselines
    """
    from attest.cli.run_cmd import run_tests
    from attest.utils.baseline import save_baseline

    # Run tests first to collect responses
    results = asyncio.run(run_tests(
        config_path=config,
        verbose=False,
        parallel=1,
        profile=profile,
        return_results=True,
    ))

    if results:
        count = save_baseline(results, Path(output))
        console.print(f"\n[green]Saved {count} baselines to {output}/[/green]")
    else:
        console.print("[yellow]No results to save.[/yellow]")


@baseline_app.command("diff")
def baseline_diff(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to attest.yaml."),
    baseline_dir: str = typer.Option("baselines", "--baseline-dir", "-b", help="Baselines directory."),
    profile: Optional[str] = typer.Option(None, "--profile", "-e", help="Environment profile."),
):
    """Run tests and compare with saved baselines.

    Shows what changed since the last `attest baseline save`.

    Example:
        attest baseline diff
    """
    from attest.cli.run_cmd import run_tests
    from attest.utils.baseline import compare_with_baseline
    from attest.core.models import TestResult, Message

    results = asyncio.run(run_tests(
        config_path=config,
        verbose=False,
        parallel=1,
        profile=profile,
        return_results=True,
    ))

    if not results:
        console.print("[yellow]No results to compare.[/yellow]")
        return

    changes = 0
    for result in results:
        diff = compare_with_baseline(result, Path(baseline_dir))
        if diff is None:
            console.print(f"  [dim]SKIP[/dim] {result.scenario} (no baseline)")
        elif diff["all_match"]:
            console.print(f"  [green]OK[/green]   {result.scenario}")
        else:
            changes += 1
            console.print(f"  [red]DIFF[/red] {result.scenario}")
            console.print(f"         {diff['details']}")

    if changes:
        console.print(f"\n[yellow]{changes} test(s) differ from baseline.[/yellow]")
    else:
        console.print("\n[green]All tests match their baselines.[/green]")


# ---------------------------------------------------------------------------


def main():
    """Entry point for the `attest` command."""
    app()


if __name__ == "__main__":
    main()
