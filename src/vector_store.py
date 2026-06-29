"""src/vector_store.py — deterministic vector store with PHYSICAL SHARED⟂TENANT
separation (SEC-003 / RAG-007). Pure Python, no vendor SDK.

Isolation is STRUCTURAL, not a query-time flag:
  - each tenant client_id owns its OWN partition (separate dict entry);
  - SHARED reference knowledge lives in a SEPARATE partition;
  - a search for scope A only ever iterates {A's partition} ∪ {SHARED?}.
    B's partition is never touched, so a B document cannot be returned to A.

The Chroma adapter (src/ai/chroma_backend.py) maps these partitions to separate
collections/namespaces and MUST preserve this contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

from contract.base import ConfidentialityLevel, IndexScope
from src.ai.base import Embedder
from src.ai.embedding_client import default_embedder
from src.isolation import IngestTarget, IsolationError, TenantScope, classify_target_scope


@dataclass
class StoredItem:
    item_id: str
    text: str
    scope: IndexScope
    owner_client_id: Optional[str]   # None for SHARED
    vector: list[float]


@dataclass
class ScoredItem:
    item_id: str
    score: float
    scope: IndexScope
    owner_client_id: Optional[str]
    text: str


@runtime_checkable
class VectorStore(Protocol):
    """The isolation-preserving store contract shared by the pure-Python
    ``DeterministicVectorStore`` (slice ⑥) and the Chroma-backed
    ``ChromaVectorStore`` (slice ②). SEC-002: ``search`` REQUIRES a TenantScope —
    there is no overload without one."""

    def search(self, scope: "TenantScope", query: str, top_k: int = 5) -> list[ScoredItem]: ...


def _cosine(a: list[float], b: list[float]) -> float:
    # vectors are L2-normalized by the embedder → dot product == cosine.
    return sum(x * y for x, y in zip(a, b))


class DeterministicVectorStore:
    def __init__(self, embedder: Optional[Embedder] = None) -> None:
        self._embedder = embedder or default_embedder()
        # PHYSICAL separation: one list per tenant + one SHARED list.
        self._tenant_partitions: dict[str, list[StoredItem]] = {}
        self._shared_partition: list[StoredItem] = []

    # -- ingestion -------------------------------------------------------- #
    def add(
        self,
        item_id: str,
        text: str,
        confidentiality_level: ConfidentialityLevel,
        client_id: Optional[str] = None,
    ) -> IngestTarget:
        """Route an item to the correct partition. Raises IsolationError on a
        NULL isolation key for client material (SEC-001)."""
        target = classify_target_scope(confidentiality_level, client_id)
        item = StoredItem(
            item_id=item_id,
            text=text,
            scope=target.scope,
            owner_client_id=target.client_id,
            vector=self._embedder.embed(text),
        )
        if target.scope is IndexScope.TENANT:
            assert target.client_id is not None  # guaranteed by classify
            self._tenant_partitions.setdefault(target.client_id, []).append(item)
        else:
            self._shared_partition.append(item)
        return target

    # -- retrieval -------------------------------------------------------- #
    def _candidate_partitions(self, scope: TenantScope) -> list[list[StoredItem]]:
        """The ONLY partitions a query may see. Overridable ONLY for adversarial
        testing (a leaky override simulates a 'forgotten filter')."""
        partitions: list[list[StoredItem]] = [self._tenant_partitions.get(scope.client_id, [])]
        if scope.include_shared:
            partitions.append(self._shared_partition)
        return partitions

    def search(self, scope: TenantScope, query: str, top_k: int = 5) -> list[ScoredItem]:
        """SEC-002: `scope` is REQUIRED — there is no overload that searches
        without a tenant filter."""
        if not isinstance(scope, TenantScope):  # defensive: cannot bypass the type
            raise IsolationError("SEC-002: search requires a TenantScope (filter cannot be omitted)")
        qv = self._embedder.embed(query)
        scored: list[ScoredItem] = []
        for partition in self._candidate_partitions(scope):
            for item in partition:
                scored.append(
                    ScoredItem(
                        item_id=item.item_id,
                        score=_cosine(qv, item.vector),
                        scope=item.scope,
                        owner_client_id=item.owner_client_id,
                        text=item.text,
                    )
                )
        scored.sort(key=lambda s: (-s.score, s.item_id))
        return scored[:top_k]

    # -- introspection (tests) ------------------------------------------- #
    def tenant_ids(self) -> list[str]:
        return sorted(self._tenant_partitions)

    def shared_count(self) -> int:
        return len(self._shared_partition)
