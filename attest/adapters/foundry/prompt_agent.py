"""Azure Foundry Prompt Agent adapter.

Connects to agents created in the Azure Foundry portal.

Authentication (simple — pick one):
  1. Put API key in .env file:  AZURE_API_KEY=your-key-here  (easiest)
  2. No key? Browser opens, you click your account, done.

Usage in attest.yaml:
    agents:
      my_agent:
        type: foundry_prompt
        endpoint: "https://your-resource.services.ai.azure.com/api/projects/your-project"
        agent_name: "Travel-Agent"
        agent_version: "3"

How it works:
  1. Reads your endpoint + agent name from attest.yaml
  2. Reads API key from .env (or opens browser for login)
  3. Creates an OpenAI client pointing to your Foundry project
  4. Sends messages via the Responses API with agent_reference
  5. Returns the response in ATTEST's standard format
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from attest.adapters.base import BaseAgentAdapter
from attest.core.exceptions import AdapterError
from attest.core.models import AgentResponse, Message, ToolCall, TokenUsage


class FoundryPromptAgentAdapter(BaseAgentAdapter):
    """Adapter for Azure Foundry Prompt Agents."""

    def __init__(
        self,
        endpoint: str,
        agent_name: str,
        agent_version: str = "latest",
        api_key: Optional[str] = None,
    ):
        """
        Args:
            endpoint: Foundry project endpoint URL
                      (from Foundry portal -> Code tab -> endpoint variable)
            agent_name: Agent name (from Foundry portal -> agent title)
            agent_version: Agent version (from Foundry portal -> YAML tab -> id field)
            api_key: API key (optional — also checked from .env / environment)
        """
        self._endpoint = endpoint
        self._agent_name = agent_name
        self._agent_version = agent_version
        self._api_key = api_key
        self._openai_client = None
        self._connected = False

    async def setup(self) -> None:
        """Connect to the Foundry agent.

        Auth order:
          1. API key from constructor arg
          2. API key from AZURE_API_KEY env var (set in .env)
          3. API key from AZURE_OPENAI_API_KEY env var
          4. Azure CLI login (az login)
          5. Browser login (opens browser, user clicks account)
        """
        api_key = (
            self._api_key
            or os.environ.get("AZURE_API_KEY")
            or os.environ.get("AZURE_OPENAI_API_KEY")
        )

        try:
            if api_key:
                # API key auth — simplest, no login needed
                from openai import OpenAI

                self._openai_client = OpenAI(
                    base_url=f"{self._endpoint}/openai/v1",
                    api_key=api_key,
                )
                self._connected = True

            else:
                # Azure identity auth — tries SP, WIF, Managed Identity, CLI, browser
                from azure.ai.projects import AIProjectClient
                from attest.utils.azure_client import get_azure_credential

                credential = get_azure_credential()

                project_client = AIProjectClient(
                    endpoint=self._endpoint,
                    credential=credential,
                )
                self._openai_client = project_client.get_openai_client()
                self._connected = True

        except ImportError:
            raise AdapterError("Required packages not installed. Run: pip install attest")
        except Exception as e:
            msg = str(e)
            if any(kw in msg.lower() for kw in ["auth", "credential", "token", "401", "403"]):
                raise AdapterError(
                    "Authentication failed.\n\n"
                    "  Fix: Add your API key to a .env file:\n"
                    "    AZURE_API_KEY=your-key-here\n\n"
                    "  Find your key: Azure Foundry Portal -> Project -> Settings -> Keys\n\n"
                    f"  Detail: {msg}"
                ) from e
            raise AdapterError(f"Connection failed: {msg}") from e

    async def teardown(self) -> None:
        """Cleanup."""
        self._openai_client = None
        self._connected = False

    async def send_message(
        self,
        message: str,
        conversation_history: Optional[List[Message]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResponse:
        """Send a message to the Foundry agent and get a response."""
        if not self._connected:
            await self.setup()

        # Build messages
        messages = []
        if conversation_history:
            for msg in conversation_history:
                messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": message})

        # Call the agent
        start_time = time.perf_counter()
        try:
            response = self._openai_client.responses.create(
                input=messages,
                extra_body={
                    "agent_reference": {
                        "name": self._agent_name,
                        "version": self._agent_version,
                        "type": "agent_reference",
                    }
                },
            )
        except Exception as e:
            raise AdapterError(f"Agent call failed: {e}") from e

        latency_ms = (time.perf_counter() - start_time) * 1000
        content = response.output_text if hasattr(response, "output_text") else str(response)

        # Extract tool calls from the response output items
        tool_calls = []
        try:
            if hasattr(response, "output") and response.output:
                for item in response.output:
                    item_type = getattr(item, "type", None)
                    if item_type == "function_call":
                        import json as _json
                        args = getattr(item, "arguments", "{}")
                        tool_calls.append(ToolCall(
                            name=getattr(item, "name", "unknown"),
                            arguments=_json.loads(args) if isinstance(args, str) else (args or {}),
                            result=getattr(item, "output", None),
                        ))
                    elif item_type == "function_call_output":
                        # Match output to the last tool call with the same call_id
                        call_id = getattr(item, "call_id", None)
                        output_val = getattr(item, "output", None)
                        if call_id and output_val and tool_calls:
                            for tc in reversed(tool_calls):
                                if not tc.result:
                                    tc.result = output_val
                                    break
        except Exception:
            pass  # Tool call extraction is best-effort

        # Extract token usage
        token_usage = None
        try:
            usage = getattr(response, "usage", None)
            if usage:
                token_usage = TokenUsage(
                    input_tokens=getattr(usage, "input_tokens", 0) or getattr(usage, "prompt_tokens", 0),
                    output_tokens=getattr(usage, "output_tokens", 0) or getattr(usage, "completion_tokens", 0),
                    total_tokens=getattr(usage, "total_tokens", 0),
                )
        except Exception:
            pass  # Token usage extraction is best-effort

        return AgentResponse(
            content=content,
            latency_ms=latency_ms,
            tool_calls=tool_calls,
            token_usage=token_usage,
            raw_response=response,
        )

    async def health_check(self) -> bool:
        """Check if we can connect."""
        try:
            if not self._connected:
                await self.setup()
            return self._connected
        except Exception:
            return False
