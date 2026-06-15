"""Mock agent adapter — an offline, zero-setup agent for demos and examples.

The mock adapter needs no network, no API key, and no external service. It
returns a canned reply based on simple keyword matching, so the shipped example
scenarios (and the dashboard) run end-to-end out of the box.

Configure it from ``attest.yaml``::

    agents:
      mock_agent:
        type: mock
        mock:
          default: "I'm a demo agent. You said: {input}"
          latency_ms: 25
          replies:
            tokyo: "Tokyo, Kyoto and Osaka are great places to visit in Japan."
            refund: "I can help with your refund. Please share your order number."

It also supports demonstrating multi-agent routing via ``handled_by`` /
``routing_path`` in the mock config.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from attest.adapters.base import AgentCapabilities, BaseAgentAdapter
from attest.core.config_models import MockConfig
from attest.core.models import AgentResponse, Message


class MockAgentAdapter(BaseAgentAdapter):
    """Offline agent that returns canned replies — for demos and examples."""

    def __init__(self, mock: Optional[MockConfig] = None):
        self._cfg = mock or MockConfig()

    def _pick_reply(self, message: str) -> str:
        lowered = (message or "").lower()
        for keyword, reply in self._cfg.replies.items():
            if keyword.lower() in lowered:
                return reply
        return self._cfg.default.replace("{input}", message or "")

    async def send_message(
        self,
        message: str,
        conversation_history: Optional[List[Message]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResponse:
        # Simulate a tiny bit of latency so timing-based assertions are realistic.
        latency_ms = max(0, int(self._cfg.latency_ms))
        if latency_ms:
            await asyncio.sleep(latency_ms / 1000)

        return AgentResponse(
            content=self._pick_reply(message),
            latency_ms=float(latency_ms),
            handled_by=self._cfg.handled_by,
            routing_path=list(self._cfg.routing_path),
        )

    async def health_check(self) -> bool:
        """The mock agent is always reachable."""
        return True

    async def get_capabilities(self) -> AgentCapabilities:
        return AgentCapabilities(
            supports_streaming=True,
            supports_tool_calls=False,
            supports_multi_turn=True,
        )
