"""src/ai/ocr_client.py — OCR adapter for scanned/HWP/PDF intake (docs/07, INTK-)."""

from __future__ import annotations

from .base import AdapterConfigError


class OcrClient:
    """# TODO(API-OCR): wire OCR (PDF/HWP/image → text). Output feeds RAG ingestion
    # which still applies SEC-001/SEC-004 license + isolation gates. Not used by slice ⑥.
    """

    def __init__(self, provider: str = "TODO-ocr") -> None:
        self.provider = provider

    def extract_text(self, file_bytes: bytes) -> str:  # pragma: no cover - real wiring
        raise AdapterConfigError("OcrClient is not wired.")
