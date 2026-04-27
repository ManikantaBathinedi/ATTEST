# ATTEST — Copilot Reference Document

> Complete context for AI coding assistants. Contains every detail about the codebase, architecture, APIs, and how to modify anything.

---

## What is ATTEST?

ATTEST (Agent Testing & Trust Evaluation Suite) is a Python framework for testing AI agents. It works with any agent (Azure Foundry, HTTP APIs, etc.) and provides 23 assertions, 32 LLM evaluators across 3 backends, a 7-page web dashboard, CLI, security red-teaming, and multi-format reporting.

**Version**: 0.1.0 | **Python**: 3.9+ | **License**: MIT

---

## Project Structure

```
attest/                          ← Main Python package
├── __init__.py                  ← Public API exports
├── version.py                   ← Version string "0.1.0"
├── quick.py                     ← Quick-start helpers
├── plugin.py                    ← Pytest plugin
│
├── core/                        ← Core engine
│   ├── models.py                ← Pydantic models: TestCase, TestResult, EvalScore, RunSummary, AgentResponse, Message, ToolCall
│   ├── config.py                ← load_config(): reads attest.yaml + .env
│   ├── config_models.py         ← AgentConfig, AttestConfig, EvalConfig
│   ├── runner.py                ← TestRunner: orchestrates adapter→assertions→evaluators per test
│   ├── scenario_loader.py       ← Loads YAML files → List[TestCase]
│   ├── assertions.py            ← 23 assertion functions + YAML resolver
│   └── exceptions.py            ← AdapterError, EvaluationError, ConfigError
│
├── adapters/                    ← Agent connectors
│   ├── __init__.py              ← create_adapter(config) factory
│   ├── base.py                  ← BaseAgentAdapter ABC: setup(), send_message(), teardown()
│   ├── http_rest.py             ← HttpAgentAdapter: generic REST APIs
│   ├── callable_adapter.py      ← CallableAgentAdapter: Python functions
│   ├── auto_detect.py           ← Auto-detect adapter type
│   └── foundry/
│       └── prompt_agent.py      ← FoundryPromptAgentAdapter: Azure Foundry (uses OpenAI SDK)
│
├── evaluation/                  ← Evaluator framework
│   ├── interface.py             ← BaseEvaluator ABC, EvaluationInput, EvaluationResult
│   ├── registry.py              ← EvaluatorRegistry: auto-registers builtin+deepeval+azure at __init__
│   ├── llm_judge.py             ← LLMJudge: calls LLM via LiteLLM, parses score JSON
│   └── builtin/                 ← 5 built-in evaluators
│       ├── correctness.py       ← Factual correctness vs expected output
│       ├── relevancy.py         ← Response addresses the query
│       ├── hallucination.py     ← Detects fabricated information
│       ├── completeness.py      ← All parts of question answered
│       └── tone.py              ← Professional/appropriate tone
│
├── plugins/                     ← Evaluator plugins (auto-registered if installed)
│   ├── deepeval_plugin/
│   │   ├── __init__.py
│   │   └── evaluators.py        ← 12 DeepEval wrappers: DeepEvalBase → each metric class
│   ├── azure_eval/
│   │   ├── __init__.py
│   │   └── evaluators.py        ← 15 Azure SDK wrappers: AzureEvaluatorBase → each metric
│   └── ragas_plugin/            ← Placeholder (not implemented, covered by DeepEval)
│
├── dashboard/                   ← Web UI
│   └── api/
│       ├── app.py               ← FastAPI backend (~1200 lines): all REST endpoints
│       └── frontend.html        ← Single-file SPA (~1500 lines): HTML+CSS+JS, dark theme
│
├── cli/                         ← Typer CLI
│   ├── main.py                  ← Entry point: app = typer.Typer()
│   ├── run_cmd.py               ← attest run implementation
│   ├── serve_cmd.py             ← attest serve (starts uvicorn)
│   └── init_cmd.py              ← attest init scaffolding
│
├── conversation/
│   └── flow.py                  ← run_conversation(): multi-turn with history + per-turn assertions
│
├── reporting/
│   ├── html_report.py           ← Jinja2 self-contained HTML report
│   └── junit_xml.py             ← JUnit XML for CI/CD
│
├── security/
│   └── red_team.py              ← RedTeamGenerator: 30 attacks, 7 categories, ATTACK_PATTERNS dict
│
├── simulation/                  ← User simulation (LLM plays realistic users)
│   ├── __init__.py
│   └── user_simulator.py        ← UserSimulator: persona + goal → multi-turn conversation with agent
│
└── utils/                       ← Shared utilities

tests/
├── scenarios/                   ← YAML test case files (one file = one suite)
│   ├── 01_basic_behavior.yaml
│   ├── 02_safety.yaml
│   ├── 03_quality.yaml
│   ├── 04_llm_evaluated.yaml
│   └── 05_multi_turn.yaml
└── test_travel_agent.py         ← Pytest integration tests

docs/                            ← Documentation
templates/                       ← CSV/JSONL upload templates
demo/                            ← Mock agent + sample config
reports/                         ← Generated results + history
```

