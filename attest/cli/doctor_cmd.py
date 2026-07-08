"""Implementation of ``attest doctor`` — configuration & environment diagnostics.

Prints a checklist of the ATTEST setup so users can spot misconfiguration
before running tests. Returns an exit code (0 = healthy, 1 = problems found).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from rich.console import Console

console = Console()


def _ok(msg: str) -> None:
    console.print(f"  [green]\u2713[/green] {msg}")


def _warn(msg: str) -> None:
    console.print(f"  [yellow]\u26a0[/yellow] {msg}")


def _err(msg: str) -> None:
    console.print(f"  [red]\u2717[/red] {msg}")


def run_doctor(config_path: Optional[str] = None) -> int:
    """Run diagnostics. Returns 0 if healthy, 1 if any problems were found."""
    problems = 0
    warnings = 0

    console.print("\n[bold]ATTEST Doctor[/bold] — checking your setup\n")

    # --- 1. Config loads ---
    console.print("[bold]Configuration[/bold]")
    config = None
    try:
        from attest.core.config import load_config
        config = load_config(config_path)
        _ok("attest.yaml loaded successfully")
    except Exception as e:
        _err(f"Could not load config: {e}")
        problems += 1

    # --- 2. Agents ---
    if config is not None:
        if config.agents:
            _ok(f"{len(config.agents)} agent(s) configured: {', '.join(config.agents)}")
            for name, ac in config.agents.items():
                if ac.type in ("http", "a2a", "foundry_prompt", "foundry_hosted") and not ac.endpoint:
                    _warn(f"agent '{name}' (type {ac.type}) has no endpoint set")
                    warnings += 1
        else:
            _warn("no agents configured — add one under 'agents:' or run 'attest init'")
            warnings += 1

    # --- 3. Scenarios ---
    console.print("\n[bold]Test scenarios[/bold]")
    if config is not None:
        scenarios_dir = config.tests.scenarios_dir
        try:
            from attest.core.scenario_loader import load_scenarios
            cases = load_scenarios(directory=scenarios_dir)
            if cases:
                _ok(f"{len(cases)} test(s) found in '{scenarios_dir}'")
                agents_used = {c.agent for c in cases}
                unknown = agents_used - set(config.agents) - {"default"}
                if unknown:
                    _warn(f"tests reference unconfigured agent(s): {', '.join(sorted(unknown))}")
                    warnings += 1
            else:
                _warn(f"no test scenarios found in '{scenarios_dir}'")
                warnings += 1
        except Exception as e:
            _err(f"failed to parse scenarios: {e}")
            problems += 1

    # --- 4. Evaluator backends ---
    console.print("\n[bold]Evaluator backends[/bold]")
    backends = [
        ("DeepEval", "deepeval", "pip install deepeval"),
        ("Azure AI Evaluation", "azure.ai.evaluation", "pip install azure-ai-evaluation"),
        ("RAGAS", "ragas", "pip install ragas langchain-openai"),
    ]
    _ok("Built-in evaluators: available (uses your LLM judge)")
    for label, module, install in backends:
        try:
            __import__(module)
            _ok(f"{label}: installed")
        except Exception:
            _warn(f"{label}: not installed ({install})")
            warnings += 1

    # --- 5. Judge credentials ---
    console.print("\n[bold]LLM judge credentials[/bold]")
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))
    has_azure = bool(os.environ.get("AZURE_API_KEY_OPENAI") or os.environ.get("AZURE_API_KEY"))
    has_base = bool(os.environ.get("AZURE_API_BASE"))
    if has_openai:
        _ok("OPENAI_API_KEY is set")
    elif has_azure and has_base:
        _ok("Azure OpenAI key + endpoint are set")
    elif has_base:
        _warn("AZURE_API_BASE set but no key — will try keyless (az login / DefaultAzureCredential)")
        warnings += 1
    else:
        _warn("no LLM judge credentials found — evaluators will error. Set OPENAI_API_KEY or AZURE_API_KEY_OPENAI + AZURE_API_BASE, or run 'az login'.")
        warnings += 1

    # --- 6. Quality gates / notify ---
    if config is not None:
        console.print("\n[bold]CI configuration[/bold]")
        from attest.core.gates import gates_are_configured
        if gates_are_configured(config.gates):
            _ok("quality gates configured (enforce with 'attest run --gate')")
        else:
            _warn("no quality gates set (optional — add a 'gates:' block for CI)")
        if getattr(config.notify, "webhook_url", None):
            _ok("notifications configured")

    # --- Summary ---
    console.print()
    if problems:
        console.print(f"[red]\u2717 {problems} problem(s), {warnings} warning(s) found.[/red]")
        return 1
    if warnings:
        console.print(f"[yellow]\u26a0 Setup usable, but {warnings} warning(s) to review.[/yellow]")
        return 0
    console.print("[green]\u2713 Everything looks healthy![/green]")
    return 0
