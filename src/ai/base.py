"""src/ai/base.py — adapter layer contracts (docs/README §2 boundary rule).

src/ai/ holds CLIENTS ONLY (LLM/embedding/reranker/MCP/web/OCR/DART/DOCX). It must
not contain RAG orchestration or isolation logic — those live in src/ (deterministic).

Every adapter exposes a real-wiring point (TODO) but ships a deterministic
fallback so the slice-⑥ harness runs hermetically with NO API keys.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class AdapterConfigError(RuntimeError):
    """Raised when a real adapter is invoked without required vendor config."""


@runtime_checkable
class Embedder(Protocol):
    """Embedding client contract. Implementations: DeterministicFakeEmbedder (tests)
    and (TODO) a real multilingual/Korean embedder behind infra/config."""

    dimension: int
    model_name: str

    def embed(self, text: str) -> list[float]: ...