---

## Data Flow

```
YAML test files + attest.yaml + .env
        │
  scenario_loader.py → List[TestCase]
  config.py → AttestConfig
        │
  runner.py (TestRunner)
        │
        ├── Routes by type:
        │   ├── single_turn → _run_single_turn()
        │   ├── conversation → _run_conversation() (uses conversation/flow.py)
        │   └── simulation  → _run_simulation() (uses simulation/user_simulator.py)
        │
        ├── For each TestCase:
        │   ├── 1. _get_adapter(agent_name) → BaseAgentAdapter
        │   ├── 2. adapter.send_message(input) → AgentResponse
        │   ├── 3. run_assertions(response, fns) → List[AssertionResult]
        │   ├── 4. _run_evaluators(test_case, response) → List[EvalScore]
        │   └── 5. _determine_status() → TestResult (pass/fail/error)
        │
  RunSummary → reports/results.json + reports/history/
```

---

## Key Patterns

### Adding a New Assertion
1. Write function in `attest/core/assertions.py` returning `AssertionResult`
2. Add entry to `registry` dict in `resolve_assertion()` function
3. Add UI checkbox in `attest/dashboard/api/frontend.html` (search for `section-card`)

### Adding a New Evaluator
1. Create class inheriting `BaseEvaluator` in `attest/evaluation/builtin/` or `attest/plugins/`
2. Implement `name` property + `async evaluate(EvaluationInput) → EvaluationResult`
3. Register: either in `registry.py.__init__()` or via plugin's `register_*()` function

### Adding a New Adapter
1. Create class inheriting `BaseAgentAdapter` in `attest/adapters/`
2. Implement `setup()`, `send_message(message, history) → AgentResponse`, `teardown()`
3. Add to `create_adapter()` factory in `attest/adapters/__init__.py`

### Adding an API Endpoint
1. Add route in `attest/dashboard/api/app.py` using `@app.get/post/delete`
2. Add JS function in `attest/dashboard/api/frontend.html`

### Adding a CLI Command
1. Add function with `@app.command()` in `attest/cli/main.py`

---

## How the Dashboard Backend Works

`attest/dashboard/api/app.py` structure:
- **State**: `_is_running`, `_latest_summary`, `_run_progress` (global vars)
- **Agent CRUD**: POST/GET/DELETE `/api/agents`
- **Test CRUD**: POST/GET/DELETE `/api/testcases`, upload, generate
- **Suite management**: `/api/suites` (file + tag based)
- **Execution**: POST `/api/run` → `_execute_tests()` runs in BackgroundTask
- **Progress**: `_run_progress` dict updated per-test, polled by frontend via `/api/status`
- **Results**: Read from `reports/results.json`, merge logic keys by `scenario|agent`
- **Templates**: Serve CSV/JSONL as downloads
- **Security**: POST `/api/testcases/generate-security` → `RedTeamGenerator`
- **AI Generate**: POST `/api/testcases/generate` → calls Azure OpenAI directly

