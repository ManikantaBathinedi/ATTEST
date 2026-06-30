"""HTML report generator.

Creates a self-contained, professional HTML report you can open in any browser
or attach to a PR. No external dependencies, no server needed.

The report includes:
- Summary cards (total, passed, failed, errors, pass rate, avg score, tokens, cost, duration)
- Per-test cards with status, suite, agent, latency
- Evaluator scores grouped with backend badges
- Assertion results (pass/fail with messages)
- Multi-agent routing (handled-by + routing path)
- Tool calls with arguments
- Token usage + estimated cost
- Full conversation trace
"""

from __future__ import annotations

import html as _html
from pathlib import Path
from typing import Optional

from attest.core.models import RunSummary, Status


def _esc(text) -> str:
    """HTML-escape any value for safe embedding."""
    return _html.escape(str(text), quote=True)


# Backend → (short badge, color)
_BACKEND_BADGE = {
    "builtin": ("Built-in", "#38bdf8"),
    "deepeval": ("DeepEval", "#a78bfa"),
    "azure": ("Azure", "#34d399"),
    "azure_eval": ("Azure", "#34d399"),
    "ragas": ("RAGAS", "#fbbf24"),
    "skipped": ("Skipped", "#64748b"),
}


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


def _scores_block(r) -> str:
    """Render the evaluator scores grid with backend badges."""
    if not r.scores:
        return ""
    cells = ""
    for name, s in sorted(r.scores.items(), key=lambda kv: getattr(kv[1], "score", 0.0) or 0.0):
        passed = getattr(s, "passed", False)
        backend = getattr(s, "backend", "builtin") or "builtin"
        badge_label, badge_color = _BACKEND_BADGE.get(backend, (backend, "#94a3b8"))
        bar_color = "#22c55e" if passed else "#ef4444"
        score = getattr(s, "score", 0.0) or 0.0
        pct = max(0, min(100, int(score * 100)))
        reason = getattr(s, "reason", "") or ""
        cells += f"""
            <div class="score-cell" title="{_esc(reason)}">
                <div class="score-top">
                    <span class="backend-badge" style="background:{badge_color}22;color:{badge_color}">{_esc(badge_label)}</span>
                    <span class="score-name">{_esc(name)}</span>
                    <span class="score-val" style="color:{bar_color}">{score:.2f}</span>
                </div>
                <div class="score-bar"><div class="score-fill" style="width:{pct}%;background:{bar_color}"></div></div>
            </div>"""
    vals = [getattr(s, "score", 0.0) or 0.0 for s in r.scores.values()]
    avg = sum(vals) / len(vals) if vals else 0.0
    n_pass = sum(1 for s in r.scores.values() if getattr(s, "passed", False))
    return f"""
        <div class="section-title">Evaluator Scores
            <span class="pill">{n_pass}/{len(r.scores)} passed · avg {avg:.2f}</span>
        </div>
        <div class="score-grid">{cells}</div>"""


def _assertions_block(r) -> str:
    if not r.assertions:
        return ""
    items = ""
    for a in r.assertions:
        ok = getattr(a, "passed", False)
        icon = "✓" if ok else "✗"
        color = "#22c55e" if ok else "#ef4444"
        msg = getattr(a, "message", "") or ""
        msg_html = f'<span class="assert-msg">— {_esc(msg)}</span>' if msg else ""
        items += (
            f'<div class="assert-row"><span style="color:{color}">{icon}</span> '
            f'<span class="assert-name">{_esc(getattr(a, "name", ""))}</span> {msg_html}</div>'
        )
    return f'<div class="section-title">Assertions</div><div class="assert-list">{items}</div>'


def _routing_block(r) -> str:
    handled_by = getattr(r, "handled_by", None)
    routing_path = getattr(r, "routing_path", None) or []
    if not handled_by and not routing_path:
        return ""
    path_html = ""
    if routing_path:
        chain = " → ".join(_esc(p) for p in routing_path)
        path_html = f'<div class="route-line">Routing path: <strong>{chain}</strong></div>'
    handled_html = ""
    if handled_by:
        handled_html = f'<div class="route-line">Handled by: <strong>{_esc(handled_by)}</strong></div>'
    return f'<div class="section-title">🔀 Multi-Agent Routing</div><div class="route-box">{handled_html}{path_html}</div>'


def _tools_block(r) -> str:
    if not r.tool_calls:
        return ""
    items = ""
    for tc in r.tool_calls:
        args = getattr(tc, "arguments", {})
        items += f'<div class="tool-row">🔧 <strong>{_esc(getattr(tc, "name", ""))}</strong>(<span class="tool-args">{_esc(args)}</span>)</div>'
    return f'<div class="section-title">Tool Calls</div><div class="tool-list">{items}</div>'


