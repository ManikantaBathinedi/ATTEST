<p align="center">
  <strong>ATTEST</strong><br>
  <em>Agent Testing & Trust Evaluation Suite</em>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> &nbsp;|&nbsp;
  <a href="docs/GETTING_STARTED.md">Full Setup Guide</a> &nbsp;|&nbsp;
  <a href="docs/TEST_CREATION_GUIDE.md">Test Types</a> &nbsp;|&nbsp;
  <a href="docs/EVALUATION.md">Evaluators</a> &nbsp;|&nbsp;
  <a href="docs/DASHBOARD.md">Dashboard & API</a> &nbsp;|&nbsp;
  <a href="examples/">Examples</a>
</p>

---

**ATTEST** is an end-to-end testing framework for AI agents. Point it at any agent — Azure Foundry, HTTP API, or Python function — and test it with deterministic assertions, LLM-as-judge evaluators, multi-turn conversations, user simulations, and security red teaming. No agent code changes needed.

## Screenshots

| Dashboard | Agent Setup |
|---|---|
| ![Dashboard](screenshots/Dashboard.png) | ![Agent Setup](screenshots/agent%20setup.png) |

| Test Cases | Evaluators |
|---|---|
| ![Test Cases](screenshots/tastcases.png) | ![Evaluators](screenshots/testcase%20evaluators.png) |

| Upload Tests | Test Suites |
|---|---|
| ![Upload](screenshots/testcase%20upload.png) | ![Test Suites](screenshots/test%20suites.png) |

| Results | HTML Report |
|---|---|
| ![Results](screenshots/results.png) | ![HTML Report](screenshots/html%20report.png) |

---

## Why ATTEST?

Testing AI agents is hard. Responses are non-deterministic, tool calls are invisible, and safety risks are subtle. Existing tools solve pieces of the puzzle — ATTEST puts them together:

- **Write tests in YAML** — no code needed for common scenarios
- **34 deterministic assertions** — content, tool calls, JSON structure, routing, latency, TTFT, throughput, cost, PII, language, semantic similarity, golden baselines
- **36 LLM evaluators** — score relevancy, correctness, bias, toxicity, groundedness across 4 backends (built-in, DeepEval, Azure AI Evaluation, RAGAS)
- **Multi-turn conversations** — test booking flows, multi-step tasks, context retention
- **User simulation** — LLM plays realistic personas to find edge cases humans miss
- **Security red teaming** — 30 attacks across 7 categories (prompt injection, jailbreak, PII extraction)
- **Works with the frameworks you use** — LangChain, LangGraph, CrewAI, AutoGen, OpenAI Assistants, MCP, Azure Foundry, HTTP/REST, or any Python callable
- **Regression & trust over time** — golden baselines, run-vs-run comparison, CI regression gate
- **Web dashboard** — visual UI to create, run, and analyze tests without touching the CLI
- **CI/CD ready** — JUnit XML, Markdown/PR reports, GitHub Actions & Azure DevOps templates, exit codes

---

## How ATTEST compares

Most tools solve one slice of agent testing. ATTEST unifies deterministic checks, LLM-judged
evaluation, RAG metrics, regression baselines, safety red-teaming, and a dashboard in one
CI-ready package.

| Capability | ATTEST | LangSmith | DeepEval | Promptfoo | Ragas |
|---|:---:|:---:|:---:|:---:|:---:|
| Deterministic assertions (tools, JSON, routing, latency) | ✅ 34 | ⚠️ basic | ⚠️ limited | ✅ | ❌ |
| LLM-as-judge evaluators | ✅ 36 | ✅ | ✅ | ✅ | ✅ |
| Multiple eval backends in one tool | ✅ 4 | ❌ | ❌ | ⚠️ | ❌ |
| RAG evaluation (faithfulness, context recall) | ✅ | ⚠️ | ✅ | ⚠️ | ✅ |
| Multi-turn conversation testing | ✅ | ✅ | ⚠️ | ⚠️ | ❌ |
| User simulation (persona-driven) | ✅ | ⚠️ | ❌ | ❌ | ❌ |
| Security red-teaming (built-in attacks) | ✅ 30 | ❌ | ⚠️ | ⚠️ | ❌ |
| Golden baselines + regression gate | ✅ | ⚠️ | ❌ | ⚠️ | ❌ |
| Tool-call & multi-agent routing assertions | ✅ | ⚠️ | ⚠️ | ❌ | ❌ |
| Framework adapters (LangChain/LangGraph/CrewAI/AutoGen/OpenAI Assistants/MCP/Foundry/HTTP) | ✅ 8 | ⚠️ LC only | ⚠️ | ✅ | ❌ |
| Web dashboard (no-code) | ✅ | ✅ | ❌ | ⚠️ | ❌ |
| CI templates + PR/Markdown reports | ✅ | ⚠️ | ⚠️ | ✅ | ❌ |
| Self-hostable / no vendor lock-in | ✅ | ❌ | ✅ | ✅ | ✅ |