### Frontend Architecture
- Single HTML file with embedded `<style>` and `<script>`
- Navigation: `showPage(name)` toggles `.page` divs
- Each page loads data via `fetch()` on navigation
- Polling: `pollProgress()` checks `/api/status` every 1.5s during runs
- Collapsible cards: `toggleCard()` + `toggleAllInCard()` for assertions/evaluators

---

## Installation

```bash
git clone <repo>; cd attest; python -m venv .venv; .venv/Scripts/activate; pip install -e "."
# Optional: pip install deepeval    (12 extra evaluators)
# Optional: pip install azure-ai-evaluation   (15 extra evaluators)
```

---

## Configuration

### attest.yaml
```yaml
project:
  name: "My Tests"
agents:
  my_agent:
    type: foundry_prompt         # or "http"
    endpoint: "https://..."
    agent_name: "Agent-Name"
    agent_version: "3"
evaluation:
  backend: builtin
  judge:
    model: "azure/gpt-4.1-mini"
tests:
  scenarios_dir: "tests/scenarios"
reporting:
  output_dir: "reports"
  formats: [json, html]
```

### .env
```
AZURE_API_KEY=your-key
AZURE_API_BASE=https://your-resource.openai.azure.com
AZURE_API_VERSION=2025-04-01-preview
```

---

## CLI Commands

| Command | What it does |
|---------|-------------|
| `attest run` | Run all tests |
| `attest run --suite "name"` | Run one suite |
| `attest run --tag smoke` | Run by tag |
| `attest serve` | Start web dashboard (port 8080) |
| `attest serve --port 9090 --no-open` | Custom port, no browser |
| `attest test-connection` | Verify agent reachable |
| `attest init --preset foundry` | Scaffold project |
| `attest version` | Show version |

---

## YAML Test Case Format

```yaml
name: "Suite Name"
agent: my_agent
tests:
  - name: test_name
    input: "User message"
    expected_output: "Ideal answer"          # Optional — for correctness eval
    context: "Source document text"           # Optional — for RAG/grounding eval
    tags: [smoke, regression]                # Optional — for grouping
    type: single_turn                        # or "conversation"
    assertions:                              # Deterministic checks (free, instant)
      - response_not_empty: true
      - response_contains: "Tokyo"
    evaluators:                              # LLM-judged quality (costs tokens)
      - correctness
      - deepeval_relevancy

  - name: multi_turn_test
    type: conversation
    tags: [regression]
    script:
      - user: "I want to book a flight"
        expect:
          response_not_empty: true
          response_contains_any: ["flight", "book"]
      - user: "To Tokyo, next Friday"
        expect:
          response_not_empty: true
    evaluators:
      - completeness

  - name: frustrated_customer_refund
    type: simulation
    persona: "Frustrated customer who received a damaged laptop. Gets increasingly impatient."
    input: "Get a full refund and return shipping label."
    max_turns: 8
    tags: [simulation, regression]
    evaluators:
      - relevancy
      - completeness
      - tone
```

---

## All 23 Assertions

### Response (6)
| YAML Key | Description |
|----------|-------------|
| `response_not_empty: true` | Response is not empty |
| `response_contains: "text"` | Substring match (case-insensitive) |
| `response_not_contains: "text"` | Must NOT contain |
| `response_contains_any: ["a","b"]` | At least one found |
| `response_matches_regex: "pattern"` | Regex match |
| `exact_match: "exact text"` | Exact string equality |