def _cost_block(r) -> str:
    tu = getattr(r, "token_usage", None)
    cost = getattr(r, "estimated_cost", 0.0) or 0.0
    if not tu and cost <= 0:
        return ""
    parts = ""
    if tu:
        parts += f'<span>Input: <strong>{tu.input_tokens}</strong></span>'
        parts += f'<span>Output: <strong>{tu.output_tokens}</strong></span>'
        parts += f'<span>Total: <strong>{tu.total_tokens}</strong></span>'
    if cost > 0:
        parts += f'<span>Est. cost: <strong style="color:#22d3ee">${cost:.5f}</strong></span>'
    return f'<div class="section-title">💰 Tokens &amp; Cost</div><div class="cost-box">{parts}</div>'


def _conversation_block(r) -> str:
    if not r.messages:
        return ""
    msgs = ""
    for m in r.messages:
        role = getattr(m, "role", "user")
        icon = "👤" if role == "user" else "🤖"
        content = _esc(getattr(m, "content", ""))
        msgs += f'<div class="message {role}"><strong>{icon} {role.title()}</strong><p>{content}</p></div>'
    return f'<div class="section-title">Conversation</div>{msgs}'


def _perf_block(perf: dict) -> str:
    """Run-level performance percentiles panel (latency / TTFT / throughput)."""
    if not perf:
        return ""
    lat = perf.get("latency_ms") or {}
    ttft = perf.get("ttft_ms") or {}
    if not lat.get("count") and not perf.get("throughput_rps"):
        return ""

    def metric(label, value, unit=""):
        return (f'<div class="perf-cell"><div class="perf-v">{value}{unit}</div>'
                f'<div class="perf-l">{label}</div></div>')

    cells = ""
    if lat.get("count"):
        cells += metric("Latency p50", f"{lat.get('p50', 0):.0f}", " ms")
        cells += metric("Latency p95", f"{lat.get('p95', 0):.0f}", " ms")
        cells += metric("Latency p99", f"{lat.get('p99', 0):.0f}", " ms")
        cells += metric("Latency max", f"{lat.get('max', 0):.0f}", " ms")
    if perf.get("throughput_rps"):
        cells += metric("Throughput", f"{perf['throughput_rps']:.2f}", " req/s")
    if perf.get("error_rate") is not None:
        cells += metric("Error rate", f"{perf['error_rate'] * 100:.1f}", " %")
    if ttft.get("count"):
        cells += metric("TTFT p95", f"{ttft.get('p95', 0):.0f}", " ms")
    if not cells:
        return ""
    return f"""
        <div class="perf-panel">
            <div class="perf-title">⚡ Performance (agent latency distribution)</div>
            <div class="perf-grid">{cells}</div>
        </div>"""


