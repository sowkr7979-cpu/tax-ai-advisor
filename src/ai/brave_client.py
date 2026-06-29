"""src/ai/brave_client.py — Brave web-search adapter (docs/06, WEB-)."""

from __future__ import annotations

from .base import AdapterConfigError


class BraveClient:
    """# TODO(WEB-002/004): wire Brave Search as a second web source.
    # Key from env (BRAVE_API_KEY). Not used by slice ⑥.
    """

    def __init__(self, api_key_env: str = "BRAVE_API_KEY") -> None:
        self.api_key_env = api_key_env

    def search(self, query: str, max_results: int = 5):  # pragma: no cover - real wiring
        raise AdapterConfigError("BraveClient is not wired (slice ③ TODO).")
