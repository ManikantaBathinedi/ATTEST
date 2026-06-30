"""Baseline comparison HTML report.

Renders a self-contained report from a list of baseline-diff entries (the same
shape produced by the dashboard's ``/api/baseline/diff``). Shows, per scenario,
whether content / tool calls / routing changed, with a full before→after view.
"""

from __future__ import annotations

import html as _html
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _esc(text) -> str:
    return _html.escape(str(text), quote=True)


def _status_meta(status: str):
    return {
        "match": ("#22c55e", "✅", "Match"),
        "changed": ("#ef4444", "🔄", "Changed"),
        "no_baseline": ("#64748b", "⏭️", "No baseline"),
    }.get(status, ("#64748b", "•", status))


def _diff_section(title: str, baseline_val, current_val, changed: bool) -> str:
    state_color = "#ef4444" if changed else "#22c55e"
    state_text = "changed" if changed else "unchanged"
    return f"""
        <div class="diff-block">
            <div class="diff-head"><span>{_esc(title)}</span><span class="diff-state" style="color:{state_color}">{state_text}</span></div>
            <div class="diff-cols">
                <div class="diff-col">
                    <div class="diff-label">Baseline (golden)</div>
                    <pre>{_esc(baseline_val) if str(baseline_val) else '—'}</pre>
                </div>
                <div class="diff-col">
                    <div class="diff-label">Current</div>
                    <pre>{_esc(current_val) if str(current_val) else '—'}</pre>
                </div>
            </div>
        </div>"""


