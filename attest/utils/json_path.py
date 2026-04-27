"""Simple JSONPath-like extraction utility.

We need to extract values from agent HTTP responses using paths like:
  "$.response"              → data["response"]
  "$.choices[0].message"    → data["choices"][0]["message"]
  "$.data.answer"           → data["data"]["answer"]

This is a lightweight implementation — no external JSONPath library needed.
It handles the 95% case: dot notation with optional array indices.
"""

from __future__ import annotations

from typing import Any, Optional


def extract_by_path(data: Any, path: str) -> Optional[Any]:
    """Extract a value from nested data using a simple JSONPath-like expression.

    Supports:
        $.key              → data["key"]
        $.key.subkey       → data["key"]["subkey"]
        $.key[0]           → data["key"][0]
        $.key[0].subkey    → data["key"][0]["subkey"]

    Args:
        data: The data to extract from (usually a parsed JSON dict).
        path: JSONPath-like expression starting with "$."

    Returns:
        The extracted value, or None if the path doesn't match.

    Examples:
        >>> extract_by_path({"response": "hello"}, "$.response")
        'hello'
        >>> extract_by_path({"a": {"b": "deep"}}, "$.a.b")
        'deep'
        >>> extract_by_path({"items": [{"name": "first"}]}, "$.items[0].name")
        'first'
    """
    if not path or not path.startswith("$"):
        return None

    # Remove the leading "$." or "$"
    path = path[1:]
    if path.startswith("."):
        path = path[1:]

    if not path:
        return data

    current = data

    # Split into segments: "choices[0].message.content" → ["choices[0]", "message", "content"]
    segments = path.split(".")

    for segment in segments:
        if current is None:
            return None

        # Check if segment has array index: "choices[0]" → key="choices", index=0
        if "[" in segment and segment.endswith("]"):
            bracket_pos = segment.index("[")
            key = segment[:bracket_pos]
            index_str = segment[bracket_pos + 1 : -1]

            # Navigate to the key first
            if key:
                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    return None

            # Then apply the index
            try:
                index = int(index_str)
                if isinstance(current, (list, tuple)) and index < len(current):
                    current = current[index]
                else:
                    return None
            except (ValueError, IndexError):
                return None
        else:
            # Simple key lookup
            if isinstance(current, dict) and segment in current:
                current = current[segment]
            else:
                return None

    return current
