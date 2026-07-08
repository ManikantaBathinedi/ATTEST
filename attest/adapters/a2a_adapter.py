"""A2A (Agent2Agent) protocol adapter.

Connects to agents that speak the A2A protocol — a JSON-RPC 2.0 over HTTP
standard for agent-to-agent communication (agent cards, message/send, tasks).

How it works:
    1. POSTs a JSON-RPC 2.0 ``message/send`` request to the A2A endpoint
    2. Extracts the reply text from the returned Message/Task ``parts``
    3. Optionally reads the agent card at ``/.well-known/agent.json`` for
       capabilities and health

Config (attest.yaml):

    agents:
      my_a2a_agent:
        type: a2a
        endpoint: "https://my-agent.example.com"   # A2A server base URL
        request:
          path: "/"                                # JSON-RPC endpoint path (default "/")
        auth:
          type: bearer
          token: "${A2A_TOKEN}"

The adapter is intentionally dependency-free (uses httpx, already required) so
it works without installing a vendor A2A SDK.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

import httpx

from attest.adapters.base import AgentCapabilities, BaseAgentAdapter
from attest.core.config_models import AgentConfig
from attest.core.exceptions import AdapterError
from attest.core.models import AgentResponse, Message


class A2AAgentAdapter(BaseAgentAdapter):
    """Adapter for agents implementing the A2A (Agent2Agent) protocol."""

    def __init__(self, config: AgentConfig):
        self._config = config
        self._client: Optional[httpx.AsyncClient] = None
        self._context_id: Optional[str] = None  # A2A conversation/context id

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def setup(self) -> None:
        self._client = httpx.AsyncClient(timeout=self._config.timeout)

    async def teardown(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def reset_conversation(self) -> None:
        self._context_id = None

    # ------------------------------------------------------------------
    # Core: send_message
    # ------------------------------------------------------------------

    async def send_message(
        self,
        message: str,
        conversation_history: Optional[List[Message]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResponse:
        if self._client is None:
            await self.setup()

        url = self._rpc_url()
        payload = self._build_rpc_request(message)
        headers = self._build_headers()

        start = time.perf_counter()
        try:
            resp = await self._client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
        except httpx.TimeoutException as e:
            raise AdapterError(f"A2A agent at {url} timed out after {self._config.timeout}s") from e
        except httpx.HTTPStatusError as e:
            raise AdapterError(
                f"A2A agent at {url} returned HTTP {e.response.status_code}: {e.response.text[:200]}"
            ) from e
        except httpx.ConnectError as e:
            raise AdapterError(f"Cannot connect to A2A agent at {url}. Is it running?") from e
        except Exception as e:  # noqa: BLE001
            raise AdapterError(f"A2A request to {url} failed: {e}") from e

        latency_ms = (time.perf_counter() - start) * 1000

        try:
            data = resp.json()
        except Exception:
            return AgentResponse(content=resp.text, latency_ms=latency_ms)

        # JSON-RPC error envelope
        if isinstance(data, dict) and data.get("error"):
            err = data["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise AdapterError(f"A2A agent returned an error: {msg}")

        result = data.get("result", data) if isinstance(data, dict) else data
        content = self._extract_text(result)
        # Track the A2A context id so multi-turn stays in the same conversation.
        ctx = self._find_context_id(result)
        if ctx:
            self._context_id = ctx

        return AgentResponse(
            content=content,
            latency_ms=latency_ms,
            raw_response=data,
        )

    # ------------------------------------------------------------------
    # Health check — read the agent card if available
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        if self._client is None:
            await self.setup()
        base = (self._config.endpoint or "").rstrip("/")
        # Prefer the well-known agent card; fall back to a base GET.
        for path in ("/.well-known/agent.json", "/.well-known/agent-card.json", "/"):
            try:
                r = await self._client.get(f"{base}{path}", timeout=5)
                if r.status_code < 500:
                    return True
            except Exception:
                continue
        return False

    async def get_capabilities(self) -> AgentCapabilities:
        """Read capabilities from the A2A agent card, if reachable."""
        caps = AgentCapabilities(supports_multi_turn=True)
        if self._client is None:
            await self.setup()
        base = (self._config.endpoint or "").rstrip("/")
        for path in ("/.well-known/agent.json", "/.well-known/agent-card.json"):
            try:
                r = await self._client.get(f"{base}{path}", timeout=5)
                if r.status_code == 200:
                    card = r.json()
                    card_caps = card.get("capabilities", {}) if isinstance(card, dict) else {}
                    caps.supports_streaming = bool(card_caps.get("streaming", False))
                    caps.metadata = card if isinstance(card, dict) else {}
                    skills = card.get("skills", []) if isinstance(card, dict) else []
                    caps.available_tools = skills if isinstance(skills, list) else []
                    break
            except Exception:
                continue
        return caps

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _rpc_url(self) -> str:
        endpoint = (self._config.endpoint or "").rstrip("/")
        path = self._config.request.path or "/"
        if not path.startswith("/"):
            path = "/" + path
        return f"{endpoint}{path}"

    def _build_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        headers.update(self._config.headers or {})
        auth = self._config.auth
        if auth.type == "api_key" and auth.key:
            prefix = f"{auth.prefix} " if auth.prefix else ""
            headers[auth.header] = f"{prefix}{auth.key}"
        elif auth.type == "bearer" and auth.token:
            headers["Authorization"] = f"Bearer {auth.token}"
        return headers

    def _build_rpc_request(self, message: str) -> Dict[str, Any]:
        """Build an A2A ``message/send`` JSON-RPC 2.0 request."""
        msg: Dict[str, Any] = {
            "role": "user",
            "parts": [{"kind": "text", "text": message}],
            "messageId": uuid.uuid4().hex,
        }
        if self._context_id:
            msg["contextId"] = self._context_id
        return {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex,
            "method": "message/send",
            "params": {"message": msg},
        }

    @staticmethod
    def _extract_text(result: Any) -> str:
        """Pull text out of an A2A Message or Task result.

        Handles both a direct Message (``parts``) and a Task whose status/
        artifacts contain messages with parts.
        """
        if result is None:
            return ""
        if isinstance(result, str):
            return result

        def _parts_text(parts: Any) -> str:
            if not isinstance(parts, list):
                return ""
            out = []
            for p in parts:
                if not isinstance(p, dict):
                    continue
                # A2A part: {"kind": "text", "text": "..."} (older: {"type":"text"})
                if p.get("text"):
                    out.append(str(p["text"]))
                elif isinstance(p.get("content"), str):
                    out.append(p["content"])
            return "".join(out)

        if isinstance(result, dict):
            # Direct message
            if result.get("parts"):
                text = _parts_text(result["parts"])
                if text:
                    return text
            # Task with status.message
            status = result.get("status")
            if isinstance(status, dict):
                sm = status.get("message")
                if isinstance(sm, dict) and sm.get("parts"):
                    text = _parts_text(sm["parts"])
                    if text:
                        return text
            # Task with artifacts -> artifact parts
            artifacts = result.get("artifacts")
            if isinstance(artifacts, list):
                collected = []
                for art in artifacts:
                    if isinstance(art, dict) and art.get("parts"):
                        collected.append(_parts_text(art["parts"]))
                if any(collected):
                    return "".join(collected)
            # history -> last agent message
            history = result.get("history")
            if isinstance(history, list) and history:
                for m in reversed(history):
                    if isinstance(m, dict) and m.get("role") in ("agent", "assistant") and m.get("parts"):
                        text = _parts_text(m["parts"])
                        if text:
                            return text
            # Common fallbacks
            for key in ("text", "content", "output", "response"):
                if isinstance(result.get(key), str):
                    return result[key]
        return ""

    @staticmethod
    def _find_context_id(result: Any) -> Optional[str]:
        if isinstance(result, dict):
            return result.get("contextId") or result.get("context_id")
        return None
