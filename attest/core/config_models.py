"""Configuration models for ATTEST.

These are simple Pydantic models that map to the attest.yaml file.
Each section of the YAML file has its own model, and they nest together
into the top-level AttestConfig.

Example attest.yaml:

    project:
      name: "My Tests"

    agents:
      my_bot:
        type: http
        endpoint: "http://localhost:8000"

    evaluation:
      backend: builtin
      judge:
        model: "openai/gpt-4.1-mini"

    tests:
      scenarios_dir: "tests/scenarios"

    reporting:
      output_dir: "reports"
      formats: [html, json]
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Agent config
# ---------------------------------------------------------------------------


class AuthConfig(BaseModel):
    """Authentication settings for an agent connection."""

    type: str = "none"  # none, api_key, bearer, azure_entra, service_principal, workload_identity, managed_identity, oauth2
    header: str = "Authorization"
    prefix: str = "Bearer"
    key: Optional[str] = None  # resolved from env vars
    token: Optional[str] = None
    token_url: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    scope: Optional[str] = None
    tenant_id: Optional[str] = None
    federated_token_file: Optional[str] = None  # For WIF (GitHub Actions, AKS)


class RequestConfig(BaseModel):
    """How to format the HTTP request to the agent."""

    method: str = "POST"
    path: str = "/chat"
    body_template: Dict[str, Any] = Field(default_factory=lambda: {"message": "{{input}}"})
    headers: Dict[str, str] = Field(
        default_factory=lambda: {"Content-Type": "application/json"}
    )


class ResponseConfig(BaseModel):
    """How to extract data from the agent's HTTP response."""

    content_path: str = "$.response"  # JSONPath to text response
    tool_calls_path: Optional[str] = None  # JSONPath to tool calls
    token_usage_path: Optional[str] = None  # JSONPath to token usage
    handled_by_path: Optional[str] = None  # JSONPath to the sub-agent that handled the request (multi-agent)
    routing_path_path: Optional[str] = None  # JSONPath to the routing chain list (multi-agent)


class MockConfig(BaseModel):
    """Settings for the offline ``mock`` adapter (no network / API key).

    The mock returns a canned reply so examples and the dashboard run end-to-end
    with zero setup. It picks the first ``replies`` entry whose keyword appears
    in the input (case-insensitive), else ``default`` (which may use ``{input}``).
    """

    default: str = "This is a mock agent reply to: {input}"
    replies: Dict[str, str] = Field(default_factory=dict)  # keyword -> reply text
    latency_ms: int = 25
    handled_by: Optional[str] = None  # echo a multi-agent routing decision
    routing_path: List[str] = Field(default_factory=list)


class PricingConfig(BaseModel):
    """Optional per-agent token price overrides (USD per 1,000 tokens).

    When set, these override the built-in model price table for exact,
    account-specific cost. Leave unset to price by the agent's ``model`` name.
    """

    input_per_1k: Optional[float] = None
    output_per_1k: Optional[float] = None


class AgentConfig(BaseModel):
    """Configuration for a single agent connection."""

    type: str = "http"  # http, websocket, callable, foundry_prompt, foundry_hosted, a2a, mcp, mock
    endpoint: Optional[str] = None
    agent_id: Optional[str] = None

    # Model name (used for token-cost estimation, e.g. "gpt-4o", "azure/gpt-4.1-mini")
    model: Optional[str] = None
    # Per-agent token price overrides (USD per 1k tokens) — exact cost if your rate differs
    pricing: PricingConfig = Field(default_factory=PricingConfig)

    # Foundry-specific
    agent_name: Optional[str] = None  # Foundry agent name (e.g. "Travel-Agent")
    agent_version: Optional[str] = None  # Foundry agent version (e.g. "3")

    # HTTP-specific
    request: RequestConfig = Field(default_factory=RequestConfig)
    response: ResponseConfig = Field(default_factory=ResponseConfig)

    # Auth
    auth: AuthConfig = Field(default_factory=AuthConfig)

    # Extra headers (on top of request.headers)
    headers: Dict[str, str] = Field(default_factory=dict)

    # MCP-specific
    command: Optional[str] = None
    transport: str = "stdio"  # stdio, sse
    args: List[str] = Field(default_factory=list)  # stdio server args
    default_tool: Optional[str] = None  # tool that send_message invokes
    input_arg: str = "input"  # tool argument that receives the message

    # Mock-specific (offline demo agent)
    mock: MockConfig = Field(default_factory=MockConfig)

    # Timeouts
    timeout: int = 30  # seconds


# ---------------------------------------------------------------------------
# Evaluation config
# ---------------------------------------------------------------------------


class JudgeConfig(BaseModel):
    """Settings for the built-in LLM-as-judge evaluator."""

    model: str = "openai/gpt-4.1-mini"
    temperature: float = 0.0
    max_tokens: int = 1024


class AzureEvalConfig(BaseModel):
    """Settings for the Azure AI Evaluation SDK backend."""

    project: Optional[str] = None  # Azure AI project URL
    model_config_dict: Dict[str, str] = Field(
        default_factory=dict,
        alias="model_config",
    )


class CostConfig(BaseModel):
    """Cost limits for evaluation runs."""

    max_eval_cost_per_run: float = 5.00  # USD
    cache_responses: bool = True
    rate_limit: float = 0  # Max requests/second to the agent. 0 = no limit.


class EvaluationConfig(BaseModel):
    """Evaluation engine settings."""

    backend: str = "builtin"  # builtin, azure, deepeval, ragas
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    azure: AzureEvalConfig = Field(default_factory=AzureEvalConfig)
    cost: CostConfig = Field(default_factory=CostConfig)


# ---------------------------------------------------------------------------
# Test discovery config
# ---------------------------------------------------------------------------


class TestsConfig(BaseModel):
    """Where to find test scenarios and test files."""

    scenarios_dir: str = "tests/scenarios"
    python_tests_dir: str = "tests"
    pattern: str = "test_*.py"


# ---------------------------------------------------------------------------
# Reporting config
# ---------------------------------------------------------------------------


class ReportingConfig(BaseModel):
    """Report generation settings."""

    output_dir: str = "reports"
    formats: List[str] = Field(default_factory=lambda: ["html", "json"])
    compare_with_previous: bool = True
    foundry_upload: bool = False  # Upload results to Foundry portal


# ---------------------------------------------------------------------------
# Dashboard config
# ---------------------------------------------------------------------------


class DashboardConfig(BaseModel):
    """Web dashboard settings."""

    port: int = 8080
    auto_open: bool = True


# ---------------------------------------------------------------------------
# Project config
# ---------------------------------------------------------------------------


class ProjectConfig(BaseModel):
    """Project-level metadata."""

    name: str = "ATTEST Project"
    version: str = "1.0"


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


class AttestConfig(BaseModel):
    """Top-level configuration — maps directly to attest.yaml.

    Every section is optional with sensible defaults, so even an empty
    attest.yaml produces a valid config.
    """

    project: ProjectConfig = Field(default_factory=ProjectConfig)
    agents: Dict[str, AgentConfig] = Field(default_factory=dict)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    tests: TestsConfig = Field(default_factory=TestsConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
