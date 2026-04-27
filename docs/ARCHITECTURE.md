# ATTEST — Architecture & Code Structure

This document explains the codebase so any developer can understand, modify, or extend ATTEST.

---

## Project Root

```
attest/                    ← Main Python package (all source code)
tests/                     ← Test scenarios (YAML files) + pytest tests
  scenarios/               ← YAML test case files (one per suite)
  data/                    ← Uploaded test data (CSV, JSONL)
docs/                      ← Documentation
templates/                 ← CSV/JSONL templates for bulk upload
demo/                      ← Demo mock agent + sample config
reports/                   ← Generated reports (JSON, HTML)
  history/                 ← Timestamped run history
attest.yaml                ← Main configuration file
.env                       ← API keys (not committed to git)
pyproject.toml             ← Package metadata, dependencies, entry points
README.md                  ← Project overview
```

---

## Package Structure (`attest/`)

```
attest/
├── __init__.py              ← Public API exports
├── version.py               ← Version string
├── quick.py                 ← Quick-start helpers
├── plugin.py                ← Pytest plugin integration
│
├── core/                    ← Core engine (the heart of ATTEST)
│   ├── models.py            ← Pydantic models: TestCase, TestResult, EvalScore, RunSummary
│   ├── config.py            ← Config loader (reads attest.yaml + .env)
│   ├── config_models.py     ← Config Pydantic models (AgentConfig, AttestConfig)
│   ├── runner.py            ← Test runner: orchestrates adapter → assertions → evaluators
│   ├── scenario_loader.py   ← Loads YAML/JSONL test files → TestCase objects
│   ├── assertions.py        ← 23 assertion functions (response, tool, JSON, classification)
│   └── exceptions.py        ← Custom exceptions
│
├── adapters/                ← Agent connectors (send message, get response)
│   ├── __init__.py          ← create_adapter() factory function
│   ├── base.py              ← BaseAgentAdapter (abstract interface)
│   ├── http_rest.py         ← HttpAgentAdapter (generic REST APIs)
│   ├── callable_adapter.py  ← CallableAgentAdapter (Python functions)
│   ├── auto_detect.py       ← Auto-detect adapter type from config
│   └── foundry/
│       └── prompt_agent.py  ← FoundryPromptAgentAdapter (Azure Foundry)
│
├── evaluation/              ← Evaluator framework
│   ├── interface.py         ← BaseEvaluator ABC, EvaluationInput, EvaluationResult
│   ├── registry.py          ← EvaluatorRegistry (name → evaluator lookup + auto-registration)
│   ├── llm_judge.py         ← LLMJudge (calls LLM via LiteLLM for scoring)
│   └── builtin/             ← 5 built-in evaluators
│       ├── correctness.py   ← Factual correctness vs expected
│       ├── relevancy.py     ← Response addresses the query
│       ├── hallucination.py ← Detects fabricated info
│       ├── completeness.py  ← All parts of question answered
│       └── tone.py          ← Professional/appropriate tone
│
├── plugins/                 ← Evaluation backend plugins
│   ├── deepeval_plugin/
│   │   └── evaluators.py    ← 12 DeepEval wrappers (quality, safety, RAG, agent)
│   ├── azure_eval/
│   │   └── evaluators.py    ← 15 Azure SDK wrappers (quality, safety, NLP)
│   └── ragas_plugin/        ← Placeholder (not implemented)
│
├── dashboard/               ← Web UI
│   └── api/
│       ├── app.py           ← FastAPI backend (~1200 lines, all API endpoints)
│       └── frontend.html    ← Single-file frontend (~1500 lines, HTML+CSS+JS)
│
├── cli/                     ← CLI commands (Typer)
│   ├── main.py              ← Entry point: attest run/serve/init/version/test-connection
│   ├── run_cmd.py           ← `attest run` implementation
│   ├── serve_cmd.py         ← `attest serve` implementation
│   └── init_cmd.py          ← `attest init` scaffolding
│
├── conversation/            ← Multi-turn conversation runner
│   └── flow.py              ← run_conversation() with per-turn assertions
│
├── reporting/               ← Report generators
│   ├── html_report.py       ← Self-contained HTML report
│   └── junit_xml.py         ← JUnit XML for CI/CD
│
├── security/                ← Red team / security testing
│   └── red_team.py          ← RedTeamGenerator: 30 attacks across 7 categories
│
├── simulation/              ← User simulation (LLM plays realistic users)
│   └── user_simulator.py    ← UserSimulator: persona + goal → multi-turn conversation
│
└── utils/                   ← Shared utilities
```

