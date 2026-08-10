"""Azure Foundry Hosted (Container) Agent adapter.

Connects to *hosted container agents* — the newer Azure AI Foundry agent type
where the agent runs as a Docker container inside your Foundry project. These
agents are reached through a per-agent endpoint, NOT the shared Responses API
with an ``agent_reference`` (that is the older *prompt* agent style — use the
``foundry_prompt`` adapter for those).

Key differences vs. prompt agents:
  - URL:   {endpoint}/agents/{agent_name}/endpoint/protocols/openai/responses
  - Query: ?api-version=v1   (required — omitting it returns 400)
  - Body:  {"input": [...messages...]}   (no agent_reference)
  - Auth:  API key header, or an AAD bearer token for scope
           https://ai.azure.com/.default

Usage in attest.yaml:
    agents:
      my_hosted_agent:
        type: foundry_hosted
        endpoint: "https://your-resource.services.ai.azure.com/api/projects/your-project"
        agent_name: "My-Hosted-Agent"

Authentication (pick one):
  1. Put an API key in .env:  AZURE_API_KEY=your-key-here
  2. No key? DefaultAzureCredential (az login / Managed Identity / browser) is used.
"""

from __future__ import annotations

import asyncio
import json as _json
import os
import time
from typing import Any, Dict, List, Optional

from attest.adapters.base import BaseAgentAdapter
from attest.core.exceptions import AdapterError
from attest.core.models import AgentResponse, Message, ToolCall, TokenUsage

# Data-plane scope for Azure AI Foundry hosted agents.
FOUNDRY_TOKEN_SCOPE = "https://ai.azure.com/.default"


class FoundryHostedAgentAdapter(BaseAgentAdapter):
    """Adapter for Azure Foundry Hosted (container) Agents."""

    def __init__(
        self,
        endpoint: str,
        agent_name: str,
        api_key: Optional[str] = None,
        api_version: str = "v1",
        timeout: float = 420.0,
    ):
        """
        Args:
            endpoint: Foundry project endpoint URL
                      (from Foundry portal -> Code tab -> endpoint variable).
            agent_name: Hosted agent name (from Foundry portal -> agent title).
            api_key: API key (optional — also checked from .env / environment).
            api_version: API version query param (hosted agents require "v1").
            timeout: HTTP request timeout in seconds.
        """
        self._endpoint = endpoint.rstrip("/")
        self._agent_name = agent_name
        self._api_key = api_key
        self._api_version = api_version
        self._timeout = timeout
        self._credential = None
        self._connected = False

    @property
    def _agent_url(self) -> str:
        return (
            f"{self._endpoint}/agents/{self._agent_name}"
            "/endpoint/protocols/openai/responses"
        )

    def _resolve_api_key(self) -> Optional[str]:
        return (
            self._api_key
            or os.environ.get("AZURE_API_KEY")
            or os.environ.get("AZURE_OPENAI_API_KEY")
        )

    async def setup(self) -> None:
        """Prepare auth. Uses an API key if available, otherwise an AAD token."""
        try:
            if not self._resolve_api_key():
                # No key — prepare an Azure credential (SP, WIF, MI, CLI, browser).
                from attest.utils.azure_client import get_azure_credential

                self._credential = get_azure_credential()
            self._connected = True
        except ImportError:
            raise AdapterError(
                "Required packages not installed. Run: pip install attest"
            )
        except Exception as e:  # noqa: BLE001 — surface a friendly auth message
            raise AdapterError(f"Connection setup failed: {e}") from e

    async def teardown(self) -> None:
        """Cleanup."""
        self._credential = None
        self._connected = False

    def _build_headers(self) -> Dict[str, str]:
        api_key = self._resolve_api_key()
        if api_key:
            # Foundry accepts the key via the api-key header.
            return {"api-key": api_key}

        if self._credential is None:
            from attest.utils.azure_client import get_azure_credential

            self._credential = get_azure_credential()

        token = self._credential.get_token(FOUNDRY_TOKEN_SCOPE)
        return {"Authorization": f"Bearer {token.token}"}

    async def send_message(
        self,
        message: str,
        conversation_history: Optional[List[Message]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResponse:
        """Send a message to the hosted agent and get a response."""
        if not self._connected:
            await self.setup()

        messages: List[Dict[str, str]] = []
        if conversation_history:
            for msg in conversation_history:
                messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": message})

        import httpx

        start_time = time.perf_counter()
        try:
            headers = await asyncio.to_thread(self._build_headers)
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._agent_url,
                    json={"input": messages},
                    params={"api-version": self._api_version},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            body = e.response.text if e.response is not None else ""
            raise AdapterError(
                f"Hosted agent call failed ({e.response.status_code}): {body}"
            ) from e
        except Exception as e:  # noqa: BLE001
            raise AdapterError(f"Hosted agent call failed: {e}") from e

        latency_ms = (time.perf_counter() - start_time) * 1000
        content = _extract_output_text(data)
        tool_calls = _extract_tool_calls(data)
        token_usage = _extract_token_usage(data)

        return AgentResponse(
            content=content,
            latency_ms=latency_ms,
            tool_calls=tool_calls,
            token_usage=token_usage,
            raw_response=data,
        )

    async def health_check(self) -> bool:
        """Check if we can prepare a connection."""
        try:
            if not self._connected:
                await self.setup()
            return self._connected
        except Exception:
            return False


def _extract_output_text(data: Dict[str, Any]) -> str:
    """Pull assistant text out of a Responses-API JSON payload (dict form)."""
    if not isinstance(data, dict):
        return str(data)

    # Convenience field returned by the Responses API.
    if data.get("output_text"):
        return data["output_text"]

    parts: List[str] = []
    for item in data.get("output", []) or []:
        if item.get("type") == "message":
            for block in item.get("content", []) or []:
                text = block.get("text")
                if isinstance(text, dict):
                    text = text.get("value")
                if text:
                    parts.append(text)
    if parts:
        return "".join(parts)

    return data.get("output_text") or ""


def _extract_tool_calls(data: Dict[str, Any]) -> List[ToolCall]:
    """Extract tool calls from a Responses-API JSON payload (dict form)."""
    tool_calls: List[ToolCall] = []
    if not isinstance(data, dict):
        return tool_calls

    try:
        for item in data.get("output", []) or []:
            if item.get("type") == "function_call":
                args = item.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = _json.loads(args)
                    except (ValueError, TypeError):
                        args = {"_raw": args}
                tool_calls.append(
                    ToolCall(
                        name=item.get("name", "unknown"),
                        arguments=args or {},
                        result=item.get("output"),
                    )
                )
            elif item.get("type") == "function_call_output":
                output_val = item.get("output")
                if output_val and tool_calls:
                    for tc in reversed(tool_calls):
                        if not tc.result:
                            tc.result = output_val
                            break
    except Exception:
        pass  # Tool call extraction is best-effort.

    return tool_calls


def _extract_token_usage(data: Dict[str, Any]) -> Optional[TokenUsage]:
    """Extract token usage from a Responses-API JSON payload (dict form)."""
    if not isinstance(data, dict):
        return None
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return None
    try:
        return TokenUsage(
            input_tokens=usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0),
            output_tokens=usage.get("output_tokens", 0)
            or usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )
    except Exception:
        return None
