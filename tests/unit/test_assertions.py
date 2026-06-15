"""Unit tests for ATTEST's deterministic assertions.

These prove the assertion library itself is correct — the single most
important thing to test in a testing framework. Each assertion is checked
for both the passing and failing case.

Run:
    pytest tests/unit/test_assertions.py -v
"""

from attest.core.models import AgentResponse, ToolCall, TokenUsage
from attest.core import assertions as A


def resp(content="", tool_calls=None, latency_ms=0.0, token_usage=None,
         routing_path=None, handled_by=None, metadata=None):
    return AgentResponse(
        content=content,
        tool_calls=tool_calls or [],
        latency_ms=latency_ms,
        token_usage=token_usage,
        routing_path=routing_path or [],
        handled_by=handled_by,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Content assertions
# ---------------------------------------------------------------------------
def test_response_contains():
    assert A.assert_response_contains("Paris")(resp("Flights to Paris")).passed
    assert not A.assert_response_contains("Rome")(resp("Flights to Paris")).passed


def test_response_contains_case_insensitive_by_default():
    assert A.assert_response_contains("paris")(resp("PARIS")).passed


def test_response_not_contains():
    assert A.assert_response_not_contains("error")(resp("all good")).passed
    assert not A.assert_response_not_contains("error")(resp("an error occurred")).passed


def test_response_not_empty():
    assert A.assert_response_not_empty()(resp("hi")).passed
    assert not A.assert_response_not_empty()(resp("   ")).passed


def test_response_contains_any():
    fn = A.assert_response_contains_any(["Tokyo", "Kyoto"])
    assert fn(resp("Visit Kyoto")).passed
    assert not fn(resp("Visit Rome")).passed


def test_response_matches_regex():
    assert A.assert_response_matches_regex(r"\d{3}-\d{4}")(resp("call 555-1234")).passed
    assert not A.assert_response_matches_regex(r"\d{3}-\d{4}")(resp("no number")).passed


# ---------------------------------------------------------------------------
# Tool-call assertions
# ---------------------------------------------------------------------------
def test_tool_called():
    r = resp(tool_calls=[ToolCall(name="search", arguments={"q": "x"})])
    assert A.assert_tool_called("search")(r).passed
    assert not A.assert_tool_called("missing")(r).passed


def test_tool_not_called():
    r = resp(tool_calls=[ToolCall(name="search")])
    assert A.assert_tool_not_called("delete")(r).passed
    assert not A.assert_tool_not_called("search")(r).passed


def test_no_tool_called():
    assert A.assert_no_tool_called()(resp()).passed
    assert not A.assert_no_tool_called()(resp(tool_calls=[ToolCall(name="x")])).passed


def test_tool_call_count():
    r = resp(tool_calls=[ToolCall(name="s"), ToolCall(name="s")])
    assert A.assert_tool_call_count("s", 2)(r).passed
    assert not A.assert_tool_call_count("s", 1)(r).passed


def test_tool_call_order():
    r = resp(tool_calls=[ToolCall(name="a"), ToolCall(name="b")])
    assert A.assert_tool_call_order(["a", "b"])(r).passed
    assert not A.assert_tool_call_order(["b", "a"])(r).passed


# ---------------------------------------------------------------------------
# Performance assertions
# ---------------------------------------------------------------------------
def test_latency_under():
    assert A.assert_latency_under(1000)(resp(latency_ms=500)).passed
    assert not A.assert_latency_under(1000)(resp(latency_ms=1500)).passed


def test_token_usage_under():
    r = resp(token_usage=TokenUsage(input_tokens=100, output_tokens=100, total_tokens=200))
    assert A.assert_token_usage_under(500)(r).passed
    assert not A.assert_token_usage_under(100)(r).passed


# ---------------------------------------------------------------------------
# JSON assertions
# ---------------------------------------------------------------------------
def test_response_is_json():
    assert A.assert_response_is_json()(resp('{"a": 1}')).passed
    assert not A.assert_response_is_json()(resp("not json")).passed


def test_json_field_exists():
    fn = A.assert_json_field_exists(["name", "email"])
    assert fn(resp('{"name": "A", "email": "a@b.com"}')).passed
    assert not fn(resp('{"name": "A"}')).passed


def test_json_field_value():
    fn = A.assert_json_field("status", "ok")
    assert fn(resp('{"status": "ok"}')).passed
    assert not fn(resp('{"status": "fail"}')).passed


# ---------------------------------------------------------------------------
# Routing assertions
# ---------------------------------------------------------------------------
def test_routed_to():
    # assert_routed_to checks `handled_by` (the sub-agent that handled it)
    r = resp(handled_by="flights_agent", routing_path=["orchestrator", "flights_agent"])
    assert A.assert_routed_to("flights_agent")(r).passed
    assert not A.assert_routed_to("hotels_agent")(r).passed


def test_not_routed_to():
    r = resp(handled_by="flights_agent", routing_path=["orchestrator", "flights_agent"])
    assert A.assert_not_routed_to("hotels_agent")(r).passed
    assert not A.assert_not_routed_to("flights_agent")(r).passed


def test_routing_path():
    r = resp(routing_path=["orchestrator", "flights_agent"])
    assert A.assert_routing_path(["orchestrator", "flights_agent"])(r).passed
    assert not A.assert_routing_path(["orchestrator", "hotels_agent"])(r).passed


# ---------------------------------------------------------------------------
# Safety / quality assertions (newer)
# ---------------------------------------------------------------------------
def test_no_pii_detects_email_and_ssn():
    r = resp("Contact a@b.com, SSN 123-45-6789")
    assert not A.assert_no_pii()(r).passed


def test_no_pii_passes_clean_text():
    assert A.assert_no_pii()(resp("Your refund is processed.")).passed


def test_no_pii_selective_types():
    # Only checking ssn — an email present should still pass.
    assert A.assert_no_pii(["ssn"])(resp("email a@b.com")).passed


def test_response_cost_under():
    r = resp(token_usage=TokenUsage(input_tokens=1000, output_tokens=1000, total_tokens=2000))
    # default pricing: 1000/1000*0.005 + 1000/1000*0.015 = 0.02
    assert A.assert_response_cost_under(0.05)(r).passed
    assert not A.assert_response_cost_under(0.01)(r).passed


def test_response_cost_skips_without_usage():
    # No token usage → cannot compute → should pass (skip), not error.
    assert A.assert_response_cost_under(0.01)(resp("hi")).passed


def test_language_is():
    english = resp("The weather is nice and the sun is out for a walk with a friend")
    assert A.assert_language_is("en")(english).passed


# ---------------------------------------------------------------------------
# Resolver: YAML dict -> assertion function
# ---------------------------------------------------------------------------
def test_resolver_maps_known_keys():
    for entry in (
        {"response_contains": "hi"},
        {"tool_called": "search"},
        {"latency_under": 5000},
        {"no_pii": True},
        {"response_cost_under": 0.05},
        {"language_is": "en"},
        {"semantic_match": {"expected": "x", "min_similarity": 0.8}},
    ):
        assert A.resolve_assertion(entry) is not None, entry


def test_resolver_unknown_key_returns_none():
    assert A.resolve_assertion({"totally_made_up": 1}) is None


def test_run_assertions_collects_results():
    r = resp("Paris", tool_calls=[ToolCall(name="search")])
    fns = [A.assert_response_contains("Paris"), A.assert_tool_called("search")]
    results = A.run_assertions(r, fns)
    assert len(results) == 2
    assert all(x.passed for x in results)


def test_run_assertions_captures_errors_gracefully():
    def boom(_response):
        raise ValueError("kaboom")

    results = A.run_assertions(resp("x"), [boom])
    assert len(results) == 1
    assert not results[0].passed
    assert "kaboom" in results[0].message
