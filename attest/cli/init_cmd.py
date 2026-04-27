"""Implementation of `attest init` command.

Generates:
    attest.yaml          — Main config file (pre-filled with comments)
    tests/scenarios/     — Directory with a sample test scenario
    .env.example         — Template for environment variables
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from attest.cli.templates import (
    ENV_TEMPLATE,
    HTTP_CONFIG_TEMPLATE,
    FOUNDRY_CONFIG_TEMPLATE,
    SAMPLE_SCENARIO_TEMPLATE,
)

console = Console()


# Minimal config for quick start
MINIMAL_CONFIG = """\
# ATTEST — Minimal Configuration
agents:
  my_agent:
    type: http
    endpoint: "http://localhost:8000"

evaluation:
  backend: builtin
  judge:
    model: "openai/gpt-4.1-mini"
"""

MINIMAL_SCENARIO = """\
name: "Quick Tests"
agent: my_agent

tests:
  - name: hello
    input: "Hello"
    assertions:
      - response_not_empty: true
"""


def run_init(preset: str = "http", directory: str = ".") -> None:
    """Generate project files based on the chosen preset.

    Args:
        preset: Template type — "http", "foundry", or "minimal".
        directory: Where to create files.
    """
    base = Path(directory)

    console.print(f"\n[bold]ATTEST[/bold] — Initializing project ({preset} preset)\n")

    # Don't overwrite existing config
    config_path = base / "attest.yaml"
    if config_path.exists():
        console.print("[yellow]⚠️  attest.yaml already exists — skipping.[/yellow]")
        console.print("    Delete it first if you want to regenerate.\n")
        return

    # Pick template — use .replace() instead of .format() to avoid
    # conflicts with ${ENV_VAR} and {{input}} syntax in the templates
    if preset == "foundry":
        config_content = (
            FOUNDRY_CONFIG_TEMPLATE
            .replace("{project_name}", "My Foundry Agent Tests")
            .replace("{endpoint}", "https://your-agent.azurewebsites.net")
            .replace("{azure_project}", "https://your-resource.services.ai.azure.com/api/projects/your-project")
        )
    elif preset == "minimal":
        config_content = MINIMAL_CONFIG
    else:
        # Default: HTTP
        config_content = (
            HTTP_CONFIG_TEMPLATE
            .replace("{project_name}", "My Agent Tests")
            .replace("{endpoint}", "http://localhost:8000")
            .replace("{path}", "/chat")
            .replace("{body_key}", "message")
            .replace("{content_path}", "$.response")
        )

    # Create files
    files_created = []

    # 1. attest.yaml
    _write_file(config_path, config_content)
    files_created.append("attest.yaml")

    # 2. tests/scenarios/ directory + sample scenario
    scenarios_dir = base / "tests" / "scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)

    scenario_path = scenarios_dir / "sample.yaml"
    if not scenario_path.exists():
        scenario_content = SAMPLE_SCENARIO_TEMPLATE if preset != "minimal" else MINIMAL_SCENARIO
        _write_file(scenario_path, scenario_content)
        files_created.append("tests/scenarios/sample.yaml")

    # 3. tests/data/ directory
    data_dir = base / "tests" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # 4. reports/ directory
    reports_dir = base / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # 5. .env.example
    env_path = base / ".env.example"
    if not env_path.exists():
        _write_file(env_path, ENV_TEMPLATE)
        files_created.append(".env.example")

    # Print summary
    console.print("  Created files:")
    for f in files_created:
        console.print(f"    [green]✅[/green] {f}")

    console.print(f"\n  Created directories:")
    for d in ["tests/scenarios/", "tests/data/", "reports/"]:
        console.print(f"    [blue]📁[/blue] {d}")

    console.print(f"\n[bold]Next steps:[/bold]")
    console.print("  1. Edit [cyan]attest.yaml[/cyan] — set your agent's URL")
    console.print("  2. Copy [cyan].env.example[/cyan] to [cyan].env[/cyan] and add your API keys")
    console.print("  3. Edit [cyan]tests/scenarios/sample.yaml[/cyan] — add your test cases")
    console.print("  4. Run: [green]attest run[/green]\n")


def _write_file(path: Path, content: str) -> None:
    """Write content to a file, creating parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
