"""Model-aware token cost calculation.

ATTEST reports the **real** token usage returned by each agent/model, and uses
this module to turn those tokens into an estimated USD cost based on the model's
published per-1K-token price.

Cost is an *estimate*: token counts are exact (model-reported), but the price
depends on the model and your billing agreement. Override prices per agent in
``attest.yaml`` (``pricing.input_per_1k`` / ``pricing.output_per_1k``) for
exact, account-specific numbers.

Prices below are approximate public list prices (USD per 1,000 tokens) and are
matched by longest substring against the normalized model name. Update them as
vendor pricing changes.
"""
from __future__ import annotations

from typing import Optional, Tuple

from attest.core.models import TokenUsage

# USD per 1,000 tokens: model-key -> (input_per_1k, output_per_1k)
# Keys are matched by longest substring against the normalized model name, so
# more specific keys (e.g. "gpt-4o-mini") win over generic ones (e.g. "gpt-4o").
MODEL_PRICES: dict[str, Tuple[float, float]] = {
    # OpenAI / Azure OpenAI — GPT-4.1 family
    "gpt-4.1-nano": (0.00010, 0.00040),
    "gpt-4.1-mini": (0.00040, 0.00160),
    "gpt-4.1": (0.00200, 0.00800),
    # GPT-4o family
    "gpt-4o-mini": (0.00015, 0.00060),
    "gpt-4o": (0.00250, 0.01000),
    # GPT-4 turbo / classic
    "gpt-4-turbo": (0.01000, 0.03000),
    "gpt-4-32k": (0.06000, 0.12000),
    "gpt-4": (0.03000, 0.06000),
    # GPT-3.5
    "gpt-3.5-turbo": (0.00050, 0.00150),
    # Reasoning models
    "o1-preview": (0.01500, 0.06000),
    "o1-mini": (0.00110, 0.00440),
    "o1": (0.01500, 0.06000),
    "o3-mini": (0.00110, 0.00440),
    "o3": (0.01000, 0.04000),
    "o4-mini": (0.00110, 0.00440),
    # Anthropic Claude
    "claude-3-5-haiku": (0.00080, 0.00400),
    "claude-3-5-sonnet": (0.00300, 0.01500),
    "claude-3-haiku": (0.00025, 0.00125),
    "claude-3-opus": (0.01500, 0.07500),
    "claude-3-sonnet": (0.00300, 0.01500),
    # Google Gemini
    "gemini-1.5-flash": (0.00007, 0.00030),
    "gemini-1.5-pro": (0.00125, 0.00500),
    "gemini-2.0-flash": (0.00010, 0.00040),
    # Meta Llama (typical hosted price)
    "llama-3.1-405b": (0.00270, 0.00270),
    "llama-3.1-70b": (0.00059, 0.00079),
    "llama-3.1-8b": (0.00005, 0.00008),
}

# Fallback when the model is unknown — approximates a mid-tier GPT-4o-class model.
DEFAULT_INPUT_PER_1K = 0.0025
DEFAULT_OUTPUT_PER_1K = 0.0100


def normalize_model(model: Optional[str]) -> str:
    """Strip provider prefixes / deployment noise to a comparable model key.

    e.g. ``azure/gpt-4.1-mini`` -> ``gpt-4.1-mini``; ``openai/gpt-4o`` -> ``gpt-4o``.
    """
    if not model:
        return ""
    name = model.strip().lower()
    # Drop provider prefix like "azure/", "openai/", "anthropic/"
    if "/" in name:
        name = name.split("/", 1)[1]
    return name


def lookup_price(model: Optional[str]) -> Optional[Tuple[float, float]]:
    """Return (input_per_1k, output_per_1k) for a model, or None if unknown."""
    name = normalize_model(model)
    if not name:
        return None
    # Longest matching key wins (most specific).
    best: Optional[str] = None
    for key in MODEL_PRICES:
        if key in name and (best is None or len(key) > len(best)):
            best = key
    return MODEL_PRICES[best] if best else None


def estimate_cost(
    token_usage: Optional[TokenUsage],
    model: Optional[str] = None,
    input_per_1k: Optional[float] = None,
    output_per_1k: Optional[float] = None,
) -> float:
    """Estimate USD cost from real token usage.

    Priority for the price used:
      1. Explicit ``input_per_1k`` / ``output_per_1k`` overrides (per-agent config).
      2. The model's entry in ``MODEL_PRICES`` (matched on ``model``).
      3. ``DEFAULT_*`` fallback prices.

    Returns 0.0 when there is no token usage (e.g. offline mock agent).
    """
    if token_usage is None:
        return 0.0

    in_tokens = token_usage.input_tokens or 0
    out_tokens = token_usage.output_tokens or 0
    # Some agents only report total_tokens — treat it all as input so cost isn't lost.
    if in_tokens == 0 and out_tokens == 0 and token_usage.total_tokens:
        in_tokens = token_usage.total_tokens

    if input_per_1k is not None and output_per_1k is not None:
        price_in, price_out = input_per_1k, output_per_1k
    else:
        looked_up = lookup_price(model)
        if looked_up is not None:
            price_in, price_out = looked_up
        else:
            price_in, price_out = DEFAULT_INPUT_PER_1K, DEFAULT_OUTPUT_PER_1K

    cost = (in_tokens / 1000.0) * price_in + (out_tokens / 1000.0) * price_out
    return round(cost, 6)
