# ATTEST — Web Dashboard

> `attest serve` → opens http://localhost:8080
>
> *(Activate your virtual environment first so `attest` is on your PATH — see
> [Getting Started → Step 2](GETTING_STARTED.md). On Windows you can also run it directly with
> `.\.venv\Scripts\attest serve`.)*

## Overview

The ATTEST dashboard is a single-page web app (FastAPI + embedded HTML/CSS/JS) that provides visual management for all framework features. No build step — it's a single HTML file served by the API.

**Start:** `attest serve` or `attest serve --no-open`

> **First time?** The dashboard opens pre-loaded with **sample results for every test type**, so
> no page is ever empty. Read the **Help & About** page (bottom of the sidebar) for a 4-step
> getting-started walkthrough, then clear the demo data from **Settings → Demo & Example Data**
> whenever you want a clean slate.

## Pages

The sidebar groups pages into **Setup**, **Run & Evaluate**, and **Advanced**, with
**Settings** and **Help & About** pinned at the bottom.

### 1. Dashboard (Home)
- Time-based welcome header with **Run All Tests** / **Stop** buttons
- Workspace overview cards: Agents, Test Cases, Suites, Runs Logged (each clickable)
- **Latest Run** summary cards: Total, Passed, Failed, Errors, Pass Rate, Duration, Total Cost
- Latest results table with agent name, scores, latency

### 2. Agent Connections (Agent Setup)
- List all configured agents with a type badge (Foundry / HTTP / MCP)
- Add/Edit/Delete agents; Test Connection per agent (shows latency + response preview)
- Agent types: Azure Foundry, HTTP/REST, MCP server, or "Other framework" (code-only adapters)
- HTTP agents include an optional **🔀 Multi-agent routing** section (`handled_by` /
  `routing_path` JSONPaths) for orchestrators
- Saves to `attest.yaml`

### 3. Test Cases
- **Create Test**: Form with test name, suite selector, input, expected output, context, test
  type (single-turn / multi-turn / user simulation), assertion cards (Response Checks, Safety &
  Quality, Tool Call, **🔀 Multi-Agent Routing**, Structured Output / JSON), 36 evaluators across
  4 backends with status badges, and tags input
- **Upload**: Download CSV/JSONL templates, upload bulk test cases, auto-creates YAML suite files
- **All Tests**: Table view with name, suite, type, input, tags, assertions, evaluators

### 4. Test Suites
- **Create Suite**: Creates a YAML file with agent assignment
- **File-Based Suites**: Expandable cards with Run/Rename/Delete/Move controls per test
- **Tags**: Virtual suites via tags. Add/Remove tests. Run by tag.

### 5. Run Tests
- **Agent override**: Dropdown to run all tests with a different agent
- **Parallel** workers + **Profile** selector
- **Run by Tag**: Expandable tag-suite cards, each with its own ▶ Run Suite button
- **File suites**: Expandable with individual test run buttons
- **Run All Tests** + **Stop** (cancel a run in progress)

### 6. Results
- **Filters**: By agent, by status (passed/failed/error)
- **Score badges**: Compact "X.XX avg · N/M ✓" pill; full per-evaluator grid in the detail
- **Expandable details**: Evaluation scores, assertions, **🔀 routing path & handled-by**, tool
  calls, token usage/cost, and the full conversation trace
- **Run History**, **Compare Runs** (run-vs-run diff), **Clear Results**, **HTML Report**, **Export CSV**

### 7. Baselines
- Save golden response snapshots; compare current responses against them (regression diff)
- Shows content / tool-call / routing changes per scenario

### 8. Settings
- API key management with show/hide toggle (Azure + OpenAI)
- Execution & cost settings (caching, rate limit, max eval cost, Foundry upload)
- Current configuration display + evaluator backend status

### 9. Help & About
- Getting Started (4-step guide), "What is ATTEST", capability cards, and key concepts

## API Reference

### Agents
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/agents/current` | List all agents |
| POST | `/api/agents` | Save/update agent |
| POST | `/api/agents/test` | Test connection |
| DELETE | `/api/agents/{name}` | Remove agent |

### Test Cases
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/testcases` | List all tests |
| POST | `/api/testcases` | Create test |
| POST | `/api/testcases/upload` | Upload CSV/JSONL |
| GET | `/api/templates/csv` | Download CSV template |
| GET | `/api/templates/jsonl` | Download JSONL template |

### Suites
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/suites` | List file + tag suites |
| POST | `/api/suites` | Create suite |
| POST | `/api/suites/tag` | Add tag to tests |
| POST | `/api/suites/untag` | Remove tag |

### Execution
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/run` | Run all (accepts `{"agent":"name"}`) |
| POST | `/api/run/suite/{name}` | Run suite |
| POST | `/api/run/test/{name}` | Run single test |
| POST | `/api/run/tag/{name}` | Run by tag |

### Results & Analytics
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/results` | Latest results |
| DELETE | `/api/results` | Clear results |
| GET | `/api/runs` | Run history |
| GET | `/api/runs/{id}` | Get specific run |
| GET | `/api/compare?run_a=X&run_b=Y` | Compare two runs (per-test diffs) |
| GET | `/api/trends` | Score trends across all runs |
| GET | `/api/download/report` | Download HTML report |
| GET | `/api/download/csv` | Export results as CSV (for Excel) |

### Test Generation
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/testcases/generate-security` | Generate 30 red team attack tests |
| POST | `/api/testcases/generate` | AI-generate tests from agent description |
| GET | `/api/security/categories` | List attack categories |
