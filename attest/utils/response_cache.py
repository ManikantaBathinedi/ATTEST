"""Response cache — avoid re-querying agents for identical inputs.

When `evaluation.cost.cache_responses` is True in attest.yaml, the runner
will check this cache before sending a message to the agent. Identical
inputs (same agent + same message + same conversation history) return
the cached response instantly.

This saves both time and money when:
- Re-running the same suite after changing evaluators/assertions
- Debugging evaluator thresholds without hitting the agent again
- Running overlapping test suites

Cache is in-memory (per run) by default. No disk persistence — each
`attest run` starts fresh.
"""

from __future__ import annotations

import hashlib
import json
from typing import Dict, List, Optional

from attest.core.models import AgentResponse, Message


class ResponseCache:
    """In-memory cache for agent responses, keyed by (agent, input, history)."""

    def __init__(self):
        self._cache: Dict[str, AgentResponse] = {}
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _make_key(agent: str, message: str, history: Optional[List[Message]] = None) -> str:
        """Create a deterministic cache key from the request."""
        parts = {
            "agent": agent,
            "message": message,
            "history": [
                {"role": m.role, "content": m.content}
                for m in (history or [])
            ],
        }
        raw = json.dumps(parts, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, agent: str, message: str, history: Optional[List[Message]] = None) -> Optional[AgentResponse]:
        """Look up a cached response. Returns None on miss."""
        key = self._make_key(agent, message, history)
        result = self._cache.get(key)
        if result is not None:
            self._hits += 1
        else:
            self._misses += 1
        return result

    def put(self, agent: str, message: str, response: AgentResponse, history: Optional[List[Message]] = None) -> None:
        """Store a response in the cache."""
        key = self._make_key(agent, message, history)
        self._cache[key] = response

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    @property
    def size(self) -> int:
        return len(self._cache)

    def clear(self) -> None:
        """Clear all cached responses."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0
