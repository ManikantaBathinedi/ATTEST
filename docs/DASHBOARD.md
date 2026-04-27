# ATTEST — Web Dashboard

> `attest serve` → opens http://localhost:8080

## Overview

The ATTEST dashboard is a single-page web app (FastAPI + embedded HTML/CSS/JS) that provides visual management for all framework features. No build step — it's a single HTML file served by the API.

**Start:** `attest serve` or `attest serve --no-open`

## Pages

### 1. Dashboard (Home)
- Summary cards: Total Tests, Passed, Failed, Pass Rate, Duration
- Run All Tests button
- Latest results table with agent name, scores, latency

### 2. Agent Connections
- List all configured agents with type badge (Foundry/HTTP)
- Add/Edit/Delete agents
- Test Connection per agent (shows latency + response preview)
- Saves to `attest.yaml`

### 3. Test Cases
- **Create Test**: Form with test name, suite selector, input, expected output, test type (single-turn / multi-turn / user simulation), assertions checkboxes, 32 evaluators across 3 backends with status badges, tags input
- **Upload**: Download CSV/JSONL templates, upload bulk test cases, auto-creates YAML suite files
- **All Tests**: Table view with name, suite, type, input, tags, assertions, evaluators

### 4. Test Suites
- **Create Suite**: Creates a YAML file with agent assignment
- **File-Based Suites**: Expandable cards with Run/Rename/Delete/Move controls per test
- **Tags**: Virtual suites via tags. Add/Remove tests. Run by tag.

### 5. Run Tests
- **Agent override**: Dropdown to run all tests with a different agent
- **Run by Tag**: Quick-run buttons for each tag
- **File suites**: Expandable with individual test run buttons

### 6. Results
- **Filters**: By agent, by status (passed/failed/error)
- **Score badges**: Color-coded with backend indicators (🧪 DeepEval, ☁️ Azure)
- **Expandable details**: Conversation trace, score progress bars, assertion details
- **Run History / Clear Results / Download Report**

### 7. Settings
- API key management with show/hide toggle
- Configuration display

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
