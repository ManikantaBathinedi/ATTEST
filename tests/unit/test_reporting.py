"""Unit tests for ATTEST reporting (Markdown report + regression diff).

Run:
    pytest tests/unit/test_reporting.py -v
"""

from attest.core.models import RunSummary, TestResult, Status, EvalScore
from attest.reporting.markdown_report import generate_markdown_report


def _result(scenario, status, agent="agent", score=None):
    r = TestResult(scenario=scenario, suite="S", status=status, agent=agent, latency_ms=10.0)
    if score is not None:
        r.scores["relevancy"] = EvalScore(
            name="relevancy", score=score, passed=score >= 0.7, threshold=0.7
        )
    return r


def _summary(run_id, results, duration=1.0):
    s = RunSummary(run_id=run_id)
    for r in results:
        s.add_result(r)
    s.duration_seconds = duration
    return s


def test_markdown_basic_summary_counts():
    s = _summary("r1", [
        _result("a", Status.PASSED),
        _result("b", Status.FAILED),
        _result("c", Status.ERROR),
    ])
    md = generate_markdown_report(s)
    assert "ATTEST Agent Test Results" in md
    assert "Total | 3" in md
    assert "Passed | 1" in md
    assert "Failed | 1" in md
    assert "Errors | 1" in md


def test_markdown_pass_rate_trend_arrow():
    prev = _summary("prev", [_result("a", Status.PASSED), _result("b", Status.PASSED)])
    cur = _summary("cur", [_result("a", Status.PASSED), _result("b", Status.FAILED)])
    md = generate_markdown_report(cur, previous=prev)
    # pass rate dropped 100% -> 50%
    assert "50%" in md
    assert "\u2193" in md  # down arrow


def test_markdown_detects_regression():
    prev = _summary("prev", [_result("login", Status.PASSED)])
    cur = _summary("cur", [_result("login", Status.FAILED)])
    md = generate_markdown_report(cur, previous=prev)
    assert "Regressions" in md
    assert "login" in md


def test_markdown_detects_fix():
    prev = _summary("prev", [_result("login", Status.FAILED)])
    cur = _summary("cur", [_result("login", Status.PASSED)])
    md = generate_markdown_report(cur, previous=prev)
    assert "Fixed" in md


def test_markdown_writes_file(tmp_path):
    s = _summary("r1", [_result("a", Status.PASSED)])
    out = tmp_path / "summary.md"
    content = generate_markdown_report(s, output_path=str(out))
    assert out.exists()
    assert out.read_text(encoding="utf-8") == content


def test_summary_pass_rate_property():
    s = _summary("r", [
        _result("a", Status.PASSED),
        _result("b", Status.PASSED),
        _result("c", Status.FAILED),
        _result("d", Status.ERROR),
    ])
    assert s.total == 4
    assert s.passed == 2
    assert abs(s.pass_rate - 0.5) < 1e-9
