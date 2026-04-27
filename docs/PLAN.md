# ATTEST — Project Status & Roadmap

## v0.1.0 — Current Release

### Implemented Features

| Category | Feature | Status |
|----------|---------|--------|
| **Core** | YAML test scenarios (single + multi-turn) | ✅ Done |
| **Core** | 23 assertion types (response 6, tool call 8, JSON 7, performance 2) | ✅ Done |
| **Core** | Test runner with async execution | ✅ Done |
| **Evaluators** | 5 built-in LLM-as-judge metrics | ✅ Done |
| **Evaluators** | 12 DeepEval metrics (quality, safety, RAG, agent) | ✅ Done |
| **Evaluators** | 15 Azure AI SDK metrics (quality, safety, NLP) | ✅ Done |
| **Evaluators** | Plugin architecture (BaseEvaluator, Registry) | ✅ Done |
| **Adapters** | Foundry Prompt Agent | ✅ Done |
| **Adapters** | HTTP/REST API | ✅ Done |
| **Adapters** | Python Callable | ✅ Done |
| **Adapters** | Auto-detect | ✅ Done |
| **Multi-Agent** | Multiple agent connections | ✅ Done |
| **Multi-Agent** | Agent override per run | ✅ Done |
| **Suites** | File-based suites (YAML files) | ✅ Done |
| **Suites** | Tag-based virtual suites | ✅ Done |
| **Dashboard** | 7-page web UI (FastAPI + HTML) | ✅ Done |
| **Dashboard** | Agent CRUD + test connection | ✅ Done |
| **Dashboard** | Test case creation (form + bulk upload) | ✅ Done |
| **Dashboard** | Results with filters (agent, status) | ✅ Done |
| **Dashboard** | Run history | ✅ Done |
| **Reports** | JSON results | ✅ Done |
| **Reports** | HTML visual report | ✅ Done |
| **Reports** | JUnit XML (CI/CD) | ✅ Done |
| **CLI** | init, run, serve, test-connection, version | ✅ Done |
| **Reports** | CSV export for Excel/Google Sheets | ✅ Done |
| **Upload** | CSV + JSONL templates with auto YAML creation | ✅ Done |
| **Conversations** | Multi-turn with per-turn assertions | ✅ Done |
| **Security** | Red team generator (30 attacks, 7 categories) | ✅ Done |
| **Security** | Safety evaluators (toxicity, bias, violence, etc.) | ✅ Done |
| **Analytics** | Run comparison API (per-test diffs) | ✅ Done |
| **Analytics** | Score trends across runs | ✅ Done |
| **Generation** | AI test generation from agent description | ✅ Done |
| **Generation** | Red team test generation (30 attack patterns) | ✅ Done |
| **Simulation** | User simulation (LLM plays personas, goal-driven multi-turn) | ✅ Done |
| **Simulation** | Dashboard UI for creating/running simulation tests | ✅ Done |
| **Plugins** | DeepEval auto-detects Azure OpenAI keys (no OPENAI_API_KEY needed) | ✅ Done |
| **Dashboard** | Evaluator status badges (shows installed/configured per backend) | ✅ Done |

### Architecture

```
User Interface Layer
├── CLI (attest run / serve / init)
├── Web Dashboard (http://localhost:8080)
└── Python API (from attest.core.runner import TestRunner)
        │
Core Engine
├── Config Loader (attest.yaml + .env)
├── Scenario Loader (YAML → TestCase objects)
├── Test Runner (orchestrates adapter → assertions → evaluators)
└── Assertions (23 deterministic checks)
        │
Evaluation Layer (32 metrics)
├── Built-in (5) — LLM-as-judge via LiteLLM
├── DeepEval Plugin (12) — Research-backed metrics
└── Azure AI Plugin (15) — Microsoft SDK
        │
Adapter Layer
├── Foundry Prompt Agent
├── HTTP/REST Agent
├── Callable Agent
└── Auto-detect
        │
Reporting
├── JSON (machine-readable)
├── HTML (visual, self-contained)
└── JUnit XML (CI/CD integration)
```

## v0.2.0 — Planned

| Feature | Priority | Status |
|---------|----------|--------|
| CI/CD pipeline templates | Medium | Planned |
| Ragas plugin | Low | Planned |
| LangSmith/Langfuse integration | Low | Planned |
| OpenAI/LangChain/CrewAI adapters | Low | Planned |
| PDF report export | Low | Planned |
