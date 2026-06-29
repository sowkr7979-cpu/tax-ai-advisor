"""src/ai/korean_law_mcp_client.py — Korean-law MCP adapter (docs/07, API-002/003/004).

Anchors answers to ProvisionVersion objects (slice ①). Real responses are recorded
as SourceSnapshot fixtures for deterministic replay (PROMPT.md §0).
"""

from __future__ import annotations

from .base import AdapterConfigError


class KoreanLawMCPClient:
    """# TODO(API-002/003/004): wire Korean-law MCP. Return version-pinned
    # ProvisionVersion + SourceSnapshot; record responses to tests/fixtures/.
    # LawDataSource fallback per API-004. Not used by slice ⑥.
    """

    def __init__(self, endpoint: str | None = None) -> None:
        self.endpoint = endpoint

    def lookup_provision(self, query: str, as_of):  # pragma: no cover - real wiring
        raise AdapterConfigError("KoreanLawMCPClient is not wired (slice ① TODO).")
