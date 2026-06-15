"""OpenTelemetry tracing for ATTEST.

Emits spans for the key stages of a test run — the whole run, each test case,
the agent call, assertion evaluation, and LLM evaluation — so you can inspect
*why* a test behaved a certain way in any OpenTelemetry-compatible backend
(Jaeger, Azure Monitor, Foundry tracing, Langfuse OTel, Honeycomb, etc.).

Design goals:
  - **Zero hard dependency**: if ``opentelemetry`` isn't installed, every call
    is a cheap no-op. ATTEST runs exactly as before.
  - **Opt-in**: tracing only activates when enabled (env var or setup call).
  - **Safe**: a tracing failure never breaks a test run.

Enable with an env var (uses console exporter if no OTLP endpoint is set)::

    set ATTEST_TRACING=1
    # optional: point at a collector
    set OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317

Or programmatically::

    from attest.utils.tracing import setup_tracing
    setup_tracing()
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

_TRACER = None
_ENABLED = False


def setup_tracing(
    service_name: str = "attest",
    console: Optional[bool] = None,
) -> bool:
    """Initialize OpenTelemetry tracing. Returns True if tracing is active.

    Args:
        service_name: Logical service name reported on spans.
        console: Force the console exporter on/off. If None, the console
            exporter is used only when no OTLP endpoint is configured.

    No-ops gracefully (returns False) if OpenTelemetry isn't installed.
    """
    global _TRACER, _ENABLED

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
    except ImportError:
        _ENABLED = False
        return False

    try:
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)

        exporter = None
        otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        if otlp_endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                    OTLPSpanExporter,
                )

                exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            except ImportError:
                exporter = None  # OTLP exporter not installed — fall back

        use_console = console if console is not None else (exporter is None)
        if exporter is not None:
            provider.add_span_processor(BatchSpanProcessor(exporter))
        if use_console:
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

        trace.set_tracer_provider(provider)
        _TRACER = trace.get_tracer("attest")
        _ENABLED = True
        return True
    except Exception:
        _ENABLED = False
        return False


def _maybe_autostart() -> None:
    """Auto-enable tracing if ATTEST_TRACING is truthy and not yet started."""
    global _ENABLED
    if _TRACER is not None or _ENABLED:
        return
    if os.environ.get("ATTEST_TRACING", "").lower() in ("1", "true", "yes", "on"):
        setup_tracing()


@contextmanager
def span(name: str, attributes: Optional[Dict[str, Any]] = None) -> Iterator[Any]:
    """Context manager that opens a span when tracing is active, else a no-op.

    Usage::

        with span("test.case", {"attest.scenario": tc.name}) as s:
            ...
            set_span_attr(s, "attest.status", "passed")
    """
    _maybe_autostart()
    if _TRACER is None:
        yield None
        return

    try:
        with _TRACER.start_as_current_span(name) as otel_span:
            if attributes:
                for k, v in attributes.items():
                    try:
                        otel_span.set_attribute(k, v)
                    except Exception:
                        pass
            yield otel_span
    except Exception:
        # Never let tracing break the run.
        yield None


def set_span_attr(otel_span: Any, key: str, value: Any) -> None:
    """Set an attribute on a span (no-op if span is None / tracing off)."""
    if otel_span is None:
        return
    try:
        otel_span.set_attribute(key, value)
    except Exception:
        pass


def is_enabled() -> bool:
    """Whether tracing is currently active."""
    _maybe_autostart()
    return _TRACER is not None
