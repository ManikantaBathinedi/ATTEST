"""Tests for data-driven (dataset:) scenario expansion."""
from pathlib import Path

from attest.core.scenario_loader import _parse_scenario_data


def test_dataset_expands_one_test_per_row():
    data = {
        "name": "QA Suite",
        "agent": "mock_agent",
        "tests": [
            {
                "name": "qa_{{question}}",
                "dataset": {"path": "tests/data/qa_dataset.jsonl"},
                "input": "{{question}}",
                "expected_output": "{{answer}}",
                "assertions": [{"response_contains": "{{answer}}"}],
            }
        ],
    }
    cases = _parse_scenario_data(data, source_file="tests/scenarios/dummy.yaml")
    assert len(cases) == 3
    inputs = {c.input for c in cases}
    assert "What is the capital of Japan?" in inputs
    assert "What is the capital of France?" in inputs
    # Placeholders filled in assertions too
    japan = next(c for c in cases if "Japan" in c.input)
    assert japan.expected_output == "Tokyo"
    assert japan.assertions == [{"response_contains": "Tokyo"}]


def test_dataset_row_name_column_used_when_no_template():
    data = {
        "agent": "mock_agent",
        "tests": [
            {"dataset": {"path": "tests/data/qa_dataset.jsonl"}, "input": "{{question}}"}
        ],
    }
    cases = _parse_scenario_data(data, source_file="tests/scenarios/dummy.yaml")
    # No explicit name/template → falls back to <stem>#<n>
    assert len(cases) == 3
    assert all(c.name for c in cases)


def test_dataset_missing_file_raises():
    import pytest
    from attest.core.exceptions import ScenarioError
    data = {
        "agent": "mock_agent",
        "tests": [{"dataset": {"path": "tests/data/nope.jsonl"}, "input": "{{question}}"}],
    }
    with pytest.raises(ScenarioError):
        _parse_scenario_data(data, source_file="tests/scenarios/dummy.yaml")
