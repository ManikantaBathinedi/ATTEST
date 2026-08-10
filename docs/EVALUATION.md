---
title: ATTEST Evaluation System
description: Configure evaluator backends and publish ATTEST evaluation results to Microsoft Foundry.
ms.date: 2026-08-10
ms.topic: reference
---

## Overview

ATTEST provides 37 evaluators across 4 backends. Evaluators score agent
responses on a normalized 0.0-1.0 scale. Some use LLM judges, while safety and
NLP evaluators use hosted services or deterministic local calculations.

### Which evaluator should I use?

| If you want to check… | Start with |
|---|---|
| The answer is correct & on-topic | `correctness`, `relevancy` |
| It didn't make things up (with `context`) | `deepeval_faithfulness`, `groundedness` |
| It's safe (no toxicity, bias, harm) | `deepeval_toxicity`, `deepeval_bias`, `violence`, `hate_unfairness` |
| Your RAG retrieval is good | `ragas_faithfulness`, `ragas_context_precision`, `ragas_context_recall` |
| It called the right tools | `deepeval_tool_correctness`, `tool_call_accuracy` |

> Tip: the **Built-in** backend always works with just your LLM judge. Install DeepEval, Azure,
> or RAGAS only when you need their extra metrics — uninstalled backends are skipped silently.

## Evaluator Backends

### Built-in (5 metrics)
Uses your configured LLM judge (e.g., `azure/gpt-4.1-mini`). No extra install needed.

| Name | What It Checks |
|------|---------------|
| `correctness` | Response matches expected output (semantic) |
| `relevancy` | Response addresses the user's query |
| `hallucination` | Response doesn't fabricate information |
| `completeness` | All parts of multi-part questions answered |
| `tone` | Professional, appropriate tone |

### DeepEval (12 metrics)
Research-backed metrics from the DeepEval framework. Install: `pip install deepeval`

| Name | Category | What It Checks |
|------|----------|---------------|
| `deepeval_correctness` | Quality | GEval-based correctness |
| `deepeval_relevancy` | Quality | Answer relevancy |
| `deepeval_faithfulness` | Quality | Faithful to context (RAG) |
| `deepeval_hallucination` | Quality | Hallucination detection |
| `deepeval_summarization` | Quality | Summarization quality |
| `deepeval_json_correctness` | Quality | Valid JSON output |
| `deepeval_bias` | Safety | Gender, racial, other biases |
| `deepeval_toxicity` | Safety | Toxic/offensive content |
| `deepeval_contextual_relevancy` | RAG | Retrieved context is relevant |
| `deepeval_contextual_recall` | RAG | Context has all needed info |
| `deepeval_contextual_precision` | RAG | Context is precise/focused |
| `deepeval_tool_correctness` | Agent | Correct tools were used |

### Azure AI SDK and Content Safety (16 metrics)
Microsoft's production evaluation SDK. Install: `pip install azure-ai-evaluation`

| Name | Category | What It Checks |
|------|----------|---------------|
| `groundedness` | Quality | Response grounded in context |
| `azure_relevance` | Quality | Relevant to query |
| `coherence` | Quality | Logical flow and clarity |
| `fluency` | Quality | Language quality |
| `similarity` | Quality | Similar to expected output |
| `task_adherence` | Agent | Follows task instructions |
| `intent_resolution` | Agent | Resolves user intent |
| `tool_call_accuracy` | Agent | Correct tool usage |
| `response_completeness` | Agent | Complete response |
| `violence` | Safety | Violence detection (free) |
| `sexual` | Safety | Sexual content (free) |
| `self_harm` | Safety | Self-harm content (free) |
| `hate_unfairness` | Safety | Hate/bias detection (free) |
| `protected_code` | Safety/IP | Detects generated code matching known GitHub repository code (preview) |
| `f1_score` | NLP | F1 score (local, free) |
| `bleu_score` | NLP | BLEU score (local, free) |

### RAGAS (4 metrics)
RAG-focused metrics from the RAGAS framework. Install: `pip install ragas langchain-openai`

| Name | Category | What It Checks |
|------|----------|---------------|
| `ragas_faithfulness` | RAG | Answer is grounded in the retrieved context |
| `ragas_answer_relevancy` | RAG | Answer actually addresses the question |
| `ragas_context_precision` | RAG | Retrieved context is relevant/precise |
| `ragas_context_recall` | RAG | Context covers the reference answer |

## Usage in YAML

```yaml
evaluators:
  - correctness                          # Built-in, default threshold 0.7
  - deepeval_relevancy                   # DeepEval
  - groundedness                         # Azure
  - deepeval_toxicity: { threshold: 0.9 } # Custom threshold
```

## Reducing LLM-Judge Flakiness

LLM-as-judge scores can vary run-to-run. To stop a single unlucky sample from flipping a
pass/fail, run each evaluator N times and take the **median**:

```yaml
evaluation:
  samples: 3        # run every evaluator 3× and aggregate (median). 1 = off (default)
```

This trades extra LLM cost for stability — pair it with a small N (3–5) on the tests that
gate your CI. Also configurable in the dashboard under **Settings → Execution & Cost**.

## Publish results to Microsoft Foundry

Set `reporting.foundry_upload` to publish ATTEST runs to the Foundry portal's
**Evaluations** tab. The default `sdk` backend uses the official
`azure.ai.evaluation.evaluate()` API and returns a direct `studio_url`.

```yaml
reporting:
  output_dir: reports
  foundry_upload: true
  foundry_upload_backend: sdk
  foundry_metric_scope: all
  foundry_rest_fallback: false
  foundry_endpoint: "https://resource.services.ai.azure.com/api/projects/project"
```

Run normally or enable publication for one invocation:

```powershell
attest run --upload-to-foundry
```

ATTEST writes an SDK input dataset and local evaluation result under
`reports/foundry/`. The dataset contains each test's query, response, status,
agent, suite, evaluator scores, assertion pass rate, latency, token usage, and
diagnostic details. A deterministic SDK evaluator replays those already
computed metrics into Foundry, which avoids running LLM judges a second time.

The default `all` metric scope is recommended because Foundry accepts custom
evaluator outputs. ATTEST namespaces score metrics by backend, for example
`score_azure_groundedness`, `score_deepeval_faithfulness`,
`score_ragas_context_precision`, and `score_builtin_correctness`. The namespace
keeps metric provenance explicit and prevents an external evaluator from being
mistaken for a native Azure evaluator. Organizations that require a strict
Azure-only portal can set `foundry_metric_scope: azure_only`; operational
status and performance fields remain available, while external evaluator and
assertion metrics are omitted.

The SDK publication path requires Azure CLI or Microsoft Entra ID credentials
with access to the Foundry project. The endpoint can be omitted when a
`foundry_prompt` or `foundry_hosted` agent already provides the project
endpoint.

> [!WARNING]
> The `rest` backend is retained for compatibility, but its endpoint contract
> is not the recommended publication mechanism. REST fallback is opt-in through
> `foundry_rest_fallback: true`; SDK failures remain visible by default.

## Plugin Architecture

All evaluators implement `BaseEvaluator`:

```python
from attest.evaluation.interface import BaseEvaluator, EvaluationInput, EvaluationResult

class MyEvaluator(BaseEvaluator):
    @property
    def name(self) -> str:
        return "my_metric"

    async def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        # Your evaluation logic here
        return EvaluationResult(
            name=self.name, score=0.85, passed=True,
            threshold=self.threshold, reason="Good response",
            metadata={"backend": "custom"},
        )
```

Register in the evaluator registry:

```python
from attest.evaluation.registry import EvaluatorRegistry

registry = EvaluatorRegistry()
registry.register("my_metric", MyEvaluator)
```

## Auto-Registration

Plugins auto-register at startup if their package is installed:
- DeepEval: `pip install deepeval` → 12 metrics available
- Azure: `pip install azure-ai-evaluation` → 16 metrics available
- RAGAS: `pip install ragas langchain-openai` → 4 metrics available
- If not installed, the optional backend is silently skipped

### Protected Code Match configuration

`protected_code` calls the Azure AI Content Safety Protected Material for Code
preview API. It scans generated code against Microsoft's index of known GitHub
repository code and returns source URLs plus reported license metadata.

```dotenv
AZURE_CONTENT_SAFETY_ENDPOINT=https://your-resource.cognitiveservices.azure.com
AZURE_CONTENT_SAFETY_KEY=your-content-safety-key
```

The key can be omitted when Microsoft Entra ID authentication is available.
These values can also be configured from **Dashboard > Settings > API Keys**.

A detected match fails the evaluator and receives a normalized score of `0.0`;
no detected match passes with `1.0`. A match is a review signal, not a legal
conclusion. Review the returned source URLs and licenses before reuse.

> [!CAUTION]
> Microsoft documents that the protected-code index is current through April
> 6, 2023. A no-match result does not prove code originality, and code added to
> GitHub after that date might not be detected.

## Authentication for Evaluators

All evaluator backends support **keyless auth via Azure Entra ID** as well as API keys.

### Auth priority (all backends)
1. `OPENAI_API_KEY` → standard OpenAI (DeepEval native path)
2. `AZURE_API_KEY_OPENAI` / `AZURE_API_KEY` → Azure OpenAI with API key
3. Azure Entra ID (`az login` + `DefaultAzureCredential`) → keyless, no keys in files

### Keyless setup
```bash
az login
pip install azure-identity
# Set non-secret model values in .env, no keys:
AZURE_API_BASE=https://your-resource.openai.azure.com
AZURE_DEPLOYMENT_NAME=gpt-4.1-mini
```

### Per-backend details

**Built-in evaluators (5)**: Use LiteLLM with API key, or fall back to Azure Entra ID via shared client.

**DeepEval evaluators (12)**: Auto-detect credentials. If `OPENAI_API_KEY` is set, use it natively. Otherwise create Azure wrapper (key or Entra ID).

**Azure AI and Content Safety evaluators (16)** use family-specific authentication:

- Quality and agent evaluators require an Azure OpenAI endpoint and deployment; they support an API key or Entra ID
- Hosted safety evaluators (`violence`, `sexual`, `self_harm`, `hate_unfairness`) require a Foundry project and Entra `TokenCredential`
- `protected_code` requires a Content Safety endpoint and supports a Content Safety key or Entra ID
- Local NLP evaluators (`f1_score`, `bleu_score`) require no credentials

**RAGAS evaluators (4)**: Wrap RAGAS metrics with your configured LLM judge and embeddings (via `langchain-openai`). Support both API key and Entra ID.

## Evaluator Status API

`GET /api/evaluators/status` returns which backends are installed and configured:
```json
{
  "deepeval": {"installed": true, "configured": true},
  "azure_eval": {"installed": true, "configured": true},
  "ragas": {"installed": true, "configured": true},
  "builtin": {"installed": true, "configured": true}
}
```
The dashboard shows ✅/❌ badges next to each evaluator group in the Test Cases page.

## Results

Each evaluator produces an `EvalScore` with:
- `name`: Metric name
- `score`: 0.0-1.0 normalized
- `passed`: Above threshold?
- `reason`: LLM explanation
- `backend`: "builtin", "deepeval", "azure", or "ragas"

Results display in the dashboard with backend indicators (🧪 DeepEval, ☁️ Azure, 🔬 RAGAS).