> ✅ first-class · ⚠️ partial / via add-ons · ❌ not available.
> Comparison reflects common usage at time of writing; capabilities of other tools evolve.

---

## Quick Start

### Try it instantly (no agent, no API key)

Want to see ATTEST in action first? It ships with example tests for **every test type**
that run offline against a built-in `mock` agent:

```bash
# 1. Clone and enter the repo
git clone https://github.com/ManikantaBathinedi/ATTEST.git
cd ATTEST

# 2. Create & activate a virtual environment
python -m venv .venv
# Windows (PowerShell):  .\.venv\Scripts\Activate.ps1
# macOS / Linux:         source .venv/bin/activate

# 3. Install, then explore
pip install -e "."
attest examples           # list the bundled example suites
attest examples --run     # run the offline ones against the mock agent
attest serve              # explore sample results for every type in the dashboard
```

> **`attest` not found?** The `attest` command only exists while your virtual environment is
> **activated** (Step 2). Re-run the activate line in any new terminal, or call it directly with
> `.\.venv\Scripts\attest serve` (Windows) / `.venv/bin/attest serve` (macOS/Linux).

The dashboard's Results page is pre-populated with **sample results** so nothing is empty on
first launch. Hide them anytime in **Settings → Demo & Example Data**. When you're ready to
test your own agent, follow the steps below.

### 1. Install

```bash
git clone https://github.com/ManikantaBathinedi/ATTEST.git
cd ATTEST

# Create & activate a virtual environment (so the `attest` command is on your PATH)
python -m venv .venv
# Windows (PowerShell):  .\.venv\Scripts\Activate.ps1
# macOS / Linux:         source .venv/bin/activate

pip install -e "."

# Optional evaluation backends & adapters
pip install -e ".[deepeval]"    # DeepEval (bias, toxicity, RAG metrics)
pip install -e ".[azure]"       # Azure AI Evaluation SDK
pip install -e ".[ragas]"       # RAGAS RAG metrics
pip install -e ".[langchain]"   # LangChain adapter
pip install -e ".[langgraph]"   # LangGraph adapter
pip install -e ".[all]"         # Everything
```

> **Remember:** activate the venv (`.\.venv\Scripts\Activate.ps1` on Windows) in **every new
> terminal** before running `attest ...`. You'll see `(.venv)` at the start of your prompt when
> it's active.

### 2. Initialize

```bash
attest init --preset foundry   # or: http
```

This creates `attest.yaml` and `.env` with placeholders.

### 3. Configure your agent

**attest.yaml:**
```yaml
agents:
  my_agent:
    type: foundry_prompt
    endpoint: "https://your-resource.services.ai.azure.com/api/projects/your-project"
    agent_name: "My-Agent"
    agent_version: "1"
```

**.env:**
```
AZURE_API_KEY=your-key-here
```

> Supports Azure Entra ID (keyless) authentication too. See [Getting Started](docs/GETTING_STARTED.md).

### 4. Verify connection

```bash
attest test-connection
```

### 5. Write tests

Create `tests/scenarios/my_tests.yaml`:

```yaml
name: My Agent Tests
agent: my_agent
tests:
  # Simple single-turn test
  - name: greeting
    input: "Hello, what can you help with?"
    tags: [smoke]
    assertions:
      - response_not_empty: true
      - latency_under: 10000
    evaluators:
      - relevancy
      - deepeval_toxicity

  # Multi-turn conversation
  - name: booking_flow
    type: conversation
    tags: [regression]
    script:
      - user: "I want to book a flight to Tokyo"
        expect:
          response_contains_any: [Tokyo, flight, book]
      - user: "Make it for next Friday"
        expect:
          response_not_empty: true

  # LLM-driven user simulation
  - name: frustrated_customer
    type: simulation
    persona: "Frustrated customer who received a damaged laptop"
    input: "Get a full refund and return shipping label"
    max_turns: 8
    evaluators: [relevancy, tone]
```

> See the [Test Creation Guide](docs/TEST_CREATION_GUIDE.md) for all 9 test types with examples.

### 6. Run

