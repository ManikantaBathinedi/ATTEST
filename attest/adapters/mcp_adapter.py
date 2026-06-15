"""MCP (Model Context Protocol) adapter.

Tests an MCP server's tools. MCP servers expose *tools* (and resources) that
agents call; this adapter connects to such a server, discovers its tools, and
invokes one — so you can assert on tool outputs, latency, and availability.

Requires the official ``mcp`` package:

    pip install mcp

Connect via stdio (a local server process) or SSE (a running HTTP server):

    from attest.adapters import MCPAgentAdapter

    # stdio: launch a server command
    adapter = MCPAgentAdapter(command="python", args=["my_mcp_server.py"],
                              default_tool="search", input_arg="query")

    # sse: connect to a running server
    adapter = MCPAgentAdapter(url="http://localhost:8000/sse",
                              default_tool="search", input_arg="query")

``send_message`` calls ``default_tool`` with ``{input_arg: message}`` and
returns the tool's text output. ``get_capabilities`` lists the server's tools.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from attest.adapters.base import AgentCapabilities, BaseAgentAdapter
from attest.core.exceptions import AdapterError
from attest.core.models import AgentResponse, Message, ToolCall


class MCPAgentAdapter(BaseAgentAdapter):
    """Adapter that calls tools on an MCP server."""

    def __init__(
        self,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        url: Optional[str] = None,
        default_tool: Optional[str] = None,
        input_arg: str = "input",
        env: Optional[Dict[str, str]] = None,
    ):
        """
        Args:
            command: Executable to launch an stdio MCP server (e.g. "python").
            args: Arguments for the stdio command.
            url: SSE endpoint of a running MCP server (alternative to command).
            default_tool: Tool name that ``send_message`` invokes. If omitted,
                the first discovered tool is used.
            input_arg: The tool argument name that receives the message.
            env: Optional environment variables for the stdio server.
        """
        if not command and not url:
            raise AdapterError("MCPAgentAdapter requires either 'command' (stdio) or 'url' (sse).")
        self._command = command
        self._args = args or []
        self._url = url
        self._default_tool = default_tool
        self._input_arg = input_arg
        self._env = env

    # ------------------------------------------------------------------
    # Session helper
    # ------------------------------------------------------------------
    def _client_context(self):
        """Return an async context manager yielding (read, write) streams."""
        try:
            if self._url:
                from mcp.client.sse import sse_client

                return sse_client(self._url)
            from mcp.client.stdio import stdio_client, StdioServerParameters

            params = StdioServerParameters(
                command=self._command, args=self._args, env=self._env
            )
            return stdio_client(params)
        except ImportError as e:
            raise AdapterError(
                "The 'mcp' package is required for MCPAgentAdapter. "
                "Install it with: pip install mcp"
            ) from e

    async def _with_session(self, fn):
        """Open a session, run fn(session), and clean up."""
        from mcp import ClientSession

        async with self._client_context() as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(session)

    # ------------------------------------------------------------------
    async def send_message(
        self,
        message: str,
        conversation_history: Optional[List[Message]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResponse:
        start = time.perf_counter()

        async def _call(session):
            tool = self._default_tool
            if tool is None:
                tools = await session.list_tools()
                names = [t.name for t in getattr(tools, "tools", [])]
                if not names:
                    raise AdapterError("MCP server exposes no tools to call.")
                tool = names[0]
            result = await session.call_tool(tool, {self._input_arg: message})
            return tool, result

        try:
            tool_name, result = await self._with_session(_call)
        except AdapterError:
            raise
        except Exception as e:  # noqa: BLE001
            raise AdapterError(f"MCP tool call failed: {e}") from e

        latency_ms = (time.perf_counter() - start) * 1000
        content = self._result_text(result)
        return AgentResponse(
            content=content,
            tool_calls=[ToolCall(name=tool_name, arguments={self._input_arg: message}, result=content)],
            latency_ms=latency_ms,
            raw_response=result,
        )

    async def health_check(self) -> bool:
        try:
            async def _ping(session):
                await session.list_tools()
                return True

            return await self._with_session(_ping)
        except Exception:
            return False

    async def get_capabilities(self) -> AgentCapabilities:
        try:
            async def _list(session):
                tools = await session.list_tools()
                return [
                    {"name": t.name, "description": getattr(t, "description", "")}
                    for t in getattr(tools, "tools", [])
                ]

            available = await self._with_session(_list)
        except Exception:
            available = []
        return AgentCapabilities(
            supports_tool_calls=True,
            supports_multi_turn=False,
            available_tools=available,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _result_text(result: Any) -> str:
        """Extract text from an MCP CallToolResult."""
        content = getattr(result, "content", None)
        if content is None:
            return str(result)
        parts: List[str] = []
        for block in content:
            text = getattr(block, "text", None)
            if text is not None:
                parts.append(text)
            elif isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
        return "".join(parts) if parts else str(content)