def generate_baseline_report(
    diffs: List[Dict[str, Any]],
    timestamp: Optional[str] = None,
    output_path: Optional[str] = None,
) -> str:
    """Build an HTML baseline-comparison report and optionally write it."""
    total = len(diffs)
    matches = sum(1 for d in diffs if d.get("status") == "match")
    changed = sum(1 for d in diffs if d.get("status") == "changed")
    no_baseline = sum(1 for d in diffs if d.get("status") == "no_baseline")
    ts = timestamp or datetime.utcnow().isoformat()
    try:
        ts_display = datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        ts_display = ts

    cards = ""
    for d in diffs:
        status = d.get("status", "")
        color, icon, label = _status_meta(status)
        scenario = _esc(d.get("scenario", ""))
        agent = _esc(d.get("agent", ""))

        body = ""
        if status == "changed":
            badges = ""
            if d.get("content_match") is False:
                badges += '<span class="badge" style="background:#ef444422;color:#ef4444">content</span>'
            if d.get("tool_calls_match") is False:
                badges += '<span class="badge" style="background:#f9731622;color:#f97316">tools</span>'
            if d.get("routing_match") is False:
                badges += '<span class="badge" style="background:#a78bfa22;color:#a78bfa">routing</span>'
            body += f'<div class="badges">{badges}</div>'
            body += _diff_section(
                "Response content",
                d.get("baseline_content", ""),
                d.get("current_content", ""),
                d.get("content_match") is False,
            )
            if d.get("tool_calls_match") is False:
                body += _diff_section(
                    "Tool calls",
                    ", ".join(d.get("baseline_tools", []) or []),
                    ", ".join(d.get("current_tools", []) or []),
                    True,
                )
            if d.get("routing_match") is False:
                body += _diff_section(
                    "Routing path",
                    " → ".join(d.get("baseline_routing", []) or []),
                    " → ".join(d.get("current_routing", []) or []),
                    True,
                )
        elif status == "match":
            body = '<div class="ok-note">No changes — current response matches the saved baseline.</div>'
        else:
            body = '<div class="ok-note">No baseline saved for this scenario yet.</div>'

        cards += f"""
        <div class="card {status}">
            <div class="card-head" onclick="this.parentElement.classList.toggle('open')">
                <span>{icon}</span>
                <span class="scenario">{scenario}</span>
                <span class="agent">{agent}</span>
                <span class="status-label" style="color:{color}">{label}</span>
                <span class="chevron">▾</span>
            </div>
            <div class="card-body">{body}</div>
        </div>"""

    return _write(
        f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ATTEST Baseline Comparison</title>
<style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#0b1220; color:#e2e8f0; padding:28px 20px; line-height:1.5; }}
    .container {{ max-width:1080px; margin:0 auto; }}
    .head {{ display:flex; align-items:center; gap:12px; }}
    .logo {{ font-size:22px; font-weight:800; background:linear-gradient(90deg,#60a5fa,#a78bfa); -webkit-background-clip:text; background-clip:text; color:transparent; }}
    h1 {{ font-size:22px; color:#f8fafc; }}
    .subtitle {{ color:#94a3b8; font-size:13px; margin:4px 0 22px; }}
    .summary {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:12px; margin-bottom:24px; }}
    .scard {{ background:linear-gradient(180deg,#16213c,#111a2e); border:1px solid #1e2a47; border-radius:12px; padding:16px; text-align:center; }}
    .scard .v {{ font-size:26px; font-weight:700; }}
    .scard .l {{ font-size:11px; color:#94a3b8; text-transform:uppercase; letter-spacing:.4px; margin-top:4px; }}
    .card {{ background:#111a2e; border:1px solid #1e2a47; border-left:4px solid #475569; border-radius:10px; margin-bottom:10px; overflow:hidden; }}
    .card.match {{ border-left-color:#22c55e; }}
    .card.changed {{ border-left-color:#ef4444; }}
    .card.no_baseline {{ border-left-color:#64748b; }}
    .card-head {{ display:flex; align-items:center; gap:12px; padding:13px 16px; cursor:pointer; }}
    .card-head:hover {{ background:#16213c; }}
    .scenario {{ font-weight:600; color:#f8fafc; }}
    .agent {{ color:#818cf8; font-size:12px; flex:1; }}
    .status-label {{ font-size:12px; font-weight:600; }}
    .chevron {{ color:#475569; transition:transform .15s; }}
    .card.open .chevron {{ transform:rotate(180deg); }}
    .card-body {{ display:none; padding:6px 16px 16px; }}
    .card.open .card-body {{ display:block; }}
    .badges {{ margin:8px 0; }}
    .badge {{ font-size:10px; padding:2px 7px; border-radius:4px; margin-right:6px; }}
    .ok-note {{ color:#94a3b8; font-size:13px; padding:8px 0; }}
    .diff-block {{ margin-top:12px; }}
    .diff-head {{ display:flex; justify-content:space-between; font-size:11px; text-transform:uppercase; letter-spacing:.5px; color:#7c8aa5; margin-bottom:6px; }}
    .diff-state {{ font-weight:700; }}
    .diff-cols {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }}
    .diff-col {{ background:#0f1830; border:1px solid #1e2a47; border-radius:8px; padding:8px 10px; }}
    .diff-label {{ font-size:10px; color:#64748b; text-transform:uppercase; margin-bottom:4px; }}
    pre {{ white-space:pre-wrap; word-break:break-word; font-size:12.5px; color:#cbd5e1; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
    .footer {{ text-align:center; color:#475569; margin-top:30px; font-size:12px; }}
    @media(max-width:680px){{ .diff-cols{{grid-template-columns:1fr;}} }}
</style></head>
<body>
<div class="container">
    <div class="head"><span class="logo">ATTEST</span><h1>Baseline Comparison</h1></div>
    <div class="subtitle">Generated {ts_display} · compares the latest run against saved golden baselines</div>
    <div class="summary">
        <div class="scard"><div class="v">{total}</div><div class="l">Scenarios</div></div>
        <div class="scard"><div class="v" style="color:#22c55e">{matches}</div><div class="l">Match</div></div>
        <div class="scard"><div class="v" style="color:#ef4444">{changed}</div><div class="l">Changed</div></div>
        <div class="scard"><div class="v" style="color:#64748b">{no_baseline}</div><div class="l">No baseline</div></div>
    </div>
    <div style="color:#64748b;font-size:12px;margin-bottom:14px">Click any scenario to expand the full before → after comparison.</div>
    {cards}
    <div class="footer">Generated by ATTEST — Agent Testing &amp; Trust Evaluation Suite</div>
</div>
</body></html>""",
        output_path,
    )


def _write(html: str, output_path: Optional[str]) -> str:
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
    return html
