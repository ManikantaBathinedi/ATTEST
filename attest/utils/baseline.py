"""Baseline / golden response manager for regression testing.

Saves agent responses as JSON snapshots. Future runs can compare against
these baselines to detect regressions (semantic drift, missing tool calls,
structural changes).

Usage in attest.yaml:
    tests:
      - name: "booking flow"
        input: "Book a flight to Paris"
        assertions:
          - type: matches_baseline
            threshold: 0.8        # optional, default 0.8

CLI:
    attest baseline save          — Snapshot current responses
    attest baseline diff          — Compare latest run with saved baseline
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from attest.core.models import AgentResponse, TestResult


BASELINE_DIR = Path("baselines")


def _key(agent: str, test_name: str) -> str:
    """Stable filename-safe key for a test case."""
    raw = f"{agent}::{test_name}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _baseline_path(agent: str, test_name: str, base_dir: Optional[Path] = None) -> Path:
    directory = base_dir or BASELINE_DIR
    return directory / f"{_key(agent, test_name)}.json"


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def save_baseline(
    results: List[TestResult],
    base_dir: Optional[Path] = None,
) -> int:
    """Save test results as baseline snapshots. Returns count saved."""
    directory = base_dir or BASELINE_DIR
    directory.mkdir(parents=True, exist_ok=True)

    count = 0
    for result in results:
        if result.error:
            continue  # Don't baseline error results
        snapshot = {
            "scenario": result.scenario,
            "agent": result.agent,
            "content": result.messages[-1].content if result.messages else "",
            "tool_calls": [tc.model_dump() for tc in result.tool_calls],
            "handled_by": result.handled_by,
            "routing_path": result.routing_path,
        }
        path = _baseline_path(result.agent, result.scenario, directory)
        path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        count += 1

    return count


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def load_baseline(
    agent: str,
    test_name: str,
    base_dir: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Load a saved baseline for a specific test. Returns None if not found."""
    path = _baseline_path(agent, test_name, base_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------


def compare_with_baseline(
    result: TestResult,
    base_dir: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Compare a test result against its saved baseline.

    Returns a diff dict with:
        - content_match: bool
        - tool_calls_match: bool
        - routing_match: bool
        - details: str (human-readable diff)

    Returns None if no baseline exists for this test.
    """
    baseline = load_baseline(result.agent, result.scenario, base_dir)
    if baseline is None:
        return None

    current_content = result.messages[-1].content if result.messages else ""
    baseline_content = baseline.get("content", "")

    current_tools = sorted([tc.name for tc in result.tool_calls])
    baseline_tools = sorted([tc.get("name", "") for tc in baseline.get("tool_calls", [])])

    current_routing = result.routing_path
    baseline_routing = baseline.get("routing_path", [])

    content_match = current_content.strip() == baseline_content.strip()
    tool_calls_match = current_tools == baseline_tools
    routing_match = current_routing == baseline_routing

    details = []
    if not content_match:
        details.append(
            f"Content changed:\n  baseline: {baseline_content[:200]}\n  current:  {current_content[:200]}"
        )
    if not tool_calls_match:
        details.append(f"Tool calls changed: {baseline_tools} → {current_tools}")
    if not routing_match:
        details.append(f"Routing changed: {baseline_routing} → {current_routing}")

    return {
        "content_match": content_match,
        "tool_calls_match": tool_calls_match,
        "routing_match": routing_match,
        "all_match": content_match and tool_calls_match and routing_match,
        "details": "\n".join(details) if details else "No changes detected.",
        # Full before/after values for a detailed, expandable comparison view.
        "baseline_content": baseline_content,
        "current_content": current_content,
        "baseline_tools": baseline_tools,
        "current_tools": current_tools,
        "baseline_routing": baseline_routing,
        "current_routing": current_routing,
    }
