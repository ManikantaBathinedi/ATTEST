"""Run-completion notifications (Slack / Teams / generic webhook).

Fires a single POST to a configured webhook when a run finishes. Fully
opt-in and failure-safe — a notification error never breaks a test run.
"""

from __future__ import annotations

from typing import Any, List, Optional


def _find_regressions(summary: Any, previous: Any) -> List[str]:
    """Names of tests that passed previously but now fail/error."""
    if previous is None:
        return []

    def _is_passed(status: Any) -> bool:
        # Handle enum (Status.PASSED), enum .value ("passed"), or raw string.
        val = getattr(status, "value", status)
        return str(val).lower() == "passed"

    prev_status = {r.scenario: r.status for r in getattr(previous, "results", [])}
    regressed = []
    for r in getattr(summary, "results", []):
        was = prev_status.get(r.scenario)
        if was is not None and _is_passed(was) and not _is_passed(r.status):
            regressed.append(r.scenario)
    return regressed


def _should_send(on: str, summary: Any, previous: Any) -> bool:
    on = (on or "always").lower()
    if on == "always":
        return True
    failed = (getattr(summary, "failed", 0) or 0) + (getattr(summary, "errors", 0) or 0)
    if on == "failure":
        return failed > 0
    if on == "regression":
        return len(_find_regressions(summary, previous)) > 0
    return True


def _build_summary_text(summary: Any) -> str:
    total = getattr(summary, "total", 0)
    passed = getattr(summary, "passed", 0)
    failed = getattr(summary, "failed", 0)
    errors = getattr(summary, "errors", 0)
    rate = getattr(summary, "pass_rate", 0.0) or 0.0
    cost = getattr(summary, "total_cost", 0.0) or 0.0
    icon = "✅" if failed == 0 and errors == 0 else "❌"
    return (
        f"{icon} ATTEST run: {passed}/{total} passed ({rate:.0%}) · "
        f"{failed} failed · {errors} errors · ${cost:.4f}"
    )


def _payload(style: str, text: str) -> dict:
    style = (style or "generic").lower()
    if style == "slack":
        return {"text": text}
    if style == "teams":
        return {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": "ATTEST run",
            "text": text,
        }
    # generic
    return {"text": text}


def maybe_notify(notify_config: Any, summary: Any, previous: Any = None) -> bool:
    """Send a notification if configured and the trigger condition matches.

    Returns True if a notification was sent, False otherwise.
    """
    url = getattr(notify_config, "webhook_url", None)
    if not url:
        return False
    if not _should_send(getattr(notify_config, "on", "always"), summary, previous):
        return False

    text = _build_summary_text(summary)
    regressions = _find_regressions(summary, previous)
    if regressions:
        text += f"\n⚠️ Regressions: {', '.join(regressions[:10])}"

    payload = _payload(getattr(notify_config, "style", "generic"), text)

    import httpx

    try:
        httpx.post(url, json=payload, timeout=10)
        return True
    except Exception:
        return False