### Tool Calls (8)
| YAML Key | Description |
|----------|-------------|
| `tool_called: "name"` | Tool was called |
| `tool_not_called: "name"` | Tool was NOT called |
| `no_tool_called: true` | Zero tool calls |
| `tool_call_count: {name: "x", count: 2}` | Exact call count |
| `tool_called_with_args: {name: "x", args: {"k":"v"}}` | Args match |
| `tool_call_order: ["a","b","c"]` | Sequence check |
| `tool_args_contain: {name: "x", key: "k", contains: "v"}` | Arg substring |
| `tool_count: 3` | Total tool call count |

### Structured Output / JSON (7)
| YAML Key | Description |
|----------|-------------|
| `response_is_json: true` | Valid JSON |
| `json_schema: {type: object, required: [a,b]}` | JSON schema validation |
| `json_field: {path: "status", value: "ok"}` | Specific field value |
| `json_field_exists: ["name","email"]` | Fields exist |
| `json_field_regex: {path: "email", pattern: "^.+@.+$"}` | Field format |
| `json_array_length: {min: 1, max: 10, field: "items"}` | Array size |
| `classification: ["pos","neg","neutral"]` | Label one-of check |

### Performance (2)
| YAML Key | Description |
|----------|-------------|
| `latency_under: 5000` | Under N milliseconds |
| `token_usage_under: 500` | Under N tokens |

### Adding New Assertions
1. Add function in `attest/core/assertions.py`
2. Register in `resolve_assertion()` registry dict
3. Optionally add UI in `attest/dashboard/api/frontend.html`

---

## All 32 Evaluators

### Built-in (5) — always available
`correctness`, `relevancy`, `hallucination`, `completeness`, `tone`

### DeepEval (12) — `pip install deepeval`
**Quality**: `deepeval_correctness`, `deepeval_relevancy`, `deepeval_faithfulness`, `deepeval_hallucination`, `deepeval_summarization`, `deepeval_json_correctness`
**Safety**: `deepeval_bias`, `deepeval_toxicity`
**RAG**: `deepeval_contextual_relevancy`, `deepeval_contextual_recall`, `deepeval_contextual_precision`
**Agent**: `deepeval_tool_correctness`

> **DeepEval + Azure OpenAI**: DeepEval auto-detects your credentials:
> - If `OPENAI_API_KEY` is set → uses standard OpenAI (DeepEval native)
> - If `AZURE_API_BASE` + `AZURE_API_KEY` are set → creates Azure OpenAI wrapper automatically
> - No extra config needed — just set one set of keys in `.env`

### Azure AI (15) — `pip install azure-ai-evaluation`
**Quality**: `groundedness`, `azure_relevance`, `coherence`, `fluency`, `similarity`
**Agent**: `task_adherence`, `intent_resolution`, `tool_call_accuracy`, `response_completeness`
**Safety (free)**: `violence`, `sexual`, `self_harm`, `hate_unfairness`
**NLP (free)**: `f1_score`, `bleu_score`

### Usage in YAML
```yaml
evaluators:
  - correctness
  - deepeval_toxicity: { threshold: 0.9 }
  - groundedness
```

### Adding New Evaluators
1. Create class inheriting `BaseEvaluator` from `attest/evaluation/interface.py`
2. Implement `name` property and `evaluate()` method
3. Register in `attest/evaluation/registry.py` or create a plugin in `attest/plugins/`

---

## Adapters

| Type | Config `type` | Adapter Class | File |
|------|--------------|---------------|------|
| Azure Foundry | `foundry_prompt` | `FoundryPromptAgentAdapter` | `adapters/foundry/prompt_agent.py` |
| HTTP REST | `http` | `HttpAgentAdapter` | `adapters/http_rest.py` |
| Python Function | `callable` | `CallableAgentAdapter` | `adapters/callable_adapter.py` |
| Auto-detect | (auto) | `auto_detect.py` | `adapters/auto_detect.py` |

### Adding New Adapters
1. Create class inheriting `BaseAgentAdapter` from `adapters/base.py`
2. Implement `setup()`, `send_message()`, `teardown()`
3. Register in `adapters/__init__.py` `create_adapter()` factory

