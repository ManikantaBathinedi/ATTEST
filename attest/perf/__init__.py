"""Agent performance utilities for ATTEST.

Aggregates the latency / TTFT / token / cost data ATTEST already captures into
run-level performance insight (percentiles, throughput, error rate), and powers
the per-test ``repeat:N`` micro-benchmark.
"""

from attest.perf.stats import (
    compute_perf_stats,
    percentile,
    summarize_latencies,
)

__all__ = ["compute_perf_stats", "percentile", "summarize_latencies"]
