"""Tests for quality gates, notifications, and dataset-driven tests."""
from attest.core.config_models import GatesConfig, NotifyConfig, AttestConfig
from attest.core.models import RunSummary, TestResult, Status
from attest.core.gates import evaluate_gates, gates_are_configured
from attest.utils.notify import _should_send, _find_regressions, _build_summary_text


def _summary(passed=8, failed=2, errors=0, cost=0.01, score=0.9, p95=1200.0):
    s = RunSummary(run_id="r1")
    s.total = passed + failed + errors
    s.passed = passed
    s.failed = failed
    s.errors = errors
    s.total_cost = cost
    s.overall_score = score
    s.perf = {"latency_ms": {"p95": p95, "count": s.total}}
    return s


# ---- gates ------------------------------------------------------------------

def test_gates_not_configured_by_default():
    assert gates_are_configured(GatesConfig()) is False


def test_gate_pass_rate_violation():
    gates = GatesConfig(min_pass_rate=0.95)
    ok, violations = evaluate_gates(_summary(passed=8, failed=2), gates)  # 80%
    assert not ok
    assert any("pass rate" in v for v in violations)


def test_gate_pass_rate_ok():
    gates = GatesConfig(min_pass_rate=0.5)
    ok, violations = evaluate_gates(_summary(passed=8, failed=2), gates)
    assert ok
    assert violations == []


def test_gate_latency_violation():
    gates = GatesConfig(max_p95_latency_ms=1000)
    ok, violations = evaluate_gates(_summary(p95=1200), gates)
    assert not ok
    assert any("p95" in v for v in violations)


def test_gate_cost_and_score():
    gates = GatesConfig(max_total_cost=0.005, min_avg_score=0.95)
    ok, violations = evaluate_gates(_summary(cost=0.01, score=0.9), gates)
    assert not ok
    assert len(violations) == 2


def test_gate_all_pass():
    gates = GatesConfig(min_pass_rate=0.5, max_failed=5, max_p95_latency_ms=5000, max_total_cost=1.0)
    ok, violations = evaluate_gates(_summary(), gates)
    assert ok


# ---- notify -----------------------------------------------------------------

def test_notify_should_send_always():
    assert _should_send("always", _summary(), None) is True


def test_notify_should_send_failure_only():
    assert _should_send("failure", _summary(failed=0, errors=0), None) is False
    assert _should_send("failure", _summary(failed=1), None) is True


def test_notify_summary_text():
    txt = _build_summary_text(_summary(passed=10, failed=0, errors=0))
    assert "10/10" in txt
    assert "✅" in txt


def test_find_regressions():
    prev = RunSummary(run_id="p")
    prev.results = [TestResult(scenario="a", status=Status.PASSED),
                    TestResult(scenario="b", status=Status.PASSED)]
    cur = RunSummary(run_id="c")
    cur.results = [TestResult(scenario="a", status=Status.FAILED),
                   TestResult(scenario="b", status=Status.PASSED)]
    assert _find_regressions(cur, prev) == ["a"]


# ---- config wiring ----------------------------------------------------------

def test_attest_config_has_gates_and_notify():
    cfg = AttestConfig()
    assert isinstance(cfg.gates, GatesConfig)
    assert isinstance(cfg.notify, NotifyConfig)
    assert cfg.evaluation.samples == 1
