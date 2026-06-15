# ATTEST Examples

Runnable examples showing how to test different kinds of AI agents with ATTEST.
Each example is self-contained and documented.

## Bundled example test suites (no setup)

ATTEST ships example scenarios for **every test type** in
[`tests/scenarios/example_*.yaml`](../tests/scenarios/). The single-turn, JSON,
multi-turn, safety, and security examples run **offline** against the built-in
`mock` agent — no API key needed. The tool-call, RAG, simulation, and routing
examples are templates you point at your own agent.

```bash
attest examples            # list the bundled examples
attest examples --run      # run the offline ones against the mock agent
attest serve               # explore them visually in the dashboard
```

The dashboard also shows **sample results** for every type on first launch, so
the Results page is never empty. Clear them anytime in **Settings → Demo &
Example Data** (or `attest examples` shows where they live).

## Python adapter examples

| Example | What it shows |
|---|---|
| [langchain_agent.py](langchain_agent.py) | Test a LangChain `AgentExecutor` with tool-call & content assertions |
| [langgraph_agent.py](langgraph_agent.py) | Test a compiled LangGraph graph (ReAct agent) |
| [http_agent.yaml](http_agent.yaml) | Test any HTTP/REST agent purely from YAML |
| [safety_and_quality.yaml](safety_and_quality.yaml) | New assertions: PII, cost, language, semantic match |

## Running the Python examples

```bash
# Install ATTEST in editable mode (makes `attest` importable), plus the adapter
pip install -e ".[langchain]"     # for langchain_agent.py
pip install -e ".[langgraph]"     # for langgraph_agent.py

python examples/langchain_agent.py
python examples/langgraph_agent.py
```

> If you run from a source checkout without installing, set `PYTHONPATH` to the
> repo root first: `PYTHONPATH=. python examples/langchain_agent.py`

## Running the YAML examples

```bash
# Point attest.yaml at your agent, then:
attest run --suite "HTTP Agent"
attest run --suite "Safety & Quality"
```

> The Python examples use small mock agents so they run without external API keys.
> Swap in your real agent object to test production code.
