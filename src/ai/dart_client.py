"""src/ai/dart_client.py — DART (전자공시) adapter (docs/07, API-)."""

from __future__ import annotations

from .base import AdapterConfigError


class DartClient:
    """# TODO(API-DART): wire DART OpenAPI for public-company filings.
    # Key from env (DART_API_KEY). Not used by slice ⑥.
    """

    def __init__(self, api_key_env: str = "DART_API_KEY") -> None:
        self.api_key_env = api_key_env

    def fetch_filing(self, corp_code: str, report_type: str):  # pragma: no cover
        raise AdapterConfigError("DartClient is not wired.")
