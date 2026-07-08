"""Tests for the dashboard results-merge helper."""
from attest.utils.results_merge import merge_results, result_key


def test_result_key():
    assert result_key({"scenario": "a", "agent": "bot"}) == "a|bot"
    assert result_key({"scenario": "a"}) == "a|default"


def test_merge_updates_matching_and_preserves_others():
    existing = {
        "results": [
            {"scenario": "a", "agent": "bot", "status": "passed"},
            {"scenario": "b", "agent": "bot", "status": "passed"},
        ],
        "total": 2, "passed": 2, "failed": 0, "errors": 0,
    }
    # Re-run only 'a', now failing — 'b' must be preserved.
    new = [{"scenario": "a", "agent": "bot", "status": "failed"}]
    merged = merge_results(existing, new)
    assert merged["total"] == 2
    assert merged["passed"] == 1
    assert merged["failed"] == 1
    statuses = {r["scenario"]: r["status"] for r in merged["results"]}
    assert statuses == {"a": "failed", "b": "passed"}


def test_merge_adds_new_rows():
    existing = {"results": [{"scenario": "a", "agent": "bot", "status": "passed"}],
                "total": 1, "passed": 1, "failed": 0, "errors": 0}
    new = [{"scenario": "c", "agent": "bot", "status": "error"}]
    merged = merge_results(existing, new)
    assert merged["total"] == 2
    assert merged["errors"] == 1


def test_merge_same_scenario_different_agents_coexist():
    existing = {"results": [{"scenario": "a", "agent": "bot1", "status": "passed"}],
                "total": 1, "passed": 1, "failed": 0, "errors": 0}
    new = [{"scenario": "a", "agent": "bot2", "status": "passed"}]
    merged = merge_results(existing, new)
    assert merged["total"] == 2  # different agents -> distinct keys
