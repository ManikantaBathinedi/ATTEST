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
):
    """Run all test scenarios.

    Loads attest.yaml, discovers test scenarios, runs them against your agent,
    and prints results.

    Examples:
        attest run                         — Run all tests
        attest run --config my_config.yaml — Use specific config
        attest run --suite "Customer Support" — Run one suite
        attest run --tag critical          — Run tagged tests only
    """
    from attest.cli.run_cmd import run_tests

    asyncio.run(run_tests(
        config_path=config,
        suite_filter=suite,
        tag_filter=tag,
        verbose=verbose,
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

    url = f"http://localhost:{port}"
    console.print(f"\n[bold]ATTEST Dashboard[/bold] starting on [cyan]{url}[/cyan]\n")

    if not no_open:
        # Open browser after a short delay (server needs to start first)
        import threading
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    uvicorn.run(dashboard_app, host="0.0.0.0", port=port, log_level="warning")


# ---------------------------------------------------------------------------


def main():
    """Entry point for the `attest` command."""
    app()


if __name__ == "__main__":
    main()
