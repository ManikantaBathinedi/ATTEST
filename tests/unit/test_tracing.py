"""Unit tests for ATTEST OpenTelemetry tracing helpers.

These verify the *safety* guarantees: tracing must never raise, and must be a
clean no-op when disabled — so it can't break a test run.

Run:
    pytest tests/unit/test_tracing.py -v
"""

from attest.utils import tracing


def test_span_is_noop_when_disabled():
    # Fresh state: tracing not set up → span yields None, never raises.
    tracing._TRACER = None
    tracing._ENABLED = False
    with tracing.span("attest.test", {"k": "v"}) as s:
        assert s is None  # no active span
        tracing.set_span_attr(s, "x", 1)  # must not raise on None


def test_set_span_attr_handles_none():
    # Should silently no-op, never raise.
    tracing.set_span_attr(None, "key", "value")


def test_setup_returns_bool():
    # setup_tracing must return a boolean and never raise, even if OTel
    # isn't installed in this environment.
    result = tracing.setup_tracing(console=False)
    assert isinstance(result, bool)


def test_span_runs_body_regardless():
    ran = {"v": False}
    with tracing.span("attest.body"):
        ran["v"] = True
    assert ran["v"] is True
