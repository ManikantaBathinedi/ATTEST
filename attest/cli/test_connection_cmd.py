"""Implementation of `attest test-connection` command.

Tests connectivity to all configured agents. Sends a simple message
and shows if the agent responds. Users run this FIRST before writing tests.

No test scenarios needed — just attest.yaml with agent config.
"""

from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.table import Table

from attest.adapters import create_adapter
from attest.core.config import load_config
from attest.core.exceptions import AttestError

console = Console()


async def run_test_connection(
    config_path: Optional[str] = None,
    agent_name: Optional[str] = None,
) -> None:
    """Test connection to configured agents.

    For each agent:
    1. Create the adapter
    2. Run health check
    3. Send a test message
    4. Show the result
    """
    try:
        config = load_config(config_path)
    except AttestError as e:
        console.print(f"[red]Error loading config:[/red] {e}")
        raise SystemExit(1)

    if not config.agents:
        console.print(
            "[yellow]No agents configured.[/yellow]\n"
            "  Add agents to attest.yaml or run: [green]attest init[/green]"
        )
        raise SystemExit(1)

    # Pick which agents to test
    if agent_name:
        if agent_name not in config.agents:
            available = list(config.agents.keys())
            console.print(
                f"[red]Agent '{agent_name}' not found.[/red] "
                f"Available: {available}"
            )
            raise SystemExit(1)
        agents_to_test = {agent_name: config.agents[agent_name]}
    else:
        agents_to_test = config.agents

    console.print(f"\n[bold]ATTEST[/bold] — Testing connection to {len(agents_to_test)} agent(s)\n")

    # Test each agent
    results = []
    for name, agent_config in agents_to_test.items():
        console.print(f"  Testing [cyan]{name}[/cyan] ({agent_config.type})...", end=" ")

        result = {"name": name, "type": agent_config.type}

        try:
            adapter = create_adapter(agent_config)
            await adapter.setup()

            # Send a test message
            response = await adapter.send_message("Hello, what can you help with?")
            preview = response.content[:100].replace("\n", " ")

            result["status"] = "✅ Connected"
            result["response"] = preview
            result["latency"] = f"{response.latency_ms:.0f}ms"

            console.print(f"[green]✅ Connected[/green] ({response.latency_ms:.0f}ms)")
            console.print(f"      [dim]Response: {preview}...[/dim]")

            await adapter.teardown()

        except Exception as e:
            error_msg = str(e)
            result["status"] = "❌ Error"
            result["response"] = error_msg

            # Give simple, actionable error messages
            if "authentication" in error_msg.lower() or "credential" in error_msg.lower() or "token" in error_msg.lower():
                console.print(f"[red]❌ Authentication failed[/red]")
                console.print()
                console.print("      [yellow]Fix: Add your API key to a .env file:[/yellow]")
                console.print("        1. Copy .env.example to .env")
                console.print("        2. Open .env and paste your API key")
                console.print("        3. Find your key: Azure Foundry Portal → Project Settings → Keys")
                console.print()
            elif "connect" in error_msg.lower() or "unreachable" in error_msg.lower():
                console.print(f"[red]❌ Cannot reach agent[/red]")
                console.print(f"      Check the endpoint URL in attest.yaml")
            else:
                console.print(f"[red]❌ Error:[/red] {error_msg[:150]}")

        results.append(result)

    # Summary
    console.print()
    connected = sum(1 for r in results if "✅" in r["status"])
    total = len(results)

    if connected == total:
        console.print(f"[green]All {total} agent(s) connected successfully.[/green]")
        console.print("You're ready to run tests: [green]attest run[/green]\n")
    else:
        console.print(
            f"[yellow]{connected}/{total} agent(s) connected.[/yellow]\n"
            "  Fix the connection issues above, then try again.\n"
        )
        raise SystemExit(1)
