"""HTTP/REST agent adapter.

This is the most commonly used adapter. It connects to any agent that has
an HTTP API — which is ~90% of all deployed agents.

How it works:
    1. Takes the user's message
    2. Fills it into the request body template from config
    3. Sends an HTTP POST (or configured method) to the agent
    4. Extracts the response text using the JSONPath from config
    5. Extracts tool calls and token usage if configured
    6. Returns a standard AgentResponse

The adapter is fully configurable via attest.yaml:

    agents:
      my_bot:
        type: http
        endpoint: "http://localhost:8000"
        request:
          method: POST
          path: "/chat"
          body_template:
            message: "{{input}}"
        response:
          content_path: "$.response"
        auth:
          type: api_key
          key: "${API_KEY}"
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx

from attest.adapters.base import BaseAgentAdapter
from attest.core.config_models import AgentConfig
from attest.core.exceptions import AdapterError
from attest.core.models import AgentResponse, Message, TokenUsage, ToolCall
from attest.utils.json_path import extract_by_path


class HttpAgentAdapter(BaseAgentAdapter):
    """Adapter that connects to agents via HTTP/REST APIs.

    This adapter handles:
    - Configurable request body templates ({{input}}, {{conversation_history}})
    - Configurable response extraction via JSONPath
    - API key, Bearer token, and no-auth authentication
    - Timeout handling
    - Session management (keeps session_id for multi-turn)

    Usage:
        adapter = HttpAgentAdapter(agent_config)
        response = await adapter.send_message("Hello, how can you help?")
    """

    def __init__(self, config: AgentConfig):
        self._config = config
        self._session_id: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def setup(self) -> None:
        """Create the HTTP client. Called once before tests start."""
        self._client = httpx.AsyncClient(timeout=self._config.timeout)

    async def teardown(self) -> None:
        """Close the HTTP client. Called after tests finish."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def reset_conversation(self) -> None:
        """Reset session ID between test cases."""
        self._session_id = None

    # ------------------------------------------------------------------
    # Core: send_message
    # ------------------------------------------------------------------

    async def send_message(
        self,
        message: str,
        conversation_history: Optional[List[Message]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResponse:
        """Send a message to the agent and get a response.

        Steps:
            1. Build the request body from the template
            2. Add auth headers
            3. Send the HTTP request
            4. Extract response content, tool calls, token usage
            5. Return standardized AgentResponse
        """
        if self._client is None:
            # Auto-setup if user forgot to call setup()
            await self.setup()

        # Step 1: Build request body
        body = self._build_request_body(message, conversation_history, metadata)

        # Step 2: Build headers (base + auth)
        headers = self._build_headers()

        # Step 3: Build URL
        url = self._build_url()

        # Step 4: Send request and measure latency
        start_time = time.perf_counter()
        try:
            response = await self._client.request(
                method=self._config.request.method,
                url=url,
                json=body,
                headers=headers,
            )
            response.raise_for_status()
        except httpx.TimeoutException as e:
            raise AdapterError(
                f"Agent at {url} timed out after {self._config.timeout}s"
            ) from e
        except httpx.HTTPStatusError as e:
            raise AdapterError(
                f"Agent at {url} returned HTTP {e.response.status_code}: "
                f"{e.response.text[:200]}"
            ) from e
        except httpx.ConnectError as e:
            raise AdapterError(
                f"Cannot connect to agent at {url}. Is the agent running?"
            ) from e
        except Exception as e:
            raise AdapterError(f"HTTP request to {url} failed: {e}") from e

        latency_ms = (time.perf_counter() - start_time) * 1000

        # Step 5: Parse response
        try:
            response_data = response.json()
        except Exception:
            # If response isn't JSON, treat the raw text as the content
            return AgentResponse(content=response.text, latency_ms=latency_ms)

        # Step 6: Extract fields using JSONPath
        content = self._extract_content(response_data)
        tool_calls = self._extract_tool_calls(response_data)
        token_usage = self._extract_token_usage(response_data)

        return AgentResponse(
            content=content,
            tool_calls=tool_calls,
            latency_ms=latency_ms,
            token_usage=token_usage,
            raw_response=response_data,
        )

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Check if the agent endpoint is reachable.

        Sends a simple GET request to the base endpoint.
        Returns True if we get any response (even an error page).
        """
        if self._client is None:
            await self.setup()

        try:
            url = self._config.endpoint or ""
            response = await self._client.get(url, timeout=5)
            # Any response means the server is up (even 404, 405, etc.)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Private helpers (each does ONE simple thing)
    # ------------------------------------------------------------------

    def _build_url(self) -> str:
        """Combine endpoint + path into full URL."""
        endpoint = (self._config.endpoint or "").rstrip("/")
        path = self._config.request.path
        return f"{endpoint}{path}"

    def _build_headers(self) -> Dict[str, str]:
        """Build request headers including auth."""
        headers = dict(self._config.request.headers)

        # Add any extra headers from config
        headers.update(self._config.headers)

        # Add authentication header
        auth = self._config.auth
        if auth.type == "api_key" and auth.key:
            prefix = f"{auth.prefix} " if auth.prefix else ""
            headers[auth.header] = f"{prefix}{auth.key}"
        elif auth.type == "bearer" and auth.token:
            headers["Authorization"] = f"Bearer {auth.token}"

        return headers

    def _build_request_body(
        self,
        message: str,
        conversation_history: Optional[List[Message]],
        metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Fill the body template with actual values.

        Replaces template variables:
            {{input}}                → the user's message
            {{conversation_history}} → list of prior messages
            {{session_id}}           → session ID for multi-turn
        """
        body = {}
        for key, value in self._config.request.body_template.items():
            if isinstance(value, str):
                # Replace template variables
                filled = value
                filled = filled.replace("{{input}}", message)

                if "{{session_id}}" in filled:
                    filled = filled.replace("{{session_id}}", self._session_id or "")

                if "{{conversation_history}}" in filled:
                    # This case is tricky — the value wants the full history as a string
                    # But usually conversation_history goes as its own field (see below)
                    history_str = str(conversation_history or [])
                    filled = filled.replace("{{conversation_history}}", history_str)

                body[key] = filled
            else:
                body[key] = value

        # If conversation history is provided and the template has a placeholder
        # for it as a list (not a string replacement), add it
        if conversation_history:
            for key, value in self._config.request.body_template.items():
                if value == "{{conversation_history}}":
                    body[key] = [
                        {"role": msg.role, "content": msg.content}
                        for msg in conversation_history
                    ]

        # Merge in any metadata
        if metadata:
            body.update(metadata)

        return body

    def _extract_content(self, response_data: Any) -> str:
        """Extract the text response from the agent's JSON response."""
        path = self._config.response.content_path
        content = extract_by_path(response_data, path)

        if content is None:
            # Fallback: if the response is a simple string, use it directly
            if isinstance(response_data, str):
                return response_data
            # Fallback: try common paths
            for fallback_path in ["$.response", "$.answer", "$.content", "$.message", "$.text"]:
                content = extract_by_path(response_data, fallback_path)
                if content is not None:
                    break

        if content is None:
            # Last resort: convert entire response to string
            return str(response_data)

        return str(content)

    def _extract_tool_calls(self, response_data: Any) -> List[ToolCall]:
        """Extract tool calls from the response, if configured."""
        path = self._config.response.tool_calls_path
        if not path:
            return []

        raw_calls = extract_by_path(response_data, path)
        if not raw_calls or not isinstance(raw_calls, list):
            return []

        tool_calls = []
        for call in raw_calls:
            if isinstance(call, dict):
                tool_calls.append(
                    ToolCall(
                        name=call.get("name", call.get("function", {}).get("name", "unknown")),
                        arguments=call.get("arguments", call.get("args", {})),
                        result=call.get("result"),
                    )
                )
        return tool_calls

    def _extract_token_usage(self, response_data: Any) -> Optional[TokenUsage]:
        """Extract token usage from the response, if configured."""
        path = self._config.response.token_usage_path
        if not path:
            return None

        usage = extract_by_path(response_data, path)
        if not usage or not isinstance(usage, dict):
            return None

        return TokenUsage(
            input_tokens=usage.get("input_tokens", usage.get("prompt_tokens", 0)),
            output_tokens=usage.get("output_tokens", usage.get("completion_tokens", 0)),
            total_tokens=usage.get("total_tokens", 0),
        )
