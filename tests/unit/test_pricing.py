"""Tests for model-aware token cost estimation."""
from attest.core.models import TokenUsage
from attest.core.pricing import (
    DEFAULT_INPUT_PER_1K,
    DEFAULT_OUTPUT_PER_1K,
    estimate_cost,
    lookup_price,
    normalize_model,
)


def test_normalize_strips_provider_prefix():
    assert normalize_model("azure/gpt-4.1-mini") == "gpt-4.1-mini"
    assert normalize_model("openai/gpt-4o") == "gpt-4o"
    assert normalize_model("GPT-4O") == "gpt-4o"
    assert normalize_model(None) == ""


def test_lookup_prefers_most_specific_key():
    # gpt-4o-mini must win over gpt-4o
    assert lookup_price("gpt-4o-mini") == (0.00015, 0.00060)
    assert lookup_price("gpt-4o") == (0.00250, 0.01000)
    # gpt-4.1-mini wins over gpt-4.1
    assert lookup_price("azure/gpt-4.1-mini") == (0.00040, 0.00160)


def test_lookup_unknown_returns_none():
    assert lookup_price("totally-made-up") is None
    assert lookup_price("") is None


def test_estimate_cost_uses_model_price():
    usage = TokenUsage(input_tokens=1000, output_tokens=1000, total_tokens=2000)
    # gpt-4o: 1*0.0025 + 1*0.01 = 0.0125
    assert estimate_cost(usage, "gpt-4o") == 0.0125


def test_estimate_cost_override_wins():
    usage = TokenUsage(input_tokens=1000, output_tokens=1000, total_tokens=2000)
    # explicit overrides beat the model table
    assert estimate_cost(usage, "gpt-4o", input_per_1k=0.001, output_per_1k=0.002) == 0.003


def test_estimate_cost_unknown_model_uses_default():
    usage = TokenUsage(input_tokens=1000, output_tokens=0, total_tokens=1000)
    expected = round((1000 / 1000.0) * DEFAULT_INPUT_PER_1K, 6)
    assert estimate_cost(usage, "mystery") == expected


def test_estimate_cost_no_usage_is_zero():
    assert estimate_cost(None, "gpt-4o") == 0.0


def test_estimate_cost_total_only_fallback():
    # Agent reported only total_tokens — treat as input so cost isn't lost.
    usage = TokenUsage(input_tokens=0, output_tokens=0, total_tokens=1000)
    assert estimate_cost(usage, "gpt-4o") == round((1000 / 1000.0) * 0.0025, 6)
