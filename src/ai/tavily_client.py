"""src/ai/tavily_client.py — Tavily web-search adapter (docs/06, WEB-)."""

from __future__ import annotations

from .base import AdapterConfigError


class TavilyClient:
    """# TODO(WEB-002/003): wire Tavily. Official-source bias + record SourceSnapshot.
    # Key from env (TAVILY_API_KEY). Not used by slice ⑥.
    """

    def __init__(self, api_key_env: str = "TAVILY_API_KEY") -> None:
        self.api_key_env = api_key_env

    def search(self, query: str, max_results: int = 5):  # pragma: no cover - real wiring
        raise AdapterConfigError("TavilyClient is not wired (slice ③ TODO).")