---

## Dashboard (Web UI)

**Start**: `attest serve` → http://localhost:8080

### Pages
1. **Dashboard** — Summary cards, run all, latest results
2. **Agent Setup** — Add/edit/delete/test agent connections
3. **Test Cases** — Create (form), Upload (CSV/JSONL), All Tests (table), Security Generator, AI Generator
4. **Test Suites** — Create file suites, manage tags, run per suite/tag
5. **Run Tests** — Agent override dropdown, run by tag/suite/individual, live progress
6. **Results** — Filter by agent/status, expand for errors/scores/tool calls/conversation, CSV export, HTML report, clear results, run history with delete
7. **Settings** — API key management

### Key API Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/agents/current` | List agents |
| POST | `/api/agents` | Save agent |
| DELETE | `/api/agents/{name}` | Delete agent |
| GET | `/api/testcases` | List all tests |
| POST | `/api/testcases` | Create test |
| POST | `/api/testcases/upload` | Upload CSV/JSONL |
| POST | `/api/testcases/generate-security` | Generate 30 red team tests |
| POST | `/api/testcases/generate` | AI generate from description |
| GET | `/api/suites` | List file + tag suites |
| POST | `/api/run` | Run all (body: `{"agent":"name"}`) |
| POST | `/api/run/suite/{name}` | Run suite |
| POST | `/api/run/test/{name}` | Run single test |
| POST | `/api/run/tag/{name}` | Run by tag |
| GET | `/api/status` | Running? + progress |
| GET | `/api/results` | Latest results |
| DELETE | `/api/results` | Clear results |
| GET | `/api/runs` | Run history |
| DELETE | `/api/runs/{id}` | Delete a run |
| GET | `/api/trends` | Score trends |
| GET | `/api/compare?run_a=X&run_b=Y` | Compare runs |
| GET | `/api/download/csv` | Export CSV |
| GET | `/api/download/report` | HTML report |
| GET | `/api/templates/csv` | CSV template |
| GET | `/api/security/categories` | Red team categories |
| GET | `/api/evaluators/status` | Check which backends are installed/configured |

### Tech Stack
- Backend: FastAPI + Uvicorn
- Frontend: Single HTML file (~1500 lines, embedded CSS+JS)
- No build step, no npm, no React

---

## Security / Red Team

30 built-in attack patterns across 7 categories:

| Category | Tests | Description |
|----------|-------|-------------|
| `prompt_injection` | 5 | Override system instructions |
| `jailbreak` | 5 | Bypass safety (DAN, roleplay) |
| `system_prompt_extraction` | 5 | Extract system prompt |
| `pii_extraction` | 3 | Extract personal info |
| `harmful_content` | 5 | Harmful/illegal requests |
| `bias_discrimination` | 4 | Biased responses |
| `tool_abuse` | 3 | Misuse tools |

### Generate
```python
from attest.security.red_team import RedTeamGenerator
gen = RedTeamGenerator()
gen.save_to_file("tests/scenarios/security.yaml")
```
Or from Dashboard: Test Cases → Upload → "Generate Security Tests"

---

## Multi-Agent Support

Configure multiple agents in `attest.yaml`. Switch between them:
- Test Cases reference agent by name
- Run Tests page has agent override dropdown
- Results show agent column with filter

---

## Reports

| Format | File | Description |
|--------|------|-------------|
| JSON | `reports/results.json` | Machine-readable, used by dashboard |
| HTML | `reports/report.html` | Self-contained visual report |
| JUnit XML | Generated on demand | CI/CD integration |
| CSV | Via `/api/download/csv` | Excel/Google Sheets |

---

## Data Models (attest/core/models.py)