def _build_html(summary: RunSummary) -> str:
    """Build the complete HTML report."""

    total_in = total_out = total_tok = 0
    score_vals = []
    for r in summary.results:
        tu = getattr(r, "token_usage", None)
        if tu:
            total_in += tu.input_tokens or 0
            total_out += tu.output_tokens or 0
            total_tok += tu.total_tokens or 0
        if r.scores:
            vals = [getattr(s, "score", 0.0) or 0.0 for s in r.scores.values()]
            if vals:
                score_vals.append(sum(vals) / len(vals))
    avg_score = sum(score_vals) / len(score_vals) if score_vals else 0.0
    total_cost = getattr(summary, "total_cost", 0.0) or 0.0

    status_meta = {
        Status.PASSED: ("passed", "✅"),
        Status.FAILED: ("failed", "❌"),
        Status.ERROR: ("error", "⚠️"),
        Status.SKIPPED: ("skipped", "⏭️"),
    }

    cards = ""
    for r in summary.results:
        status_class, status_icon = status_meta.get(r.status, ("error", "?"))

        score_pill = ""
        if r.scores:
            vals = [getattr(s, "score", 0.0) or 0.0 for s in r.scores.values()]
            avg = sum(vals) / len(vals) if vals else 0.0
            n_pass = sum(1 for s in r.scores.values() if getattr(s, "passed", False))
            score_pill = f'<span class="hdr-pill">{avg:.2f} avg · {n_pass}/{len(r.scores)} ✓</span>'

        n_assert = len(r.assertions)
        n_assert_pass = sum(1 for a in r.assertions if getattr(a, "passed", False))
        assert_pill = f'<span class="hdr-assert">{n_assert_pass}/{n_assert} asserts</span>' if n_assert else ""

        agent = _esc(getattr(r, "agent", "") or "")
        body = (
            _scores_block(r)
            + _assertions_block(r)
            + _routing_block(r)
            + _tools_block(r)
            + _cost_block(r)
            + _conversation_block(r)
        )
        error_html = f'<div class="error-banner">⚠️ {_esc(r.error)}</div>' if r.error else ""

        cards += f"""
        <div class="result-card {status_class}">
            <div class="result-header" onclick="this.parentElement.classList.toggle('expanded')">
                <span class="status-icon">{status_icon}</span>
                <span class="test-name">{_esc(r.scenario)}</span>
                <span class="suite-name">{_esc(r.suite)}</span>
                <span class="agent-name">{agent}</span>
                {score_pill}
                {assert_pill}
                <span class="latency">{r.latency_ms:.0f}ms</span>
                <span class="chevron">▾</span>
            </div>
            {error_html}
            <div class="result-body">{body}</div>
        </div>"""

    pass_color = "#22c55e" if summary.pass_rate >= 0.8 else "#eab308" if summary.pass_rate >= 0.5 else "#ef4444"
    ts = summary.timestamp.strftime("%Y-%m-%d %H:%M:%S")

    cost_card = (
        f'<div class="card"><div class="value" style="color:#22d3ee">${total_cost:.4f}</div><div class="label">Est. Cost</div></div>'
        if total_cost > 0 else ""
    )
    token_card = (
        f'<div class="card"><div class="value">{total_tok:,}</div><div class="label">Tokens</div></div>'
        if total_tok > 0 else ""
    )
    score_card = (
        f'<div class="card"><div class="value" style="color:#a78bfa">{avg_score:.2f}</div><div class="label">Avg Score</div></div>'
        if score_vals else ""
    )

    # Performance percentiles block (agent latency distribution).
    perf = getattr(summary, "perf", None) or {}
    perf_html = _perf_block(perf)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ATTEST Report — {_esc(summary.run_id)}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0b1220; color: #e2e8f0; padding: 28px 20px; line-height: 1.5; }}
        .container {{ max-width: 1080px; margin: 0 auto; }}

        .report-head {{ display:flex; align-items:center; gap:12px; margin-bottom:4px; }}
        .logo {{ font-size:22px; font-weight:800; letter-spacing:.5px; background:linear-gradient(90deg,#60a5fa,#a78bfa); -webkit-background-clip:text; background-clip:text; color:transparent; }}
        h1 {{ color: #f8fafc; font-size: 22px; font-weight:700; }}
        .subtitle {{ color: #94a3b8; margin-bottom: 24px; font-size: 13px; }}
        .subtitle .sep {{ color:#334155; margin:0 8px; }}

        .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px; margin-bottom: 26px; }}
        .card {{ background: linear-gradient(180deg,#16213c,#111a2e); border:1px solid #1e2a47; border-radius: 12px; padding: 16px; text-align: center; }}
        .card .value {{ font-size: 26px; font-weight: 700; color: #f8fafc; }}
        .card .label {{ font-size: 11px; color: #94a3b8; margin-top: 4px; text-transform:uppercase; letter-spacing:.4px; }}
        .card.pass-rate .value {{ color: {pass_color}; }}

        .click-hint {{ color: #64748b; font-size: 12px; margin-bottom: 14px; }}

        .result-card {{ background: #111a2e; border:1px solid #1e2a47; border-radius: 10px; margin-bottom: 10px; overflow: hidden; border-left: 4px solid #475569; }}
        .result-card.passed {{ border-left-color: #22c55e; }}
        .result-card.failed {{ border-left-color: #ef4444; }}
        .result-card.error {{ border-left-color: #eab308; }}
        .result-card.skipped {{ border-left-color: #64748b; }}

        .result-header {{ display: flex; align-items: center; gap: 12px; padding: 13px 16px; cursor: pointer; }}
        .result-header:hover {{ background: #16213c; }}
        .status-icon {{ font-size: 15px; }}
        .test-name {{ font-weight: 600; color: #f8fafc; }}
        .suite-name {{ color: #64748b; font-size: 12px; }}
        .agent-name {{ color: #818cf8; font-size: 12px; flex:1; }}
        .hdr-pill {{ font-size: 11px; background:#a78bfa22; color:#c4b5fd; padding:2px 8px; border-radius:10px; }}
        .hdr-assert {{ font-size: 11px; background:#33415544; color:#94a3b8; padding:2px 8px; border-radius:10px; }}
        .latency {{ color: #94a3b8; font-size: 12px; min-width: 56px; text-align: right; }}
        .chevron {{ color:#475569; transition:transform .15s; }}
        .result-card.expanded .chevron {{ transform: rotate(180deg); }}

        .error-banner {{ padding: 10px 16px; color: #fca5a5; font-size: 13px; background: #2a1620; border-top:1px solid #3b1d2a; }}

        .result-body {{ display: none; padding: 6px 16px 16px; }}
        .result-card.expanded .result-body {{ display: block; }}

        .section-title {{ font-size: 11px; text-transform: uppercase; letter-spacing:.5px; color:#7c8aa5; margin:16px 0 8px; font-weight:600; }}
        .pill {{ text-transform:none; letter-spacing:0; font-weight:500; background:#1e293b; color:#94a3b8; font-size:11px; padding:2px 8px; border-radius:10px; margin-left:8px; }}

        .score-grid {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); gap:8px; }}
        .score-cell {{ background:#0f1830; border:1px solid #1e2a47; border-radius:8px; padding:8px 10px; }}
        .score-top {{ display:flex; align-items:center; gap:6px; margin-bottom:6px; }}
        .backend-badge {{ font-size:9px; padding:1px 5px; border-radius:4px; font-weight:700; text-transform:uppercase; }}
        .score-name {{ flex:1; font-size:12px; color:#cbd5e1; }}
        .score-val {{ font-size:13px; font-weight:700; }}
        .score-bar {{ height:5px; background:#1e293b; border-radius:3px; overflow:hidden; }}
        .score-fill {{ height:100%; border-radius:3px; }}

        .assert-list, .tool-list {{ display:flex; flex-direction:column; gap:4px; }}
        .assert-row {{ font-size:13px; }}
        .assert-name {{ color:#cbd5e1; }}
        .assert-msg {{ color:#7c8aa5; font-size:12px; }}
        .route-box, .cost-box {{ background:#0f1830; border:1px solid #1e2a47; border-radius:8px; padding:10px 12px; font-size:13px; }}
        .route-line {{ color:#c4b5fd; margin:2px 0; }}
        .cost-box {{ display:flex; gap:18px; flex-wrap:wrap; color:#94a3b8; }}
        .tool-row {{ font-size:13px; color:#cbd5e1; }}
        .tool-args {{ color:#fbbf24; font-size:12px; }}

        .message {{ margin-bottom: 6px; padding: 9px 12px; border-radius: 8px; font-size: 13px; }}
        .message.user {{ background: #14233f; }}
        .message.assistant {{ background: #122a1c; }}
        .message strong {{ display: block; margin-bottom: 4px; font-size: 11px; color: #94a3b8; }}
        .message p {{ line-height: 1.55; white-space: pre-wrap; }}

        .footer {{ text-align: center; color: #475569; margin-top: 30px; font-size: 12px; }}
        .perf-panel {{ background:linear-gradient(180deg,#16213c,#111a2e); border:1px solid #1e2a47; border-radius:12px; padding:14px 16px; margin-bottom:24px; }}
        .perf-title {{ font-size:12px; text-transform:uppercase; letter-spacing:.5px; color:#7c8aa5; font-weight:600; margin-bottom:10px; }}
        .perf-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(96px,1fr)); gap:10px; }}
        .perf-cell {{ background:#0f1830; border:1px solid #1e2a47; border-radius:8px; padding:10px; text-align:center; }}
        .perf-v {{ font-size:18px; font-weight:700; color:#22d3ee; }}
        .perf-l {{ font-size:10px; color:#94a3b8; text-transform:uppercase; letter-spacing:.3px; margin-top:3px; }}
    </style></head>
<body>
    <div class="container">
        <div class="report-head">
            <span class="logo">ATTEST</span>
            <h1>Test Report</h1>
        </div>
        <div class="subtitle">
            Run: {_esc(summary.run_id)}<span class="sep">|</span>{ts}<span class="sep">|</span>Duration: {summary.duration_seconds:.1f}s
        </div>

        <div class="summary">
            <div class="card"><div class="value">{summary.total}</div><div class="label">Total Tests</div></div>
            <div class="card"><div class="value" style="color:#22c55e">{summary.passed}</div><div class="label">Passed</div></div>
            <div class="card"><div class="value" style="color:#ef4444">{summary.failed}</div><div class="label">Failed</div></div>
            <div class="card"><div class="value" style="color:#eab308">{summary.errors}</div><div class="label">Errors</div></div>
            <div class="card pass-rate"><div class="value">{summary.pass_rate:.0%}</div><div class="label">Pass Rate</div></div>
            {score_card}
            {token_card}
            {cost_card}
            <div class="card"><div class="value">{summary.duration_seconds:.1f}s</div><div class="label">Duration</div></div>
        </div>

        {perf_html}

        <div class="click-hint">Click any test to expand scores, assertions, routing, tokens &amp; conversation.</div>

        {cards}

        <div class="footer">Generated by ATTEST — Agent Testing &amp; Trust Evaluation Suite</div>
    </div>
</body>
</html>"""
