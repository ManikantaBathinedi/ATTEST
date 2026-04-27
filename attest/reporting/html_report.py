"""HTML report generator.

Creates a self-contained HTML file with test results that you can
open in any browser. No external dependencies, no server needed.

The report includes:
- Summary cards (total, passed, failed, pass rate)
- Results table with color-coded status
- Expandable conversation traces for each test
- Failure details with clear explanations
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from attest.core.models import RunSummary, Status


def generate_html_report(
    summary: RunSummary,
    output_path: Optional[str] = None,
) -> str:
    """Generate an HTML report from a RunSummary.

    Args:
        summary: The test run results.
        output_path: Where to save. If None, returns HTML string only.

    Returns:
        The HTML content as a string.
    """
    html = _build_html(summary)

    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")

    return html


def _build_html(summary: RunSummary) -> str:
    """Build the complete HTML report."""

    # Build results rows
    rows_html = ""
    for r in summary.results:
        status_class = {
            Status.PASSED: "passed",
            Status.FAILED: "failed",
            Status.ERROR: "error",
            Status.SKIPPED: "skipped",
        }.get(r.status, "error")

        status_icon = {
            Status.PASSED: "✅",
            Status.FAILED: "❌",
            Status.ERROR: "⚠️",
            Status.SKIPPED: "⏭️",
        }.get(r.status, "?")

        # Build scores display
        scores_html = ""
        if r.scores:
            for name, score in r.scores.items():
                color = "#22c55e" if score.passed else "#ef4444"
                scores_html += f'<span style="color:{color}">{name}: {score.score:.2f}</span> '

        # Build assertion failures
        failures_html = ""
        failed_assertions = [a for a in r.assertions if not a.passed]
        if failed_assertions:
            for a in failed_assertions:
                failures_html += f'<div class="failure">↳ {a.name}: {a.message}</div>'

        # Build error display
        if r.error:
            failures_html += f'<div class="failure">↳ {r.error}</div>'

        # Build conversation trace
        conversation_html = ""
        for msg in r.messages:
            role_icon = "👤" if msg.role == "user" else "🤖"
            content_preview = msg.content[:300]
            if len(msg.content) > 300:
                content_preview += "..."
            conversation_html += f"""
                <div class="message {msg.role}">
                    <strong>{role_icon} {msg.role.title()}</strong>
                    <p>{content_preview}</p>
                </div>"""

        # Tool calls
        if r.tool_calls:
            tools_str = ", ".join(f"{tc.name}({tc.arguments})" for tc in r.tool_calls)
            conversation_html += f'<div class="message tool">🔧 Tools: {tools_str}</div>'

        rows_html += f"""
        <div class="result-card {status_class}">
            <div class="result-header" onclick="this.parentElement.classList.toggle('expanded')">
                <span class="status-icon">{status_icon}</span>
                <span class="test-name">{r.scenario}</span>
                <span class="suite-name">{r.suite}</span>
                <span class="scores">{scores_html}</span>
                <span class="latency">{r.latency_ms:.0f}ms</span>
            </div>
            {failures_html}
            <div class="conversation">{conversation_html}</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ATTEST Report — {summary.run_id}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; padding: 20px; }}
        .container {{ max-width: 1000px; margin: 0 auto; }}

        h1 {{ color: #f8fafc; margin-bottom: 5px; font-size: 24px; }}
        .subtitle {{ color: #94a3b8; margin-bottom: 25px; font-size: 14px; }}

        /* Summary cards */
        .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 30px; }}
        .card {{ background: #1e293b; border-radius: 10px; padding: 16px; text-align: center; }}
        .card .value {{ font-size: 28px; font-weight: bold; color: #f8fafc; }}
        .card .label {{ font-size: 12px; color: #94a3b8; margin-top: 4px; }}
        .card.pass-rate .value {{ color: {"#22c55e" if summary.pass_rate >= 0.8 else "#eab308" if summary.pass_rate >= 0.5 else "#ef4444"}; }}

        /* Results */
        .result-card {{ background: #1e293b; border-radius: 8px; margin-bottom: 8px; overflow: hidden; border-left: 4px solid #475569; }}
        .result-card.passed {{ border-left-color: #22c55e; }}
        .result-card.failed {{ border-left-color: #ef4444; }}
        .result-card.error {{ border-left-color: #eab308; }}

        .result-header {{ display: flex; align-items: center; gap: 12px; padding: 12px 16px; cursor: pointer; }}
        .result-header:hover {{ background: #334155; }}
        .status-icon {{ font-size: 16px; }}
        .test-name {{ font-weight: 600; color: #f8fafc; flex: 1; }}
        .suite-name {{ color: #64748b; font-size: 12px; }}
        .scores {{ font-size: 12px; }}
        .latency {{ color: #94a3b8; font-size: 12px; min-width: 60px; text-align: right; }}

        .failure {{ padding: 8px 16px 8px 44px; color: #fca5a5; font-size: 13px; background: #1a1a2e; }}

        .conversation {{ display: none; padding: 12px 16px 12px 44px; }}
        .result-card.expanded .conversation {{ display: block; }}
        .message {{ margin-bottom: 8px; padding: 8px 12px; border-radius: 6px; font-size: 13px; }}
        .message.user {{ background: #1e3a5f; }}
        .message.assistant {{ background: #1a2e1a; }}
        .message.tool {{ background: #2e2a1a; color: #fbbf24; font-size: 12px; }}
        .message strong {{ display: block; margin-bottom: 4px; font-size: 11px; color: #94a3b8; }}
        .message p {{ line-height: 1.5; }}

        .footer {{ text-align: center; color: #475569; margin-top: 30px; font-size: 12px; }}
        .click-hint {{ text-align: center; color: #64748b; font-size: 12px; margin-bottom: 15px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>ATTEST Report</h1>
        <div class="subtitle">Run: {summary.run_id} | {summary.timestamp.strftime('%Y-%m-%d %H:%M:%S')} | Duration: {summary.duration_seconds:.1f}s</div>

        <div class="summary">
            <div class="card"><div class="value">{summary.total}</div><div class="label">Total Tests</div></div>
            <div class="card"><div class="value" style="color:#22c55e">{summary.passed}</div><div class="label">Passed</div></div>
            <div class="card"><div class="value" style="color:#ef4444">{summary.failed}</div><div class="label">Failed</div></div>
            <div class="card"><div class="value" style="color:#eab308">{summary.errors}</div><div class="label">Errors</div></div>
            <div class="card pass-rate"><div class="value">{summary.pass_rate:.0%}</div><div class="label">Pass Rate</div></div>
            <div class="card"><div class="value">{summary.duration_seconds:.1f}s</div><div class="label">Duration</div></div>
        </div>

        <div class="click-hint">Click any test to expand conversation details</div>

        {rows_html}

        <div class="footer">Generated by ATTEST — Agent Testing & Trust Evaluation Suite</div>
    </div>
</body>
</html>"""
