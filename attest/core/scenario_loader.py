"""YAML scenario loader.

Reads YAML test scenario files and converts them into TestCase objects.
This is the zero-code path — QA writes YAML, the loader does the rest.

Supported YAML format:

    name: "My Test Suite"
    agent: my_bot              # Which agent to test (from attest.yaml)

    tests:
      - name: greeting
        input: "Hello"
        assertions:
          - response_not_empty: true

      - name: refund
        input: "I want a refund"
        expected_output: "Refund initiated"
        assertions:
          - tool_called: process_refund
        evaluators:
          - correctness: { threshold: 0.8 }

Also supports bulk data from JSONL:

    name: "Bulk Tests"
    agent: my_bot
    data:
      source: "tests/data/qa_pairs.jsonl"
    evaluators:
      - correctness

Usage:
    from attest.core.scenario_loader import load_scenarios, discover_scenario_files

    files = discover_scenario_files("tests/scenarios")
    test_cases = load_scenarios(files)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ruamel.yaml import YAML

from attest.core.exceptions import ScenarioError
from attest.core.models import ExpectedToolCall, TestCase


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def discover_scenario_files(directory: str) -> List[Path]:
    """Find all YAML scenario files in a directory.

    Searches for *.yaml and *.yml files, sorted alphabetically.

    Args:
        directory: Path to search in.

    Returns:
        List of Path objects for found scenario files.
    """
    dir_path = Path(directory)
    if not dir_path.exists():
        return []

    files = []
    for pattern in ["*.yaml", "*.yml"]:
        files.extend(dir_path.glob(pattern))

    return sorted(files)


# ---------------------------------------------------------------------------
# YAML parsing
# ---------------------------------------------------------------------------


def load_scenario_file(path: Path) -> List[TestCase]:
    """Load a single YAML scenario file and return TestCase objects.

    Args:
        path: Path to the YAML file.

    Returns:
        List of TestCase objects parsed from the file.
    """
    yaml = YAML()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.load(f)
    except Exception as e:
        raise ScenarioError(f"Failed to parse scenario file {path}: {e}") from e

    if data is None:
        return []

    return _parse_scenario_data(data, source_file=str(path))


def _parse_scenario_data(data: Dict[str, Any], source_file: str = "") -> List[TestCase]:
    """Parse a scenario data dict into TestCase objects.

    Handles two modes:
    1. Inline tests: tests defined directly in the YAML
    2. Data source: tests loaded from a JSONL/CSV file
    """
    # Suite-level defaults
    suite_name = data.get("name", "default")
    default_agent = data.get("agent", "default")
    suite_evaluators = data.get("evaluators", [])
    suite_assertions = data.get("assertions", [])
    suite_tags = data.get("tags", [])

    test_cases = []

    # Mode 1: Inline tests
    if "tests" in data:
        for test_data in data["tests"]:
            tc = _parse_single_test(
                test_data,
                suite_name=suite_name,
                default_agent=default_agent,
                suite_evaluators=suite_evaluators,
                suite_assertions=suite_assertions,
                suite_tags=suite_tags,
            )
            test_cases.append(tc)

    # Mode 2: Data source (JSONL/CSV)
    if "data" in data:
        data_tests = _load_data_source(
            data["data"],
            suite_name=suite_name,
            default_agent=default_agent,
            suite_evaluators=suite_evaluators,
            suite_assertions=suite_assertions,
            suite_tags=suite_tags,
        )
        test_cases.extend(data_tests)

    return test_cases


def _parse_single_test(
    test_data: Dict[str, Any],
    suite_name: str,
    default_agent: str,
    suite_evaluators: list,
    suite_assertions: list,
    suite_tags: list,
) -> TestCase:
    """Parse a single test entry from YAML into a TestCase."""
    # Conversation tests have 'script' instead of 'input'
    test_type = test_data.get("type", "single_turn")
    is_conversation = test_type == "conversation" or "script" in test_data
    is_simulation = test_type == "simulation"

    if not is_conversation and not is_simulation and "input" not in test_data:
        raise ScenarioError(
            f"Test '{test_data.get('name', 'unnamed')}' is missing 'input' field."
        )

    # Build name (auto-generate if not provided)
    if is_conversation:
        name = test_data.get("name", f"conversation_{id(test_data) % 10000:04d}")
    elif is_simulation:
        name = test_data.get("name", f"simulation_{id(test_data) % 10000:04d}")
    else:
        name = test_data.get("name", f"test_{hash(test_data['input']) % 10000:04d}")

    # Merge suite-level and test-level evaluators/assertions
    evaluators = test_data.get("evaluators", []) or suite_evaluators
    assertions = test_data.get("assertions", []) or suite_assertions
    tags = list(set(suite_tags + test_data.get("tags", [])))

    # Parse expected tool calls
    expected_tool_calls = []
    for tc_data in test_data.get("expected_tool_calls", []):
        if isinstance(tc_data, dict):
            expected_tool_calls.append(
                ExpectedToolCall(
                    name=tc_data.get("name", ""),
                    args=tc_data.get("args", {}),
                )
            )

    # Parse thresholds from evaluator specs
    thresholds = {}
    for spec in evaluators:
        if isinstance(spec, dict):
            for eval_name, config in spec.items():
                if isinstance(config, dict) and "threshold" in config:
                    thresholds[eval_name] = config["threshold"]
                elif isinstance(config, (int, float)):
                    thresholds[eval_name] = float(config)

    # For conversation tests, use first user message as input
    input_text = test_data.get("input", "")
    conversation_script = []
    if is_conversation and "script" in test_data:
        conversation_script = list(test_data["script"])
        # Use first turn's message as the input (for display/naming)
        if conversation_script and not input_text:
            input_text = conversation_script[0].get("user", "multi-turn test")

    # For simulation tests, goal can come from 'input' or 'goal'
    if is_simulation and not input_text:
        input_text = test_data.get("goal", "Complete the task successfully")

    # Determine effective type
    effective_type = "conversation" if is_conversation else ("simulation" if is_simulation else "single_turn")

    return TestCase(
        name=name,
        suite=suite_name,
        type=effective_type,
        input=input_text,
        conversation_script=conversation_script,
        expected_output=test_data.get("expected_output"),
        expected_tool_calls=expected_tool_calls,
        expected_intent=test_data.get("expected_intent"),
        context=test_data.get("context"),
        ground_truth=test_data.get("ground_truth"),
        assertions=assertions,
        evaluators=evaluators,
        thresholds=thresholds,
        agent=test_data.get("agent", default_agent),
        tags=tags,
        timeout=test_data.get("timeout", 30),
        description=test_data.get("description"),
        persona=test_data.get("persona"),
        max_turns=test_data.get("max_turns"),
    )


# ---------------------------------------------------------------------------
# Data source loading (JSONL, CSV)
# ---------------------------------------------------------------------------


def _load_data_source(
    data_config: Dict[str, Any],
    suite_name: str,
    default_agent: str,
    suite_evaluators: list,
    suite_assertions: list,
    suite_tags: list,
) -> List[TestCase]:
    """Load test cases from a data file (JSONL or CSV)."""
    source = data_config.get("source", "")
    mapping = data_config.get("mapping", {})
    path = Path(source)

    if not path.exists():
        raise ScenarioError(f"Data source not found: {source}")

    if path.suffix == ".jsonl":
        return _load_jsonl(
            path, mapping, suite_name, default_agent,
            suite_evaluators, suite_assertions, suite_tags,
        )
    elif path.suffix == ".csv":
        return _load_csv(
            path, mapping, suite_name, default_agent,
            suite_evaluators, suite_assertions, suite_tags,
        )
    else:
        raise ScenarioError(f"Unsupported data format: {path.suffix}. Use .jsonl or .csv")


def _load_jsonl(
    path: Path,
    mapping: Dict[str, str],
    suite_name: str,
    default_agent: str,
    suite_evaluators: list,
    suite_assertions: list,
    suite_tags: list,
) -> List[TestCase]:
    """Load test cases from a JSONL file (one JSON object per line)."""
    test_cases = []

    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise ScenarioError(f"Invalid JSON on line {line_num} of {path}: {e}")

            # Apply column mapping
            mapped = _apply_mapping(row, mapping)

            if "input" not in mapped:
                continue  # Skip rows without input

            tc = TestCase(
                name=mapped.get("name", f"data_{line_num}"),
                suite=suite_name,
                input=mapped["input"],
                expected_output=mapped.get("expected_output"),
                context=mapped.get("context"),
                ground_truth=mapped.get("ground_truth"),
                evaluators=suite_evaluators,
                assertions=suite_assertions,
                agent=default_agent,
                tags=suite_tags + mapped.get("tags", []),
            )
            test_cases.append(tc)

    return test_cases


def _load_csv(
    path: Path,
    mapping: Dict[str, str],
    suite_name: str,
    default_agent: str,
    suite_evaluators: list,
    suite_assertions: list,
    suite_tags: list,
) -> List[TestCase]:
    """Load test cases from a CSV file."""
    import csv

    test_cases = []

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, 1):
            mapped = _apply_mapping(dict(row), mapping)

            if "input" not in mapped:
                continue

            tc = TestCase(
                name=mapped.get("name", f"csv_{row_num}"),
                suite=suite_name,
                input=mapped["input"],
                expected_output=mapped.get("expected_output"),
                context=mapped.get("context"),
                ground_truth=mapped.get("ground_truth"),
                evaluators=suite_evaluators,
                assertions=suite_assertions,
                agent=default_agent,
                tags=suite_tags,
            )
            test_cases.append(tc)

    return test_cases


def _apply_mapping(row: Dict[str, Any], mapping: Dict[str, str]) -> Dict[str, Any]:
    """Apply column name mapping to a data row.

    If mapping says {"input": "question", "expected_output": "answer"},
    then row["question"] becomes row["input"].
    """
    if not mapping:
        return row

    mapped = dict(row)
    for target_field, source_field in mapping.items():
        if source_field in row:
            mapped[target_field] = row[source_field]

    return mapped


# ---------------------------------------------------------------------------
# High-level API
# ---------------------------------------------------------------------------


def load_scenarios(
    paths: Optional[List[Path]] = None,
    directory: Optional[str] = None,
) -> List[TestCase]:
    """Load all test scenarios from files or a directory.

    Args:
        paths: Explicit list of YAML files to load.
        directory: Directory to search for *.yaml files.

    Returns:
        All TestCase objects from all files combined.
    """
    all_cases = []

    if directory:
        found_files = discover_scenario_files(directory)
        paths = (paths or []) + found_files

    for path in (paths or []):
        cases = load_scenario_file(Path(path))
        all_cases.extend(cases)

    return all_cases
