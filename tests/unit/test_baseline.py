"""Unit tests for ATTEST baseline / golden-response regression support.

Run:
    pytest tests/unit/test_baseline.py -v
"""

from attest.core.models import TestResult, Status, Message, ToolCall
from attest.utils.baseline import save_baseline, load_baseline, compare_with_baseline


def _result(scenario="greeting", agent="agent", content="Hello there",
            tool_calls=None, routing_path=None):
    return TestResult(
        scenario=scenario,
        agent=agent,
        status=Status.PASSED,
        messages=[Message(role="assistant", content=content)],
        tool_calls=tool_calls or [],
        routing_path=routing_path or [],
    )


def test_save_and_load_roundtrip(tmp_path):
    saved = save_baseline([_result(content="Hi!")], base_dir=tmp_path)
    assert saved == 1
    loaded = load_baseline("agent", "greeting", base_dir=tmp_path)
    assert loaded is not None
    assert loaded["content"] == "Hi!"


def test_save_skips_error_results(tmp_path):
    err = _result(scenario="boom")
    err.status = Status.ERROR
    err.error = "timeout"
    assert save_baseline([err], base_dir=tmp_path) == 0


def test_compare_no_baseline_returns_none(tmp_path):
    assert compare_with_baseline(_result(), base_dir=tmp_path) is None


def test_compare_all_match(tmp_path):
    save_baseline([_result(content="same")], base_dir=tmp_path)
    diff = compare_with_baseline(_result(content="same"), base_dir=tmp_path)
    assert diff is not None
    assert diff["all_match"] is True


def test_compare_detects_content_change(tmp_path):
    save_baseline([_result(content="original")], base_dir=tmp_path)
    diff = compare_with_baseline(_result(content="changed"), base_dir=tmp_path)
    assert diff["content_match"] is False
    assert diff["all_match"] is False


def test_compare_detects_tool_call_change(tmp_path):
    save_baseline([_result(tool_calls=[ToolCall(name="search")])], base_dir=tmp_path)
    diff = compare_with_baseline(
        _result(tool_calls=[ToolCall(name="delete")]), base_dir=tmp_path
    )
    assert diff["tool_calls_match"] is False


def test_compare_detects_routing_change(tmp_path):
    save_baseline([_result(routing_path=["orch", "flights"])], base_dir=tmp_path)
    diff = compare_with_baseline(
        _result(routing_path=["orch", "hotels"]), base_dir=tmp_path
    )
    assert diff["routing_match"] is False
