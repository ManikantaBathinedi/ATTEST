"""Markdown report generator.

Produces a concise Markdown summary of an ATTEST run, designed for:
  - GitHub / Azure DevOps pull-request comments
  - GitHub Actions job summaries (``$GITHUB_STEP_SUMMARY``)
  - Commit-status / chat notifications

It can also render a **regression diff** when a previous run is supplied,
highlighting tests that went pass -> fail (regressions) and fail -> pass
(fixes). This is what turns ATTEST baselines into a visible CI quality gate.

Usage::

    from attest.reporting.markdown_report import generate_markdown_report

    md = generate_markdown_report(summary)
    md = generate_markdown_report(summary, previous=previous_summary)  # with diff
    generate_markdown_report(summary, output_path="reports/summary.md")
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from attest.core.models import RunSummary, Status, TestResult


def _status_emoji(status: Status) -> str:
    return {
        Status.PASSED: "\u2705",
        Status.FAILED: "\u274c",
        Status.ERROR: "\u26a0\ufe0f",
        Status.SKIPPED: "\u23ed\ufe0f",
    }.get(status, "\u2753")


def _result_key(r: TestResult) -> str:
    return f"{r.agent}::{r.scenario}"


def _avg_score(r: TestResult) -> Optional[float]:
    if not r.scores:
        return None
    return sum(s.score for s in r.scores.values()) / len(r.scores)


def _diff_runs(
    summary: RunSummary, previous: RunSummary
) -> Tuple[List[TestResult], List[TestResult], List[TestResult]]:
    """Return (regressions, fixes, new_failures) comparing summary vs previous."""
    prev_status: Dict[str, Status] = {_result_key(r): r.status for r in previous.results}

    regressions: List[TestResult] = []
    fixes: List[TestResult] = []
    new_failures: List[TestResult] = []

    for r in summary.results:
        key = _result_key(r)
        was = prev_status.get(key)
        now_bad = r.status in (Status.FAILED, Status.ERROR)
        if was is None:
            if now_bad:
                new_failures.append(r)
            continue
        was_bad = was in (Status.FAILED, Status.ERROR)
        if was == Status.PASSED and now_bad:
            regressions.append(r)
        elif was_bad and r.status == Status.PASSED:
            fixes.append(r)
    return regressions, fixes, new_failures


def generate_markdown_report(
    summary: RunSummary,
    output_path: Optional[str] = None,
    previous: Optional[RunSummary] = None,
    title: str = "ATTEST Agent Test Results",
    max_rows: int = 50,
) -> str:
    """Build a Markdown report string (and optionally write it to a file).

    Args:
        summary: The current run results.
        output_path: If given, the Markdown is also written to this path.
        previous: An optional prior run to diff against for regression detection.
        title: Heading for the report.
        max_rows: Maximum number of result rows to render in the detail table.

    Returns:
        The Markdown content as a string.
    """
    pass_rate = round(summary.pass_rate * 100)
    lines: List[str] = []

    lines.append(f"## {title}")
    lines.append("")

    # Pass-rate trend vs previous (if provided)
    rate_suffix = ""
    if previous is not None and previous.total > 0:
        prev_rate = round(previous.pass_rate * 100)
        delta = pass_rate - prev_rate
        arrow = "\u2191" if delta > 0 else ("\u2193" if delta < 0 else "\u2192")
        sign = "+" if delta > 0 else ""
        rate_suffix = f" {arrow} ({sign}{delta} pts vs previous {prev_rate}%)"

    overall = "\u2705 PASSED" if summary.failed == 0 and summary.errors == 0 else "\u274c FAILED"
    lines.append(f"**Status:** {overall}  |  **Pass Rate:** {pass_rate}%{rate_suffix}")
    lines.append("")

    # Summary table
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Total | {summary.total} |")
    lines.append(f"| \u2705 Passed | {summary.passed} |")
    lines.append(f"| \u274c Failed | {summary.failed} |")
    lines.append(f"| \u26a0\ufe0f Errors | {summary.errors} |")
    if summary.skipped:
        lines.append(f"| \u23ed\ufe0f Skipped | {summary.skipped} |")
    lines.append(f"| Duration | {summary.duration_seconds:.1f}s |")
    if summary.total_cost > 0:
        lines.append(f"| Est. Cost | ${summary.total_cost:.4f} |")
    lines.append("")

    # Regression diff section
    if previous is not None:
        regressions, fixes, new_failures = _diff_runs(summary, previous)
        if regressions:
            lines.append(f"### \U0001f534 Regressions ({len(regressions)})")
            lines.append("Tests that were passing and are now failing:")
            lines.append("")
            for r in regressions:
                lines.append(f"- {_status_emoji(r.status)} `{r.scenario}` ({r.agent})")
            lines.append("")
        if new_failures:
            lines.append(f"### \U0001f7e0 New Failing Tests ({len(new_failures)})")
            lines.append("")
            for r in new_failures:
                lines.append(f"- {_status_emoji(r.status)} `{r.scenario}` ({r.agent})")
            lines.append("")
        if fixes:
            lines.append(f"### \U0001f7e2 Fixed ({len(fixes)})")
            lines.append("")
            for r in fixes:
                lines.append(f"- \u2705 `{r.scenario}` ({r.agent})")
            lines.append("")
        if not regressions and not new_failures and not fixes:
            lines.append("_No status changes vs the previous run._")
            lines.append("")

    # Failure details (collapsible)
    failures = [r for r in summary.results if r.status in (Status.FAILED, Status.ERROR)]
    if failures:
        lines.append("<details>")
        lines.append(f"<summary>Failure details ({len(failures)})</summary>")
        lines.append("")
        for r in failures:
            lines.append(f"**{_status_emoji(r.status)} {r.scenario}** ({r.agent})")
            if r.error:
                lines.append(f"> Error: {r.error}")
            failed_asserts = [a for a in r.assertions if not a.passed]
            for a in failed_asserts:
                msg = getattr(a, "message", "") or getattr(a, "name", "assertion")
                lines.append(f"> - \u274c {msg}")
            failed_scores = [(n, s) for n, s in r.scores.items() if not s.passed]
            for name, s in failed_scores:
                lines.append(f"> - \U0001f4c9 {name}: {s.score:.2f} (threshold not met)")
            lines.append("")
        lines.append("</details>")
        lines.append("")

    # Full results table (truncated)
    lines.append("<details>")
    lines.append(f"<summary>All results ({summary.total})</summary>")
    lines.append("")
    lines.append("| Test | Suite | Agent | Status | Score | Latency |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for r in summary.results[:max_rows]:
        score = _avg_score(r)
        score_str = f"{score:.2f}" if score is not None else "\u2014"
        lines.append(
            f"| {r.scenario} | {r.suite} | {r.agent} | "
            f"{_status_emoji(r.status)} {r.status.value} | {score_str} | "
            f"{round(r.latency_ms)}ms |"
        )
    if summary.total > max_rows:
        lines.append(f"| _\u2026 {summary.total - max_rows} more_ | | | | | |")
    lines.append("")
    lines.append("</details>")
    lines.append("")
    lines.append("<sub>Generated by ATTEST \u2014 Agent Testing & Trust Evaluation Suite</sub>")

    content = "\n".join(lines)

    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    return content
