"""Quality-gate evaluation.

Turns a run's summary into a pass/fail decision against configured thresholds,
so ``attest run --gate`` can fail CI when quality/latency/cost regress.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def evaluate_gates(summary: Any, gates: Any) -> Tuple[bool, List[str]]:
    """Check a RunSummary against GatesConfig thresholds.

    Returns (passed, violations). ``passed`` is True when no configured
    threshold is violated. Unset thresholds (None) are skipped.
    """
    violations: List[str] = []

    def _g(name):
        return getattr(gates, name, None)

    total = getattr(summary, "total", 0) or 0
    pass_rate = getattr(summary, "pass_rate", 0.0) or 0.0
    failed = getattr(summary, "failed", 0) or 0
    errors = getattr(summary, "errors", 0) or 0
    total_cost = getattr(summary, "total_cost", 0.0) or 0.0
    avg_score = getattr(summary, "overall_score", 0.0) or 0.0
    perf = getattr(summary, "perf", {}) or {}
    p95 = (perf.get("latency_ms") or {}).get("p95", 0.0) if isinstance(perf, dict) else 0.0

    min_pass_rate = _g("min_pass_rate")
    if min_pass_rate is not None and total > 0 and pass_rate < min_pass_rate:
        violations.append(
            f"pass rate {pass_rate:.0%} < required {min_pass_rate:.0%}"
        )

    max_failed = _g("max_failed")
    if max_failed is not None and failed > max_failed:
        violations.append(f"{failed} failed > allowed {max_failed}")

    max_errors = _g("max_errors")
    if max_errors is not None and errors > max_errors:
        violations.append(f"{errors} errored > allowed {max_errors}")

    max_p95 = _g("max_p95_latency_ms")
    if max_p95 is not None and p95 > max_p95:
        violations.append(f"p95 latency {p95:.0f}ms > allowed {max_p95:.0f}ms")

    max_cost = _g("max_total_cost")
    if max_cost is not None and total_cost > max_cost:
        violations.append(f"cost ${total_cost:.4f} > allowed ${max_cost:.4f}")

    min_avg_score = _g("min_avg_score")
    if min_avg_score is not None and avg_score < min_avg_score:
        violations.append(
            f"avg score {avg_score:.2f} < required {min_avg_score:.2f}"
        )

    return (len(violations) == 0, violations)


def gates_are_configured(gates: Any) -> bool:
    """True if any gate threshold is set."""
    for name in (
        "min_pass_rate", "max_failed", "max_errors",
        "max_p95_latency_ms", "max_total_cost", "min_avg_score",
    ):
        if getattr(gates, name, None) is not None:
            return True
    return False
