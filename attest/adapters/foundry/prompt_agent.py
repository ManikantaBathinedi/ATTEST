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
from attest.core.models import AgentResponse, Message


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
                # Azure identity auth — tries CLI first, then opens browser
                from azure.ai.projects import AIProjectClient
                from azure.identity import (
                    ChainedTokenCredential,
                    AzureCliCredential,
                    InteractiveBrowserCredential,
                )

                credential = ChainedTokenCredential(
                    AzureCliCredential(),
                    InteractiveBrowserCredential(),
                )

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

        return AgentResponse(content=content, latency_ms=latency_ms)

    async def health_check(self) -> bool:
        """Check if we can connect."""
        try:
            if not self._connected:
                await self.setup()
            return self._connected
        except Exception:
            return False
