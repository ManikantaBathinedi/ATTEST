"""Agent API auto-detection.

When a user gives us just a URL and nothing else, this module:
1. Probes the URL with common request body formats
2. Detects which format the agent accepts
3. Detects where the response text lives in the JSON
4. Returns a ready-to-use AgentConfig

This means users can get started with ZERO config knowledge — just a URL.

Usage:
    from attest.adapters.auto_detect import detect_agent_api

    config = await detect_agent_api("http://localhost:8000/chat")
    # → AgentConfig with all fields filled in automatically
"""

from __future__ import annotations

from typing import Optional

import httpx

from attest.core.config_models import AgentConfig, RequestConfig, ResponseConfig
from attest.utils.json_path import extract_by_path


# Common request body formats to try (ordered by popularity)
_REQUEST_FORMATS = [
    # Format name, body template, path to use as {{input}} key
    ("message", {"message": "{{input}}"}),
    ("query", {"query": "{{input}}"}),
    ("input", {"input": "{{input}}"}),
    ("openai", {"messages": [{"role": "user", "content": "{{input}}"}]}),
    ("prompt", {"prompt": "{{input}}"}),
    ("text", {"text": "{{input}}"}),
    ("content", {"content": "{{input}}"}),
    ("question", {"question": "{{input}}"}),
]

# Common response text locations to check (ordered by popularity)
_RESPONSE_PATHS = [
    "$.response",
    "$.answer",
    "$.content",
    "$.message",
    "$.text",
    "$.output",
    "$.result",
    "$.reply",
    "$.data.response",
    "$.data.answer",
    "$.data.content",
    "$.choices[0].message.content",  # OpenAI format
]

# Common tool call locations
_TOOL_CALL_PATHS = [
    "$.tool_calls",
    "$.tools",
    "$.function_calls",
    "$.actions",
    "$.choices[0].message.tool_calls",
]

# Test message used for probing
_PROBE_MESSAGE = "Hello, can you help me?"


async def detect_agent_api(
    url: str,
    test_message: str = _PROBE_MESSAGE,
    timeout: int = 15,
) -> Optional[AgentConfig]:
    """Auto-detect an agent's API format by probing it.

    Tries multiple common request formats against the URL.
    When one works, analyzes the response to find the text field.

    Args:
        url: The agent's URL (e.g. "http://localhost:8000/chat")
        test_message: Message to send for detection.
        timeout: How long to wait per attempt.

    Returns:
        AgentConfig with detected settings, or None if detection failed.

    Example:
        config = await detect_agent_api("http://localhost:8000/chat")
        if config:
            print(f"Detected! Body: {config.request.body_template}")
            print(f"Response at: {config.response.content_path}")
    """
    # Split URL into endpoint + path
    endpoint, path = _split_url(url)

    async with httpx.AsyncClient(timeout=timeout) as client:
        # Try each request format
        for format_name, body_template in _REQUEST_FORMATS:
            # Build the actual request body (replace {{input}} with test message)
            body = _fill_template(body_template, test_message)

            try:
                response = await client.post(
                    url,
                    json=body,
                    headers={"Content-Type": "application/json"},
                )

                # Skip if the server returns an error
                if response.status_code >= 400:
                    continue

                # Try to parse as JSON
                try:
                    data = response.json()
                except Exception:
                    continue

                # Find where the response text lives
                content_path = _detect_response_path(data)
                if content_path is None:
                    continue

                # Success! We found a working format
                tool_calls_path = _detect_tool_calls_path(data)

                return AgentConfig(
                    type="http",
                    endpoint=endpoint,
                    request=RequestConfig(
                        method="POST",
                        path=path,
                        body_template=body_template,
                    ),
                    response=ResponseConfig(
                        content_path=content_path,
                        tool_calls_path=tool_calls_path,
                    ),
                )

            except (httpx.ConnectError, httpx.TimeoutException):
                # Agent is not running or URL is wrong — fail all attempts
                return None
            except Exception:
                # This format didn't work, try the next one
                continue

    return None


def _split_url(url: str) -> tuple:
    """Split 'http://localhost:8000/chat' into ('http://localhost:8000', '/chat')."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    endpoint = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path or "/"
    return endpoint, path


def _fill_template(template: dict, message: str) -> dict:
    """Replace {{input}} with the actual message in a body template."""
    result = {}
    for key, value in template.items():
        if isinstance(value, str):
            result[key] = value.replace("{{input}}", message)
        elif isinstance(value, list):
            # Handle OpenAI format: [{"role": "user", "content": "{{input}}"}]
            filled_list = []
            for item in value:
                if isinstance(item, dict):
                    filled_item = {}
                    for k, v in item.items():
                        if isinstance(v, str):
                            filled_item[k] = v.replace("{{input}}", message)
                        else:
                            filled_item[k] = v
                    filled_list.append(filled_item)
                else:
                    filled_list.append(item)
            result[key] = filled_list
        else:
            result[key] = value
    return result


def _detect_response_path(data: dict) -> Optional[str]:
    """Try common paths to find where the response text is in the JSON."""
    for path in _RESPONSE_PATHS:
        value = extract_by_path(data, path)
        if value is not None and isinstance(value, str) and len(value) > 0:
            return path
    return None


def _detect_tool_calls_path(data: dict) -> Optional[str]:
    """Try common paths to find tool calls in the response."""
    for path in _TOOL_CALL_PATHS:
        value = extract_by_path(data, path)
        if value is not None and isinstance(value, list):
            return path
    return None
