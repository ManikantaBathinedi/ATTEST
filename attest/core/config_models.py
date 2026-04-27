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

    type: str = "none"  # none, api_key, bearer, azure_entra, oauth2
    header: str = "Authorization"
    prefix: str = "Bearer"
    key: Optional[str] = None  # resolved from env vars
    token: Optional[str] = None
    token_url: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    scope: Optional[str] = None
    tenant_id: Optional[str] = None


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


class AgentConfig(BaseModel):
    """Configuration for a single agent connection."""

    type: str = "http"  # http, websocket, callable, foundry_prompt, foundry_hosted, a2a, mcp
    endpoint: Optional[str] = None
    agent_id: Optional[str] = None

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