```bash
attest run                         # Run all tests
attest run --tag smoke             # Run by tag
attest run --suite "My Agent Tests"  # Run by suite name
```

### 7. View results

```bash
attest serve       # Opens dashboard at http://localhost:8080
```

Or check `reports/results.json` directly.

---

## Evaluators

ATTEST ships with **36 evaluators** across 4 backends. Mix and match in YAML:

| Backend | Count | Metrics |
|---------|-------|---------|
| **Built-in** | 5 | correctness, relevancy, hallucination, completeness, tone |
| **DeepEval** | 12 | bias, toxicity, faithfulness, contextual relevancy/recall/precision, tool correctness, summarization, and more |
| **Azure AI SDK** | 15 | groundedness, coherence, fluency, violence, self-harm, hate/unfairness, f1 score, BLEU, and more |
| **RAGAS** | 4 | faithfulness, answer relevancy, context precision, context recall |

```yaml
evaluators:
  - correctness                          # Built-in
  - deepeval_bias                        # DeepEval
  - groundedness                         # Azure AI SDK
  - deepeval_toxicity: { threshold: 0.9 }  # Custom threshold
```

> Deep dive: [Evaluation docs](docs/EVALUATION.md) — auth setup, custom evaluators, plugin architecture.

---

## Web Dashboard

Prefer a visual, no-code experience? Launch the dashboard:

```bash
attest serve                 # starts the web UI and opens your browser
# → ATTEST Dashboard starting on http://localhost:8080
```

Then open **http://localhost:8080** in your browser (use `--port 3000` to change the port).
If the auto-opened tab shows a connection error on Windows, open **http://127.0.0.1:8080** instead.

**9 pages**, grouped for a natural workflow:

- **Dashboard** — welcome overview: workspace counts (agents, tests, suites, runs) + latest-run stats
- *Setup:* **Agent Setup** (connect Foundry / HTTP / MCP agents), **Test Cases** (create or upload), **Test Suites** (organize by file & tags)
- *Run & Evaluate:* **Run Tests** (run all / suite / tag / single), **Results** (scores, latency, failures, compare runs)
- *Advanced:* **Baselines** (golden snapshots + regression diff)
- *Pinned:* **Settings** (API keys, cost controls, evaluator status), **Help & About** (getting-started guide + framework info)

Features: bulk CSV/JSONL upload, AI test generation, run history & run-vs-run comparison, named runs, trend charts, HTML/Markdown report export.

> API reference: [Dashboard docs](docs/DASHBOARD.md)

---

## Using from Python

```python
import asyncio
from attest.core.config import load_config
from attest.core.runner import TestRunner
from attest.core.scenario_loader import load_scenarios

async def main():
    config = load_config("attest.yaml")
    scenarios = load_scenarios(directory=config.tests.scenarios_dir)
    runner = TestRunner(config)
    summary = await runner.run(scenarios)

    print(f"Passed: {summary.passed}/{summary.total}")
    for r in summary.results:
        print(f"  {r.scenario}: {r.status} ({r.latency_ms:.0f}ms)")

asyncio.run(main())
```

---

## Project Structure

```
attest/
├── adapters/           # Agent connectors (Mock, Foundry, HTTP, Callable, LangChain, LangGraph, CrewAI, AutoGen, OpenAI Assistants, MCP)
├── cli/                # CLI commands (init, run, serve, examples, ci, test-connection)
├── core/               # Config, models, runner, assertions, scenario loader
├── conversation/       # Multi-turn conversation engine
├── dashboard/          # Web UI — FastAPI backend + single HTML frontend
├── evaluation/         # Evaluator framework + 5 built-in evaluators
├── plugins/
│   ├── deepeval_plugin/  # 12 DeepEval evaluators
│   ├── azure_eval/       # 15 Azure AI SDK evaluators
│   └── ragas_plugin/     # 4 RAGAS RAG evaluators
├── reporting/          # HTML, JUnit XML, CSV report generators
├── security/           # Red team attack generator (30 patterns)
└── simulation/         # User simulation (LLM-driven personas)
```

---

## Documentation

| Guide | What it covers |
|-------|---------------|
| [Getting Started](docs/GETTING_STARTED.md) | Full setup walkthrough — install, auth, first test run |
| [Test Creation Guide](docs/TEST_CREATION_GUIDE.md) | All 9 test types with YAML, CSV, JSONL, and Python examples |
| [Evaluation](docs/EVALUATION.md) | 36 evaluators, 4 backends, auth options, custom evaluators |
| [Dashboard & API](docs/DASHBOARD.md) | Dashboard pages, REST API reference |

---

## License

MIT
