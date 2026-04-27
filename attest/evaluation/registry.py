"""Evaluator registry.

The registry is a simple lookup: evaluator name → evaluator class.
When a YAML scenario says evaluators: ["correctness", "relevancy"],
the registry creates the right evaluator instances.

It starts with built-in evaluators and can be extended with plugins.

Usage:
    from attest.evaluation.registry import EvaluatorRegistry

    registry = EvaluatorRegistry()
    evaluator = registry.get("correctness", threshold=0.8)
    result = await evaluator.evaluate(input)
"""

from __future__ import annotations

from typing import Dict, Optional, Type

from attest.evaluation.interface import BaseEvaluator
from attest.evaluation.builtin.correctness import CorrectnessEvaluator
from attest.evaluation.builtin.relevancy import RelevancyEvaluator
from attest.evaluation.builtin.hallucination import HallucinationEvaluator
from attest.evaluation.builtin.completeness import CompletenessEvaluator
from attest.evaluation.builtin.tone import ToneEvaluator


class EvaluatorRegistry:
    """Registry of all available evaluators.

    Looks up evaluators by name and creates instances with the right settings.
    Starts with built-in evaluators; plugins add more at runtime.
    """

    def __init__(self, model: str = "openai/gpt-4.1-mini"):
        self._model = model

        # Built-in evaluators — always available
        self._registry: Dict[str, Type[BaseEvaluator]] = {
            "correctness": CorrectnessEvaluator,
            "relevancy": RelevancyEvaluator,
            "hallucination": HallucinationEvaluator,
            "completeness": CompletenessEvaluator,
            "tone": ToneEvaluator,
        }

        # Auto-register DeepEval evaluators if installed
        try:
            from attest.plugins.deepeval_plugin.evaluators import register_deepeval_evaluators
            register_deepeval_evaluators(self)
        except ImportError:
            pass  # deepeval not installed — skip

        # Auto-register Azure evaluators if SDK installed
        try:
            from attest.plugins.azure_eval.evaluators import register_azure_evaluators
            register_azure_evaluators(self)
        except ImportError:
            pass  # azure-ai-evaluation not installed — skip

    def get(
        self,
        name: str,
        threshold: Optional[float] = None,
        **kwargs,
    ) -> BaseEvaluator:
        """Get an evaluator instance by name.

        Args:
            name: Evaluator name (e.g. "correctness", "relevancy").
            threshold: Override the default threshold (optional).
            **kwargs: Additional arguments passed to the evaluator constructor.

        Returns:
            An evaluator instance ready to use.

        Raises:
            KeyError if the evaluator name is not registered.
        """
        if name not in self._registry:
            available = list(self._registry.keys())
            raise KeyError(
                f"Unknown evaluator: '{name}'. Available: {available}"
            )

        cls = self._registry[name]

        # Build constructor args
        init_kwargs = {"model": self._model}
        if threshold is not None:
            init_kwargs["threshold"] = threshold
        init_kwargs.update(kwargs)

        return cls(**init_kwargs)

    def register(self, name: str, evaluator_class: Type[BaseEvaluator]) -> None:
        """Register a new evaluator (used by plugins).

        Args:
            name: Name to register under (e.g. "groundedness").
            evaluator_class: The evaluator class.

        Example:
            # In a plugin's setup:
            registry.register("groundedness", AzureGroundednessEvaluator)
        """
        self._registry[name] = evaluator_class

    def list_available(self) -> list:
        """List all registered evaluator names."""
        return sorted(self._registry.keys())

    def is_registered(self, name: str) -> bool:
        """Check if an evaluator name is registered."""
        return name in self._registry

    def resolve_evaluators(
        self,
        evaluator_specs: list,
        default_threshold: float = 0.7,
    ) -> list:
        """Resolve a list of evaluator specs from YAML into evaluator instances.

        Handles multiple formats from YAML:
            - "correctness"                          → name only, default threshold
            - {"correctness": {"threshold": 0.8}}    → name with custom threshold
            - {"correctness": 0.8}                   → shorthand for threshold

        Args:
            evaluator_specs: List from YAML scenario's evaluators field.
            default_threshold: Threshold to use when none is specified.

        Returns:
            List of evaluator instances.
        """
        evaluators = []
        for spec in evaluator_specs:
            if isinstance(spec, str):
                # Simple name: "correctness"
                evaluators.append(self.get(spec, threshold=default_threshold))

            elif isinstance(spec, dict):
                # Dict: {"correctness": {"threshold": 0.8}} or {"correctness": 0.8}
                for eval_name, config in spec.items():
                    if isinstance(config, dict):
                        threshold = config.get("threshold", default_threshold)
                    elif isinstance(config, (int, float)):
                        threshold = float(config)
                    else:
                        threshold = default_threshold

                    evaluators.append(self.get(eval_name, threshold=threshold))

        return evaluators
