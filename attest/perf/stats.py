"""Agent performance statistics.

Aggregates the per-request performance primitives ATTEST already captures
(latency, time-to-first-token, tokens, cost) into run-level insight:
percentiles, throughput, and averages.

This is *agent* performance — latency distribution and cost across the tests
you already run — not infrastructure load testing (use k6 / Locust for that).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


def percentile(values: Sequence[float], p: float) -> float:
    """Return the p-th percentile (0–100) of values using linear interpolation.

    Returns 0.0 for an empty input. ``p`` is clamped to [0, 100].
    """
    if not values:
        return 0.0
    p = max(0.0, min(100.0, p))
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    # Linear interpolation between closest ranks (NIST / numpy 'linear' method).
    rank = (p / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return float(ordered[low] + (ordered[high] - ordered[low]) * frac)


def _summarize(values: List[float]) -> Dict[str, float]:
    """min / max / mean / p50 / p90 / p95 / p99 for a list of numbers."""
    if not values:
        return {"count": 0, "min": 0.0, "max": 0.0, "mean": 0.0,
                "p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0}
    return {
        "count": len(values),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "mean": round(sum(values) / len(values), 2),
        "p50": round(percentile(values, 50), 2),
        "p90": round(percentile(values, 90), 2),
        "p95": round(percentile(values, 95), 2),
        "p99": round(percentile(values, 99), 2),
    }


def compute_perf_stats(results: Sequence[Any]) -> Dict[str, Any]:
    """Compute aggregate performance stats from a list of TestResult-like objects.

    Each result is expected to expose ``latency_ms``, optionally
    ``token_usage`` (with ``total_tokens``), ``estimated_cost``, and
    ``error``. Works with both pydantic models and plain dicts.

    Returns a dict with latency / ttft / tokens / cost summaries plus
    throughput and error rate.
    """
    def _get(obj, name, default=None):
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    latencies: List[float] = []
    ttfts: List[float] = []
    tokens: List[float] = []
    costs: List[float] = []
    errors = 0
    total = 0

    for r in results:
        total += 1
        if _get(r, "error"):
            errors += 1
        lat = _get(r, "latency_ms", 0) or 0
        if lat:
            latencies.append(float(lat))
        ttft = _get(r, "time_to_first_token_ms", None)
        if ttft:
            ttfts.append(float(ttft))
        tu = _get(r, "token_usage", None)
        if tu is not None:
            tt = tu.get("total_tokens") if isinstance(tu, dict) else getattr(tu, "total_tokens", 0)
            if tt:
                tokens.append(float(tt))
        cost = _get(r, "estimated_cost", 0) or 0
        if cost:
            costs.append(float(cost))

    return {
        "total_requests": total,
        "error_rate": round(errors / total, 4) if total else 0.0,
        "latency_ms": _summarize(latencies),
        "ttft_ms": _summarize(ttfts),
        "total_tokens": _summarize(tokens),
        "cost_usd": {
            "total": round(sum(costs), 6),
            "mean": round(sum(costs) / len(costs), 6) if costs else 0.0,
            "max": round(max(costs), 6) if costs else 0.0,
        },
    }


def summarize_latencies(latencies: Sequence[float]) -> Dict[str, float]:
    """Public helper: percentile summary for a raw list of latencies (ms).

    Used by the per-test ``repeat:N`` micro-benchmark.
    """
    return _summarize([float(v) for v in latencies])
