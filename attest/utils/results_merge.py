"""Result-set merge helpers for the dashboard.

Partial runs (single test / suite / tag) must merge into the accumulated
``results.json`` without clobbering unrelated results. This logic was
previously inlined (and had a clobbering bug); it lives here so it can be
unit-tested in isolation.
"""

from __future__ import annotations

from typing import Any, Dict, List


def result_key(r: Dict[str, Any]) -> str:
    """Stable identity for a result row: scenario + agent."""
    return str(r.get("scenario", "")) + "|" + str(r.get("agent", "default"))


def merge_results(existing: Dict[str, Any], new_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge ``new_results`` into an existing results document (keyed by
    scenario|agent), recomputing the aggregate counts.

    Returns the updated ``existing`` dict (mutated in place and returned).
    """
    merged: Dict[str, Dict[str, Any]] = {result_key(r): r for r in existing.get("results", [])}
    for r in new_results:
        merged[result_key(r)] = r

    results_list = list(merged.values())
    existing["results"] = results_list
    existing["total"] = len(results_list)
    existing["passed"] = sum(1 for r in results_list if r.get("status") == "passed")
    existing["failed"] = sum(1 for r in results_list if r.get("status") == "failed")
    existing["errors"] = sum(1 for r in results_list if r.get("status") == "error")
    existing["skipped"] = sum(1 for r in results_list if r.get("status") == "skipped")
    return existing
