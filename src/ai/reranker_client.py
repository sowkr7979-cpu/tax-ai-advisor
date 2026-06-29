"""src/ai/reranker_client.py — reranker adapter (docs/05 hybrid retrieval, RAG)."""

from __future__ import annotations

from .base import AdapterConfigError


class RerankerClient:
    """Cross-encoder reranker.

    # TODO(RAG-rerank): wire a real reranker (model from infra/config). Used to
    # reorder hybrid candidates; not required for slice ⑥ isolation tests.
    """

    def __init__(self, model_name: str = "TODO-reranker") -> None:
        self.model_name = model_name

    def rerank(self, query: str, candidates: list[str]) -> list[int]:  # pragma: no cover
        raise AdapterConfigError("RerankerClient is not wired.")