### TestCase
```python
class TestCase(BaseModel):
    name: str
    suite: str = "default"
    tags: List[str] = []
    input: str
    expected_output: Optional[str] = None
    context: Optional[str] = None        # For RAG grounding
    type: str = "single_turn"            # "single_turn", "conversation", or "simulation"
    conversation_script: List[Dict] = []
    persona: Optional[str] = None        # For simulation tests
    max_turns: Optional[int] = None      # For simulation tests (default 8)
    assertions: List[Dict] = []
    evaluators: List[Any] = []
    agent: str = "default"
```

### TestResult
```python
class TestResult(BaseModel):
    scenario: str
    suite: str
    status: Status              # passed/failed/error
    messages: List[Message]     # conversation trace
    tool_calls: List[ToolCall]  # tool invocations
    scores: Dict[str, EvalScore]
    assertions: List[AssertionResult]
    latency_ms: float
    agent: str
    tags: List[str]
    error: Optional[str]
```

### EvalScore
```python
class EvalScore(BaseModel):
    name: str
    score: float          # 0.0-1.0
    passed: bool
    threshold: float
    reason: Optional[str]
    backend: str          # "builtin", "deepeval", "azure"
```

---

## File Locations Quick Reference

| What | Where |
|------|-------|
| Main config | `attest.yaml` |
| API keys | `.env` |
| Test scenarios | `tests/scenarios/*.yaml` |
| Results | `reports/results.json` |
| Run history | `reports/history/run_*.json` |
| HTML reports | `reports/report.html` |
| Dashboard backend | `attest/dashboard/api/app.py` |
| Dashboard frontend | `attest/dashboard/api/frontend.html` |
| Assertions code | `attest/core/assertions.py` |
| Runner code | `attest/core/runner.py` |
| Models | `attest/core/models.py` |
| Config models | `attest/core/config_models.py` |
| Evaluator registry | `attest/evaluation/registry.py` |
| DeepEval plugin | `attest/plugins/deepeval_plugin/evaluators.py` |
| Azure plugin | `attest/plugins/azure_eval/evaluators.py` |
| Red team | `attest/security/red_team.py` |
| User simulator | `attest/simulation/user_simulator.py` |
| CLI entry | `attest/cli/main.py` |
| Upload templates | `templates/` |
| Package config | `pyproject.toml` |

---

## Dependencies

**Core**: pydantic, httpx, ruamel.yaml, litellm, typer, rich, jinja2, jsonschema, python-dotenv, azure-ai-projects, azure-identity, openai, fastapi, uvicorn

**Optional**: deepeval, azure-ai-evaluation, ragas

**Dev**: pytest, pytest-asyncio, ruff, mypy

---

## Agent Types Supported

| Agent Type | How to Test |
|------------|-------------|
| Conversational | Response assertions + evaluators + multi-turn |
| Tool/Function-calling | 8 tool call assertions |
| RAG/Knowledge | context field + faithfulness/groundedness evaluators |
| Classification | `classification` assertion |
| Data Extraction | `json_field`, `json_field_exists`, `json_field_regex` |
| Decision/Routing | `json_field` + `classification` |
| Data Transformation | `json_schema`, `json_array_length` |
| Summarization | `deepeval_summarization` |
| Safety Testing | Red team generator + toxicity/bias evaluators |
| **User Simulation** | `type: simulation` + persona/goal → LLM plays user, evaluators judge |
---

## Environment Variables (.env)

```bash
# Agent authentication (Foundry)
AZURE_API_KEY=<key>                        # Foundry agent key (or leave blank for Entra ID)

# LLM Judge (evaluators, AI test gen, simulation)
AZURE_API_BASE=https://<resource>.openai.azure.com   # Azure OpenAI endpoint
AZURE_API_KEY_OPENAI=<key>                            # Azure OpenAI key (or leave blank for Entra ID)
AZURE_API_VERSION=2025-04-01-preview

# Standard OpenAI (alternative to Azure)
# OPENAI_API_KEY=sk-...

# Anthropic (for Claude as judge — builtin evaluators only)
# ANTHROPIC_API_KEY=sk-ant-...

# Azure eval SDK (optional)
# AZURE_SUBSCRIPTION_ID=<sub-id>
# AZURE_RESOURCE_GROUP=<rg>
# AZURE_PROJECT_NAME=<project>
```

