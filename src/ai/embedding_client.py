"""src/ai/embedding_client.py — embedding adapter (docs/07 API; RAG embeddings).

DeterministicFakeEmbedder: a hash-based bag-of-words embedder. It needs NO API key
and is fully deterministic, so the slice-⑥ isolation harness can verify the
ISOLATION logic (which docs go in which index, which are retrievable) without
depending on any real embedding provider.

The real multilingual/Korean embedder is wired behind RealEmbeddingClient (TODO).
"""

from __future__ import annotations

import math
import re
from typing import Optional

from .base import AdapterConfigError, Embedder

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)  # \w includes Hangul under re.UNICODE


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


class DeterministicFakeEmbedder:
    """Hashing bag-of-words → fixed-dim L2-normalized vector.

    Deterministic across runs/processes (uses a stable hash, not Python's salted
    hash). Two texts that share tokens get higher cosine similarity — enough to
    exercise retrieval/recall in the isolation harness without a real model.
    """

    model_name = "fake-deterministic-bow-v1"

    def __init__(self, dimension: int = 256) -> None:
        self.dimension = dimension

    @staticmethod
    def _stable_hash(token: str) -> int:
        # FNV-1a (stable, unsalted) — reproducible across processes.
        h = 0x811C9DC5
        for ch in token.encode("utf-8"):
            h ^= ch
            h = (h * 0x01000193) & 0xFFFFFFFF
        return h

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        for tok in _tokenize(text):
            idx = self._stable_hash(tok) % self.dimension
            sign = 1.0 if (self._stable_hash(tok + "#sign") & 1) else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]


class RealEmbeddingClient:
    """Multilingual/Korean embedding client — real wiring point.

    # TODO(API-embedding): wire a real embedder (model + endpoint from
    # infra/config/vendors.yaml). MUST honor docs/01 §8 non-training / masking
    # before sending any L3/L4 content. Not used by deterministic tests.
    """

    def __init__(self, model_name: Optional[str] = None, dimension: int = 1024) -> None:
        self.model_name = model_name or "TODO-multilingual-embedder"
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:  # pragma: no cover - real wiring
        raise AdapterConfigError(
            "RealEmbeddingClient is not wired. Use DeterministicFakeEmbedder for "
            "tests, or configure infra/config/vendors.yaml + provide credentials."
        )


def default_embedder() -> Embedder:
    """Hermetic default for the harness."""
    return DeterministicFakeEmbedder()
