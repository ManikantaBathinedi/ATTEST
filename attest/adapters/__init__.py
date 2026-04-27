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

    raise ConfigError(
        f"Unknown agent type: '{config.type}'. "
        f"Supported types: http, foundry_prompt, foundry_hosted, callable"
    )


__all__ = [
    "BaseAgentAdapter",
    "AgentCapabilities",
    "HttpAgentAdapter",
    "CallableAgentAdapter",
    "create_adapter",
]
