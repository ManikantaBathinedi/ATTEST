# ATTEST — Evaluation System

## Overview

ATTEST provides 32 evaluators across 3 backends. Evaluators use LLM-as-judge to score agent responses on a 0.0-1.0 scale.

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

### Azure AI SDK (15 metrics)
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
| `f1_score` | NLP | F1 score (local, free) |
| `bleu_score` | NLP | BLEU score (local, free) |

## Usage in YAML

```yaml
evaluators:
  - correctness                          # Built-in, default threshold 0.7
  - deepeval_relevancy                   # DeepEval
  - groundedness                         # Azure
  - deepeval_toxicity: { threshold: 0.9 } # Custom threshold
```

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
- Azure: `pip install azure-ai-evaluation` → 15 metrics available
- If not installed, silently skipped — no errors

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
# Set only endpoint in .env, no keys:
AZURE_API_BASE=https://your-resource.openai.azure.com
```

### Per-backend details

**Built-in evaluators (5)**: Use LiteLLM with API key, or fall back to Azure Entra ID via shared client.

**DeepEval evaluators (12)**: Auto-detect credentials. If `OPENAI_API_KEY` is set, use it natively. Otherwise create Azure wrapper (key or Entra ID).

**Azure AI evaluators (15)**: Auto-build `model_config` from env vars. Support both API key and Entra ID token provider.

## Evaluator Status API

`GET /api/evaluators/status` returns which backends are installed and configured:
```json
{
  "deepeval": {"installed": true, "configured": true},
  "azure_eval": {"installed": true, "configured": true},
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
- `backend`: "builtin", "deepeval", or "azure"

Results display in the dashboard with backend indicators (🧪 DeepEval, ☁️ Azure).