### Keyless Auth (Azure Entra ID)

All components support keyless auth via `DefaultAzureCredential`:
1. Run `az login`
2. Set only `AZURE_API_BASE` in `.env` (no keys)
3. Install `pip install azure-identity`

Auth priority everywhere: API key → Entra ID (DefaultAzureCredential).
Shared client: `attest/utils/azure_client.py`

---

## Runner Internals (attest/core/runner.py)

```
TestRunner.__init__(config, scenarios_path)
  └── loads config, creates EvaluatorRegistry

TestRunner.run_all(agent_override=None, progress_callback=None)
  ├── loads test cases via scenario_loader
  ├── creates adapter per agent via create_adapter()
  ├── for each TestCase:
  │   ├── routes by type:
  │   │   ├── single_turn → _run_single_turn()
  │   │   ├── conversation → _run_conversation() (conversation/flow.py)
  │   │   └── simulation  → _run_simulation() (simulation/user_simulator.py)
  │   ├── calls adapter.send_message() → AgentResponse
  │   ├── runs assertions → List[AssertionResult]
  │   ├── runs evaluators → List[EvalScore]
  │   ├── status = "failed" if any assertion/eval fails
  │   └── appends TestResult
  └── returns RunSummary (total, passed, failed, errors, duration, results[])
```

- **Progress tracking**: `progress_callback({"current": n, "total": t, "test": name, "status": s})`
- **Agent override**: replaces all test agents at runtime (dashboard "Run as" dropdown)
- **Error isolation**: each test wrapped in try/except, errors don't stop the run

---

## Common Gotchas & Known Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| LiteLLM hangs on Windows | Async event loop conflict | AI test generation uses `AzureOpenAI` SDK directly instead |
| Agent override ignored | FastAPI `Optional[dict]` param parsing | Use `Request` object + `await request.json()` |
| Results overwritten per run | Same scenario name | Composite key `scenario\|agent` for merge |
| DeepEval import slow | Downloads models on first use | Expected, ~10s first time |
| Dashboard changes need restart | No hot reload | Restart `attest serve` |
| Azure eval SDK needs project | Requires subscription/RG/project env vars | Set all 3 in `.env` |
| Evaluator scores 0-1 | Some backends return 1-5 | Wrappers normalize to 0.0-1.0 |

---

## User Simulation (attest/simulation/user_simulator.py)

LLM-powered synthetic users that stress-test agents beyond hand-written scripts.

### How it works
1. Define a **persona** (who the user is) and **goal** (what they want)
2. LLM generates realistic first message based on persona
3. Message sent to agent via adapter → agent responds
4. LLM decides next turn: continue, escalate, or stop (goal achieved)
5. Repeat for max_turns or until `[CONVERSATION_ENDED]`
6. LLM generates summary + goal achievement assessment
7. Evaluators score the full conversation

### YAML format
```yaml
tests:
  - name: frustrated_refund
    type: simulation
    persona: "Frustrated customer who received a damaged laptop"
    input: "Get a full refund and return label"
    max_turns: 8
    evaluators: [relevancy, tone, completeness]
```

### Pass/fail logic
- **goal_achieved** assertion (LLM judges if goal was met)
- **evaluator scores** on full conversation
- Both must pass for the test to pass

### Dashboard UI
- Test Cases → Create → "User Simulation" test type button
- Purple simulation form: persona, goal, max_turns
- Test list shows 🎭 badge with turn count
- Results show full simulated conversation trace

### Key class: `UserSimulator`
```python
from attest.simulation import UserSimulator
sim = UserSimulator(model="azure/gpt-4.1-mini")
result = await sim.run(adapter, persona="...", goal="...", max_turns=8)
print(result.goal_achieved, result.summary, result.turn_count)
```