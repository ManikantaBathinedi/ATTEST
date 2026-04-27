"""Assertions library for ATTEST.

Assertions are instant, deterministic checks that don't need an LLM.
They run BEFORE evaluators (which need LLM calls) and catch the easy stuff:
wrong tool called, missing content, too slow, etc.

Each assertion is a simple function:
    Input:  AgentResponse (what the agent returned)
    Output: AssertionResult (pass/fail + message)

Usage in YAML:
    assertions:
      - tool_called: lookup_order
      - response_contains: "refund"
      - latency_under: 5000

Usage in Python:
    from attest.core.assertions import assert_tool_called, assert_response_contains

    assertions = [
        assert_tool_called("lookup_order"),
        assert_response_contains("refund"),
        assert_latency_under(5000),
    ]
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from attest.core.models import AgentResponse, AssertionResult


# ---------------------------------------------------------------------------
# Type alias: an assertion is a function that checks a response
# ---------------------------------------------------------------------------

# AssertionFn takes an AgentResponse and returns an AssertionResult
AssertionFn = Callable[[AgentResponse], AssertionResult]


# =========================================================================
# Tool Call Assertions
# =========================================================================


def assert_tool_called(name: str, **expected_args) -> AssertionFn:
    """Check that the agent called a specific tool.

    Args:
        name: Tool name to look for (e.g. "lookup_order").
        **expected_args: Optional expected arguments (partial match).

    Examples:
        assert_tool_called("lookup_order")
        assert_tool_called("lookup_order", order_id="12345")
    """

    def check(response: AgentResponse) -> AssertionResult:
        # Find the tool call by name
        matching_calls = [tc for tc in response.tool_calls if tc.name == name]

        if not matching_calls:
            called_names = [tc.name for tc in response.tool_calls]
            return AssertionResult(
                name=f"tool_called:{name}",
                passed=False,
                message=f"Tool '{name}' was not called. Called tools: {called_names}",
                expected=name,
                actual=called_names,
            )

        # If specific args are expected, check them
        if expected_args:
            call = matching_calls[0]
            for key, expected_val in expected_args.items():
                actual_val = call.arguments.get(key)
                if str(actual_val) != str(expected_val):
                    return AssertionResult(
                        name=f"tool_called:{name}",
                        passed=False,
                        message=(
                            f"Tool '{name}' called but arg '{key}' = {actual_val!r}, "
                            f"expected {expected_val!r}"
                        ),
                        expected=expected_args,
                        actual=call.arguments,
                    )

        return AssertionResult(name=f"tool_called:{name}", passed=True)

    return check


def assert_tool_not_called(name: str) -> AssertionFn:
    """Check that a specific tool was NOT called."""

    def check(response: AgentResponse) -> AssertionResult:
        called = any(tc.name == name for tc in response.tool_calls)
        if called:
            return AssertionResult(
                name=f"tool_not_called:{name}",
                passed=False,
                message=f"Tool '{name}' was called but should not have been.",
            )
        return AssertionResult(name=f"tool_not_called:{name}", passed=True)

    return check


def assert_no_tool_called() -> AssertionFn:
    """Check that NO tools were called at all."""

    def check(response: AgentResponse) -> AssertionResult:
        if response.tool_calls:
            names = [tc.name for tc in response.tool_calls]
            return AssertionResult(
                name="no_tool_called",
                passed=False,
                message=f"Expected no tool calls, but got: {names}",
                actual=names,
            )
        return AssertionResult(name="no_tool_called", passed=True)

    return check


def assert_tool_call_count(name: str, count: int) -> AssertionFn:
    """Check that a tool was called exactly N times."""

    def check(response: AgentResponse) -> AssertionResult:
        actual_count = sum(1 for tc in response.tool_calls if tc.name == name)
        if actual_count != count:
            return AssertionResult(
                name=f"tool_call_count:{name}",
                passed=False,
                message=f"Tool '{name}' called {actual_count} times, expected {count}.",
                expected=count,
                actual=actual_count,
            )
        return AssertionResult(name=f"tool_call_count:{name}", passed=True)

    return check


def assert_tool_called_with_args(name: str, expected_args: Dict[str, Any]) -> AssertionFn:
    """Check that a tool was called with specific argument values.

    Args:
        name: Tool name.
        expected_args: Dict of argument key-value pairs to validate.

    Examples:
        assert_tool_called_with_args("search_flights", {"destination": "Tokyo", "class": "economy"})
    """

    def check(response: AgentResponse) -> AssertionResult:
        matching = [tc for tc in response.tool_calls if tc.name == name]
        if not matching:
            return AssertionResult(
                name=f"tool_args:{name}",
                passed=False,
                message=f"Tool '{name}' was not called.",
                expected=expected_args,
                actual=[tc.name for tc in response.tool_calls],
            )

        call = matching[0]
        mismatches = []
        for key, expected_val in expected_args.items():
            actual_val = call.arguments.get(key)
            if actual_val is None:
                mismatches.append(f"'{key}' missing (expected {expected_val!r})")
            elif str(actual_val).lower() != str(expected_val).lower():
                mismatches.append(f"'{key}'={actual_val!r} (expected {expected_val!r})")

        if mismatches:
            return AssertionResult(
                name=f"tool_args:{name}",
                passed=False,
                message=f"Tool '{name}' args mismatch: {'; '.join(mismatches)}",
                expected=expected_args,
                actual=call.arguments,
            )

        return AssertionResult(name=f"tool_args:{name}", passed=True)

    return check


def assert_tool_call_order(expected_order: List[str]) -> AssertionFn:
    """Check that tools were called in a specific order.

    Args:
        expected_order: List of tool names in expected sequence.

    Examples:
        assert_tool_call_order(["search_flights", "book_flight", "send_confirmation"])
    """

    def check(response: AgentResponse) -> AssertionResult:
        actual_order = [tc.name for tc in response.tool_calls]

        # Check if expected_order is a subsequence of actual_order
        expected_idx = 0
        for actual_name in actual_order:
            if expected_idx < len(expected_order) and actual_name == expected_order[expected_idx]:
                expected_idx += 1

        if expected_idx == len(expected_order):
            return AssertionResult(name="tool_call_order", passed=True)

        return AssertionResult(
            name="tool_call_order",
            passed=False,
            message=f"Tool call order mismatch. Expected: {expected_order}, Actual: {actual_order}",
            expected=expected_order,
            actual=actual_order,
        )

    return check


def assert_tool_args_contain(name: str, key: str, substring: str) -> AssertionFn:
    """Check that a tool's argument contains a substring.

    Args:
        name: Tool name.
        key: Argument key to check.
        substring: Text that should appear in the argument value.

    Examples:
        assert_tool_args_contain("search_flights", "destination", "Tokyo")
    """

    def check(response: AgentResponse) -> AssertionResult:
        matching = [tc for tc in response.tool_calls if tc.name == name]
        if not matching:
            return AssertionResult(
                name=f"tool_arg_contains:{name}.{key}",
                passed=False,
                message=f"Tool '{name}' was not called.",
            )

        call = matching[0]
        actual_val = str(call.arguments.get(key, ""))
        if substring.lower() in actual_val.lower():
            return AssertionResult(name=f"tool_arg_contains:{name}.{key}", passed=True)

        return AssertionResult(
            name=f"tool_arg_contains:{name}.{key}",
            passed=False,
            message=f"Tool '{name}' arg '{key}'='{actual_val}' does not contain '{substring}'.",
            expected=substring,
            actual=actual_val,
        )

    return check


def assert_tool_count(count: int) -> AssertionFn:
    """Check total number of tool calls (any tool)."""

    def check(response: AgentResponse) -> AssertionResult:
        actual = len(response.tool_calls)
        if actual == count:
            return AssertionResult(name=f"tool_count:{count}", passed=True)
        return AssertionResult(
            name=f"tool_count:{count}",
            passed=False,
            message=f"Expected {count} total tool call(s), got {actual}.",
            expected=count,
            actual=actual,
        )

    return check


# =========================================================================
# Response Content Assertions
# =========================================================================


def assert_response_contains(text: str, case_sensitive: bool = False) -> AssertionFn:
    """Check that the response contains specific text.

    Args:
        text: Text to look for.
        case_sensitive: Whether the check is case-sensitive. Default: False.
    """

    def check(response: AgentResponse) -> AssertionResult:
        content = response.content
        search_text = text

        if not case_sensitive:
            content = content.lower()
            search_text = text.lower()

        if search_text in content:
            return AssertionResult(name=f"response_contains:{text}", passed=True)

        return AssertionResult(
            name=f"response_contains:{text}",
            passed=False,
            message=f"Response does not contain '{text}'.",
            expected=text,
            actual=response.content[:200],
        )

    return check


def assert_response_not_contains(text: str, case_sensitive: bool = False) -> AssertionFn:
    """Check that the response does NOT contain specific text."""

    def check(response: AgentResponse) -> AssertionResult:
        content = response.content
        search_text = text

        if not case_sensitive:
            content = content.lower()
            search_text = text.lower()

        if search_text not in content:
            return AssertionResult(name=f"response_not_contains:{text}", passed=True)

        return AssertionResult(
            name=f"response_not_contains:{text}",
            passed=False,
            message=f"Response should not contain '{text}' but it does.",
        )

    return check


def assert_response_not_empty() -> AssertionFn:
    """Check that the response is not empty."""

    def check(response: AgentResponse) -> AssertionResult:
        if response.content and response.content.strip():
            return AssertionResult(name="response_not_empty", passed=True)
        return AssertionResult(
            name="response_not_empty",
            passed=False,
            message="Response is empty.",
        )

    return check


def assert_response_matches_regex(pattern: str) -> AssertionFn:
    """Check that the response matches a regex pattern."""

    def check(response: AgentResponse) -> AssertionResult:
        if re.search(pattern, response.content):
            return AssertionResult(name=f"response_matches:{pattern}", passed=True)
        return AssertionResult(
            name=f"response_matches:{pattern}",
            passed=False,
            message=f"Response does not match pattern '{pattern}'.",
            expected=pattern,
            actual=response.content[:200],
        )

    return check


def assert_response_contains_any(texts: List[str], case_sensitive: bool = False) -> AssertionFn:
    """Check that the response contains at least one of the given texts."""

    def check(response: AgentResponse) -> AssertionResult:
        content = response.content if case_sensitive else response.content.lower()

        for text in texts:
            search = text if case_sensitive else text.lower()
            if search in content:
                return AssertionResult(
                    name=f"response_contains_any",
                    passed=True,
                    message=f"Found '{text}' in response.",
                )

        return AssertionResult(
            name="response_contains_any",
            passed=False,
            message=f"Response does not contain any of: {texts}",
            expected=texts,
            actual=response.content[:200],
        )

    return check


# =========================================================================
# Performance Assertions
# =========================================================================


def assert_latency_under(ms: int) -> AssertionFn:
    """Check that the response latency is under the given milliseconds."""

    def check(response: AgentResponse) -> AssertionResult:
        if response.latency_ms <= ms:
            return AssertionResult(name=f"latency_under:{ms}ms", passed=True)
        return AssertionResult(
            name=f"latency_under:{ms}ms",
            passed=False,
            message=f"Latency {response.latency_ms:.0f}ms exceeds limit of {ms}ms.",
            expected=ms,
            actual=response.latency_ms,
        )

    return check


def assert_token_usage_under(max_tokens: int) -> AssertionFn:
    """Check that total token usage is under the limit."""

    def check(response: AgentResponse) -> AssertionResult:
        if response.token_usage is None:
            return AssertionResult(
                name=f"token_usage_under:{max_tokens}",
                passed=True,
                message="No token usage data (skipping check).",
            )
        actual = response.token_usage.total_tokens
        if actual <= max_tokens:
            return AssertionResult(name=f"token_usage_under:{max_tokens}", passed=True)
        return AssertionResult(
            name=f"token_usage_under:{max_tokens}",
            passed=False,
            message=f"Token usage {actual} exceeds limit of {max_tokens}.",
            expected=max_tokens,
            actual=actual,
        )

    return check


# =========================================================================
# Structured Output Assertions (JSON, Classification, Data Extraction)
# =========================================================================


def assert_response_is_json() -> AssertionFn:
    """Check that the response is valid JSON."""

    def check(response: AgentResponse) -> AssertionResult:
        import json as _json
        try:
            _json.loads(response.content)
            return AssertionResult(name="response_is_json", passed=True)
        except (ValueError, TypeError):
            return AssertionResult(
                name="response_is_json",
                passed=False,
                message=f"Response is not valid JSON. Got: {response.content[:100]}...",
            )

    return check


def assert_json_schema(schema: Dict[str, Any]) -> AssertionFn:
    """Check that JSON response matches a JSON schema.

    Args:
        schema: JSON schema dict (uses jsonschema for validation).

    Examples:
        assert_json_schema({"type": "object", "required": ["name", "age"]})
    """

    def check(response: AgentResponse) -> AssertionResult:
        import json as _json
        try:
            data = _json.loads(response.content)
        except (ValueError, TypeError):
            return AssertionResult(
                name="json_schema",
                passed=False,
                message="Response is not valid JSON.",
            )

        try:
            import jsonschema
            jsonschema.validate(data, schema)
            return AssertionResult(name="json_schema", passed=True)
        except ImportError:
            # Fallback: just check required fields if jsonschema not installed
            required = schema.get("required", [])
            if isinstance(data, dict):
                missing = [f for f in required if f not in data]
                if missing:
                    return AssertionResult(
                        name="json_schema",
                        passed=False,
                        message=f"Missing required fields: {missing}",
                        expected=required,
                        actual=list(data.keys()),
                    )
            return AssertionResult(name="json_schema", passed=True)
        except Exception as e:
            return AssertionResult(
                name="json_schema",
                passed=False,
                message=f"Schema validation failed: {str(e)[:200]}",
            )

    return check


def assert_json_field(path: str, expected_value: Any) -> AssertionFn:
    """Check that a specific JSON field has a specific value.

    Args:
        path: Dot-separated path to field (e.g. "result.category" or "status").
        expected_value: Expected value (exact match, case-insensitive for strings).

    Examples:
        assert_json_field("status", "approved")
        assert_json_field("result.confidence", 0.95)
        assert_json_field("data.items.0.name", "flight")
    """

    def check(response: AgentResponse) -> AssertionResult:
        import json as _json
        try:
            data = _json.loads(response.content)
        except (ValueError, TypeError):
            return AssertionResult(
                name=f"json_field:{path}",
                passed=False,
                message="Response is not valid JSON.",
            )

        # Navigate dot path
        current = data
        for key in path.split("."):
            if isinstance(current, dict):
                current = current.get(key)
            elif isinstance(current, list):
                try:
                    current = current[int(key)]
                except (IndexError, ValueError):
                    current = None
            else:
                current = None

            if current is None:
                return AssertionResult(
                    name=f"json_field:{path}",
                    passed=False,
                    message=f"Field '{path}' not found in response.",
                    expected=expected_value,
                )

        # Compare values
        if isinstance(expected_value, str) and isinstance(current, str):
            match = current.lower() == expected_value.lower()
        else:
            match = current == expected_value

        if match:
            return AssertionResult(name=f"json_field:{path}", passed=True)

        return AssertionResult(
            name=f"json_field:{path}",
            passed=False,
            message=f"Field '{path}' = {current!r}, expected {expected_value!r}.",
            expected=expected_value,
            actual=current,
        )

    return check


def assert_json_field_exists(fields: List[str]) -> AssertionFn:
    """Check that specific fields exist in JSON response.

    Args:
        fields: List of dot-separated field paths.
    """

    def check(response: AgentResponse) -> AssertionResult:
        import json as _json
        try:
            data = _json.loads(response.content)
        except (ValueError, TypeError):
            return AssertionResult(
                name="json_field_exists",
                passed=False,
                message="Response is not valid JSON.",
            )

        missing = []
        for field in fields:
            current = data
            for key in field.split("."):
                if isinstance(current, dict):
                    current = current.get(key)
                elif isinstance(current, list):
                    try:
                        current = current[int(key)]
                    except (IndexError, ValueError):
                        current = None
                else:
                    current = None
                if current is None:
                    missing.append(field)
                    break

        if not missing:
            return AssertionResult(name="json_field_exists", passed=True)

        return AssertionResult(
            name="json_field_exists",
            passed=False,
            message=f"Missing fields: {missing}",
            expected=fields,
            actual=missing,
        )

    return check


def assert_json_field_regex(path: str, pattern: str) -> AssertionFn:
    """Check that a JSON field value matches a regex pattern.

    Args:
        path: Dot-separated path to field.
        pattern: Regex pattern to match against.

    Examples:
        assert_json_field_regex("email", r"^[\\w.-]+@[\\w.-]+\\.\\w+$")
        assert_json_field_regex("date", r"^\\d{4}-\\d{2}-\\d{2}$")
        assert_json_field_regex("phone", r"^\\+?\\d[\\d\\s-]{7,}$")
    """

    def check(response: AgentResponse) -> AssertionResult:
        import json as _json
        try:
            data = _json.loads(response.content)
        except (ValueError, TypeError):
            return AssertionResult(
                name=f"json_field_regex:{path}",
                passed=False,
                message="Response is not valid JSON.",
            )

        # Navigate dot path
        current = data
        for key in path.split("."):
            if isinstance(current, dict):
                current = current.get(key)
            elif isinstance(current, list):
                try:
                    current = current[int(key)]
                except (IndexError, ValueError):
                    current = None
            else:
                current = None
            if current is None:
                return AssertionResult(
                    name=f"json_field_regex:{path}",
                    passed=False,
                    message=f"Field '{path}' not found.",
                )

        if re.search(pattern, str(current)):
            return AssertionResult(name=f"json_field_regex:{path}", passed=True)

        return AssertionResult(
            name=f"json_field_regex:{path}",
            passed=False,
            message=f"Field '{path}' = '{current}' does not match pattern '{pattern}'.",
            expected=pattern,
            actual=str(current),
        )

    return check


def assert_classification(expected_labels: List[str], field: str = "") -> AssertionFn:
    """Check that the response (or a JSON field) is one of the expected labels.

    Args:
        expected_labels: List of valid labels/categories.
        field: Optional JSON field path. If empty, checks the raw response text.

    Examples:
        assert_classification(["positive", "negative", "neutral"])
        assert_classification(["bug", "feature", "question"], field="category")
    """

    def check(response: AgentResponse) -> AssertionResult:
        if field:
            import json as _json
            try:
                data = _json.loads(response.content)
                current = data
                for key in field.split("."):
                    if isinstance(current, dict):
                        current = current.get(key)
                    else:
                        current = None
                value = str(current).strip().lower() if current else ""
            except (ValueError, TypeError):
                value = response.content.strip().lower()
        else:
            value = response.content.strip().lower()

        normalized_labels = [l.lower() for l in expected_labels]
        if value in normalized_labels:
            return AssertionResult(name="classification", passed=True)

        return AssertionResult(
            name="classification",
            passed=False,
            message=f"Output '{value}' is not in expected labels: {expected_labels}.",
            expected=expected_labels,
            actual=value,
        )

    return check


def assert_exact_match(expected: str, case_sensitive: bool = False) -> AssertionFn:
    """Check that the response exactly matches expected text.

    Args:
        expected: The exact expected output.
        case_sensitive: Whether comparison is case-sensitive.
    """

    def check(response: AgentResponse) -> AssertionResult:
        actual = response.content.strip()
        exp = expected.strip()

        if not case_sensitive:
            match = actual.lower() == exp.lower()
        else:
            match = actual == exp

        if match:
            return AssertionResult(name="exact_match", passed=True)

        return AssertionResult(
            name="exact_match",
            passed=False,
            message=f"Response does not exactly match expected output.",
            expected=expected[:200],
            actual=actual[:200],
        )

    return check


def assert_json_array_length(min_len: int = 0, max_len: Optional[int] = None, field: str = "") -> AssertionFn:
    """Check that a JSON array has expected length.

    Args:
        min_len: Minimum array length.
        max_len: Maximum array length (None = no limit).
        field: Dot-path to array field. Empty = root response.
    """

    def check(response: AgentResponse) -> AssertionResult:
        import json as _json
        try:
            data = _json.loads(response.content)
        except (ValueError, TypeError):
            return AssertionResult(name="json_array_length", passed=False, message="Not valid JSON.")

        # Navigate to field
        current = data
        if field:
            for key in field.split("."):
                if isinstance(current, dict):
                    current = current.get(key)
                else:
                    current = None
                if current is None:
                    return AssertionResult(name="json_array_length", passed=False, message=f"Field '{field}' not found.")

        if not isinstance(current, list):
            return AssertionResult(name="json_array_length", passed=False, message=f"Expected array, got {type(current).__name__}.")

        actual_len = len(current)
        if actual_len < min_len:
            return AssertionResult(name="json_array_length", passed=False, message=f"Array length {actual_len} < minimum {min_len}.", expected=min_len, actual=actual_len)
        if max_len is not None and actual_len > max_len:
            return AssertionResult(name="json_array_length", passed=False, message=f"Array length {actual_len} > maximum {max_len}.", expected=max_len, actual=actual_len)

        return AssertionResult(name="json_array_length", passed=True)

    return check


# =========================================================================
# YAML Assertion Resolver
# =========================================================================
# This translates YAML assertion syntax into assertion functions.
# In YAML, users write:
#   assertions:
#     - tool_called: lookup_order
#     - response_contains: "refund"
#     - latency_under: 5000
#     - response_not_empty: true


def resolve_assertion(assertion_dict: Dict[str, Any]) -> Optional[AssertionFn]:
    """Convert a YAML assertion dict into an assertion function.

    Args:
        assertion_dict: A single entry like {"tool_called": "lookup_order"}

    Returns:
        An assertion function, or None if the assertion type is unknown.

    Examples:
        resolve_assertion({"tool_called": "search"})
        resolve_assertion({"response_contains": "hello"})
        resolve_assertion({"latency_under": 5000})
    """
    # Map of YAML assertion names to factory functions
    registry = {
        # Tool call assertions
        "tool_called": lambda v: assert_tool_called(v) if isinstance(v, str) else assert_tool_called(**v),
        "tool_not_called": lambda v: assert_tool_not_called(v),
        "no_tool_called": lambda v: assert_no_tool_called(),
        "tool_call_count": lambda v: assert_tool_call_count(v["name"], v["count"]),
        "tool_called_with_args": lambda v: assert_tool_called_with_args(v["name"], v.get("args", {})),
        "tool_call_order": lambda v: assert_tool_call_order(v),
        "tool_args_contain": lambda v: assert_tool_args_contain(v["name"], v["key"], v["contains"]),
        "tool_count": lambda v: assert_tool_count(int(v)),
        # Response content assertions
        "response_contains": lambda v: assert_response_contains(v),
        "response_not_contains": lambda v: assert_response_not_contains(v),
        "response_not_empty": lambda v: assert_response_not_empty(),
        "response_matches_regex": lambda v: assert_response_matches_regex(v),
        "response_contains_any": lambda v: assert_response_contains_any(v),
        "exact_match": lambda v: assert_exact_match(v) if isinstance(v, str) else assert_exact_match(v.get("value", ""), v.get("case_sensitive", False)),
        # Performance assertions
        "latency_under": lambda v: assert_latency_under(int(v)),
        "token_usage_under": lambda v: assert_token_usage_under(int(v)),
        # Structured output / JSON assertions
        "response_is_json": lambda v: assert_response_is_json(),
        "json_schema": lambda v: assert_json_schema(v),
        "json_field": lambda v: assert_json_field(v["path"], v["value"]),
        "json_field_exists": lambda v: assert_json_field_exists(v),
        "json_field_regex": lambda v: assert_json_field_regex(v["path"], v["pattern"]),
        "json_array_length": lambda v: assert_json_array_length(v.get("min", 0), v.get("max"), v.get("field", "")),
        # Classification assertion
        "classification": lambda v: assert_classification(v) if isinstance(v, list) else assert_classification(v.get("labels", []), v.get("field", "")),
    }

    for key, value in assertion_dict.items():
        factory = registry.get(key)
        if factory:
            return factory(value)

    return None


def resolve_assertions(assertion_list: List[Dict[str, Any]]) -> List[AssertionFn]:
    """Convert a list of YAML assertion dicts into assertion functions.

    Skips any unrecognized assertions (won't crash on unknown types).

    Args:
        assertion_list: List from YAML, e.g. [{"tool_called": "search"}, {"latency_under": 5000}]

    Returns:
        List of assertion functions ready to run.
    """
    functions = []
    for assertion_dict in assertion_list:
        fn = resolve_assertion(assertion_dict)
        if fn:
            functions.append(fn)
    return functions


def run_assertions(
    response: AgentResponse,
    assertion_fns: List[AssertionFn],
) -> List[AssertionResult]:
    """Run all assertions against a response and return results.

    Args:
        response: The agent's response to check.
        assertion_fns: List of assertion functions to run.

    Returns:
        List of AssertionResult (one per assertion).
    """
    results = []
    for fn in assertion_fns:
        try:
            result = fn(response)
            results.append(result)
        except Exception as e:
            results.append(
                AssertionResult(
                    name="assertion_error",
                    passed=False,
                    message=f"Assertion raised an error: {e}",
                )
            )
    return results