---

## Data Flow

```
User writes YAML test     attest.yaml config     .env API keys
        │                       │                      │
        ▼                       ▼                      ▼
  scenario_loader.py ──→ config.py loads ──→ env vars loaded
        │                       │
        ▼                       ▼
  List[TestCase]          AttestConfig
        │                       │
        └───────┬───────────────┘
                ▼
          runner.py (TestRunner)
                │
                ├── For each TestCase:\n routes by type:\n                │   ├── single_turn → _run_single_turn()\n                │   ├── conversation → _run_conversation()\n                │   └── simulation  → _run_simulation()\n                │\n                │   ├── 1. Get adapter (Foundry/HTTP/Callable)\n                │   ├── 2. Send message → AgentResponse\n                │   ├── 3. Run assertions (23 types) → AssertionResult[]\n                │   ├── 4. Run evaluators (32 metrics) → EvalScore[]\n                │   └── 5. Build TestResult (pass/fail/error)
                │
                ▼
          RunSummary
                │
                ├── reports/results.json
                ├── reports/report.html
                ├── reports/history/run_YYYYMMDD.json
                └── Dashboard displays via /api/results
```

---

## Key Files to Modify

| Want to... | Edit this file |
|------------|---------------|
| Add new assertion type | `attest/core/assertions.py` (add function + register in `resolve_assertion`) |
| Add new evaluator | Create in `attest/evaluation/builtin/` or `attest/plugins/`, register in `registry.py` |
| Add new agent adapter | Create in `attest/adapters/`, update `__init__.py` factory |
| Add API endpoint | `attest/dashboard/api/app.py` |
| Change UI | `attest/dashboard/api/frontend.html` (single file, search for section) |
| Add CLI command | `attest/cli/main.py` (Typer app) |
| Change test YAML format | `attest/core/scenario_loader.py` + `attest/core/models.py` |
| Add red team attacks | `attest/security/red_team.py` → `ATTACK_PATTERNS` dict |
| Change config structure | `attest/core/config_models.py` |

---

## How Evaluators Work

```
YAML: evaluators: ["correctness", "deepeval_relevancy"]
        │
        ▼
  EvaluatorRegistry.resolve_evaluators(specs)
        │
        ├── "correctness" → CorrectnessEvaluator (builtin)
        └── "deepeval_relevancy" → DeepEvalRelevancyEvaluator (plugin)
        │
        ▼ each evaluator.evaluate(EvaluationInput) → EvaluationResult
        │
        ▼ normalized to EvalScore(name, score 0-1, passed, reason, backend)
```

Auto-registration in `registry.py.__init__()`:
1. Built-in 5 evaluators always registered
2. `try: import deepeval_plugin → register 12` (skip if not installed)
3. `try: import azure_eval → register 15` (skip if not installed)

---

## How Assertions Work

```
YAML: assertions: [{response_contains: "Tokyo"}, {tool_called: "search"}]
        │
        ▼
  resolve_assertions(list) → List[AssertionFn]
        │
        ▼
  run_assertions(AgentResponse, fns) → List[AssertionResult]
```

To add a new assertion:
1. Write the function in `assertions.py`
2. Add it to the `registry` dict in `resolve_assertion()`
3. Optionally add UI checkbox in `frontend.html`

---

## Dashboard Architecture

- **Backend**: FastAPI app in `app.py` (~1200 lines)
- **Frontend**: Single HTML file with embedded CSS and JS (~1500 lines)
- **No build step**: No React, no npm — just serve the HTML file
- **State**: File-based (YAML tests, JSON results, .env keys)
- **Hot reload**: Not supported — restart `attest serve` after code changes

---

## Configuration

`attest.yaml` structure:
```yaml
project:
  name: "Project Name"
agents:
  agent_name:
    type: foundry_prompt | http
    endpoint: "..."
    agent_name: "..."        # Foundry only
    agent_version: "..."     # Foundry only
evaluation:
  backend: builtin
  judge:
    model: "azure/gpt-4.1-mini"
    temperature: 0.0
tests:
  scenarios_dir: "tests/scenarios"
reporting:
  output_dir: "reports"
  formats: [json, html]
```

`.env` keys:
```
AZURE_API_KEY=...
AZURE_API_BASE=...
AZURE_API_KEY_OPENAI=...
AZURE_API_VERSION=2025-04-01-preview
```
