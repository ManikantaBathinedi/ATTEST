"""Unit tests for ATTEST streaming support.

Covers:
  - The base default `send_message_stream` (single-chunk fallback)
  - `collect_stream` aggregation + time_to_first_token_ms
  - A LangChain agent that exposes `astream` (real streaming path)

Run:
    pytest tests/unit/test_streaming.py -v
"""

from attest.adapters import CallableAgentAdapter, LangChainAgentAdapter
from attest.adapters.base import StreamChunk


# ---------------------------------------------------------------------------
# Default fallback: non-streaming adapters still stream as one chunk
# ---------------------------------------------------------------------------
async def test_default_stream_yields_final_chunk():
    adapter = CallableAgentAdapter(fn=lambda message: f"echo: {message}")
    chunks = [c async for c in adapter.send_message_stream("hi")]
    assert chunks[-1].done is True
    text = "".join(c.delta for c in chunks)
    assert text == "echo: hi"


async def test_collect_stream_aggregates_to_response():
    adapter = CallableAgentAdapter(fn=lambda message: "hello world")
    response = await adapter.collect_stream("hi")
    assert response.content == "hello world"
    assert response.time_to_first_token_ms is not None
    assert response.latency_ms >= 0


# ---------------------------------------------------------------------------
# Real streaming via LangChain astream
# ---------------------------------------------------------------------------
class _StreamingRunnable:
    """Mimics a LangChain runnable that streams string pieces via astream."""

    async def ainvoke(self, payload):
        return {"output": "the full answer"}

    async def astream(self, payload):
        for piece in ["the ", "full ", "answer"]:
            yield {"output": piece}


async def test_langchain_real_streaming():
    adapter = LangChainAgentAdapter(_StreamingRunnable())
    chunks = [c async for c in adapter.send_message_stream("q")]
    text = "".join(c.delta for c in chunks)
    assert text == "the full answer"
    assert chunks[-1].done is True


async def test_langchain_capabilities_report_streaming():
    adapter = LangChainAgentAdapter(_StreamingRunnable())
    caps = await adapter.get_capabilities()
    assert caps.supports_streaming is True


async def test_collect_stream_via_langchain():
    adapter = LangChainAgentAdapter(_StreamingRunnable())
    response = await adapter.collect_stream("q")
    assert response.content == "the full answer"


def test_stream_chunk_defaults():
    c = StreamChunk()
    assert c.delta == ""
    assert c.done is False
    assert c.tool_call is None
