"""Agent adapters — connectors for different agent types.

An adapter's job is simple:
  1. Take a user message
  2. Send it to the agent (HTTP, function call, SDK, etc.)
  3. Return a standardized AgentResponse

The create_adapter() factory picks the right adapter based on config type.
"""

from attest.adapters.base import BaseAgentAdapter, AgentCapabilities
from attest.adapters.callable_adapter import CallableAgentAdapter
from attest.adapters.http_rest import HttpAgentAdapter
from attest.adapters.langchain_adapter import LangChainAgentAdapter
from attest.adapters.langgraph_adapter import LangGraphAgentAdapter
from attest.adapters.crewai_adapter import CrewAIAgentAdapter
from attest.adapters.autogen_adapter import AutoGenAgentAdapter
from attest.adapters.openai_assistant_adapter import OpenAIAssistantAdapter
from attest.adapters.mcp_adapter import MCPAgentAdapter
from attest.adapters.mock_adapter import MockAgentAdapter
from attest.core.config_models import AgentConfig
from attest.core.exceptions import ConfigError


def create_adapter(config: AgentConfig) -> BaseAgentAdapter:
    """Create the right adapter based on the agent's type field in config.

    Args:
        config: AgentConfig from attest.yaml

    Returns:
        The appropriate adapter instance, ready to use.

    Raises:
        ConfigError if the agent type is not recognized.
    """
    adapter_type = config.type.lower()

    # Mock — offline demo agent (no network / API key)
    if adapter_type == "mock":
        return MockAgentAdapter(config.mock)

    if adapter_type in ("http", "rest", "http_rest"):
        return HttpAgentAdapter(config)

    # Foundry Prompt Agent — uses Azure AI Projects SDK
    if adapter_type == "foundry_prompt":
        from attest.adapters.foundry.prompt_agent import FoundryPromptAgentAdapter

        if not config.endpoint:
            raise ConfigError("Foundry agent requires 'endpoint' (project endpoint URL)")
        if not config.agent_name:
            raise ConfigError("Foundry agent requires 'agent_name'")

        return FoundryPromptAgentAdapter(
            endpoint=config.endpoint,
            agent_name=config.agent_name,
            agent_version=config.agent_version or "latest",
            api_key=config.auth.key if config.auth.key else None,
        )

    # Foundry Hosted Agent — HTTP endpoint
    if adapter_type in ("foundry_hosted", "foundry_workflow"):
        return HttpAgentAdapter(config)

    if adapter_type == "callable":
        raise ConfigError(
            "Callable adapter cannot be created from YAML config — "
            "use CallableAgentAdapter directly in Python code."
        )

    if adapter_type in ("langchain", "langgraph", "crewai", "autogen", "openai_assistant"):
        adapter_class = {
            "langchain": "LangChainAgentAdapter",
            "langgraph": "LangGraphAgentAdapter",
            "crewai": "CrewAIAgentAdapter",
            "autogen": "AutoGenAgentAdapter",
            "openai_assistant": "OpenAIAssistantAdapter",
        }[adapter_type]
        raise ConfigError(
            f"The '{adapter_type}' adapter cannot be created from YAML config — "
            f"use {adapter_class} directly in Python code (it wraps an in-process "
            "agent object)."
        )

    # MCP — can be created from YAML (connects to a server via stdio or sse)
    if adapter_type == "mcp":
        if not config.command and not config.endpoint:
            raise ConfigError(
                "MCP agent requires 'command' (stdio) or 'endpoint' (sse url)."
            )
        return MCPAgentAdapter(
            command=config.command,
            args=config.args,
            url=config.endpoint if config.transport == "sse" else None,
            default_tool=config.default_tool,
            input_arg=config.input_arg,
        )

    raise ConfigError(
        f"Unknown agent type: '{config.type}'. "
        f"Supported types: mock, http, foundry_prompt, foundry_hosted, callable, mcp"
    )


__all__ = [
    "BaseAgentAdapter",
    "AgentCapabilities",
    "HttpAgentAdapter",
    "CallableAgentAdapter",
    "LangChainAgentAdapter",
    "LangGraphAgentAdapter",
    "CrewAIAgentAdapter",
    "AutoGenAgentAdapter",
    "OpenAIAssistantAdapter",
    "MCPAgentAdapter",
    "MockAgentAdapter",
    "create_adapter",
]
