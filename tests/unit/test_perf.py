"""Tests for agent performance stats and perf assertions."""
from attest.core.models import AgentResponse, TokenUsage
from attest.core.assertions import (
    assert_ttft_under,
    assert_tokens_per_second_over,
    resolve_assertion,
)
from attest.perf.stats import (
    compute_perf_stats,
    percentile,
    summarize_latencies,
)


# ---- percentile / summarize -------------------------------------------------

def test_percentile_basic():
    vals = [10, 20, 30, 40, 50]
    assert percentile(vals, 0) == 10
    assert percentile(vals, 100) == 50
    assert percentile(vals, 50) == 30


def test_percentile_empty_is_zero():
    assert percentile([], 95) == 0.0


def test_percentile_single_value():
    assert percentile([42], 95) == 42


def test_summarize_latencies():
    s = summarize_latencies([100, 200, 300, 400, 500])
    assert s["count"] == 5
    assert s["min"] == 100
    assert s["max"] == 500
    assert s["mean"] == 300
    assert s["p50"] == 300


# ---- compute_perf_stats -----------------------------------------------------

def test_compute_perf_stats_from_dicts():
    results = [
        {"latency_ms": 100, "token_usage": {"total_tokens": 50}, "estimated_cost": 0.001, "error": None},
        {"latency_ms": 200, "token_usage": {"total_tokens": 80}, "estimated_cost": 0.002, "error": None},
        {"latency_ms": 300, "token_usage": {"total_tokens": 60}, "estimated_cost": 0.0, "error": "boom"},
    ]
    perf = compute_perf_stats(results)
    assert perf["total_requests"] == 3
    assert perf["error_rate"] == round(1 / 3, 4)
    assert perf["latency_ms"]["count"] == 3
    assert perf["latency_ms"]["max"] == 300
    assert perf["total_tokens"]["count"] == 3
    assert perf["cost_usd"]["total"] == 0.003


def test_compute_perf_stats_empty():
    perf = compute_perf_stats([])
    assert perf["total_requests"] == 0
    assert perf["error_rate"] == 0.0
    assert perf["latency_ms"]["count"] == 0


# ---- ttft_under -------------------------------------------------------------

def test_ttft_under_passes_within_limit():
    resp = AgentResponse(content="hi", latency_ms=500, time_to_first_token_ms=200)
    res = assert_ttft_under(800)(resp)
    assert res.passed


def test_ttft_under_fails_over_limit():
    resp = AgentResponse(content="hi", latency_ms=500, time_to_first_token_ms=900)
    res = assert_ttft_under(800)(resp)
    assert not res.passed


def test_ttft_under_skips_when_missing():
    resp = AgentResponse(content="hi", latency_ms=500)  # no ttft
    res = assert_ttft_under(800)(resp)
    assert res.passed  # skipped == pass


# ---- tokens_per_second_over -------------------------------------------------

def test_tps_over_passes():
    # 100 output tokens / 1s = 100 tok/s
    resp = AgentResponse(content="x", latency_ms=1000,
                         token_usage=TokenUsage(output_tokens=100, total_tokens=120))
    res = assert_tokens_per_second_over(20)(resp)
    assert res.passed


def test_tps_over_fails():
    # 10 tokens / 1s = 10 tok/s < 20
    resp = AgentResponse(content="x", latency_ms=1000,
                         token_usage=TokenUsage(output_tokens=10, total_tokens=12))
    res = assert_tokens_per_second_over(20)(resp)
    assert not res.passed


def test_tps_over_skips_without_usage():
    resp = AgentResponse(content="x", latency_ms=1000)
    res = assert_tokens_per_second_over(20)(resp)
    assert res.passed  # skipped


# ---- resolver wiring --------------------------------------------------------

def test_resolver_registers_perf_assertions():
    assert resolve_assertion({"ttft_under": 800}) is not None
    assert resolve_assertion({"tokens_per_second_over": 20}) is not None
