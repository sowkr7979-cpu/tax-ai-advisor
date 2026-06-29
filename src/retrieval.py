"""src/retrieval.py — IsolatedRetriever (slice ⑥). docs/04 §4-1 (RetrievalRun),
SEC-002 (mandatory tenant filter), RAG-013/SEC-007 (reproducibility).

The retriever returns hits EXACTLY as the store yields them — it adds no masking
filter that could hide a leak. Isolation is the store's structural job; this layer
records the filter used (incl. tenant_scope) for reproducibility and computes the
leakage metric the harness scores.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from contract.base import IndexScope
from contract.cluster_f_qa import RetrievalRun
from src.isolation import TenantScope
from src.vector_store import DeterministicVectorStore, ScoredItem


@dataclass
class RetrievedHit:
    doc_id: str
    owner_client_id: Optional[str]   # None = SHARED reference knowledge
    scope: IndexScope
    score: float

    @property
    def is_shared(self) -> bool:
        return self.scope is IndexScope.SHARED


class IsolatedRetriever:
    """SEC-002: `retrieve` requires a TenantScope. There is no code path that
    retrieves without one — the filter is part of the call signature."""

    def __init__(self, store: DeterministicVectorStore) -> None:
        self._store = store

    def retrieve(
        self, scope: TenantScope, query: str, top_k: int = 5
    ) -> list[RetrievedHit]:
        # SEC-002 격리필터 비활성 불가 — scope는 필수 인자
        scored: list[ScoredItem] = self._store.search(scope, query, top_k=top_k)
        return [
            RetrievedHit(
                doc_id=s.item_id,
                owner_client_id=s.owner_client_id,
                scope=s.scope,
                score=s.score,
            )
            for s in scored
        ]

    def retrieve_with_run(
        self, scope: TenantScope, run_id: str, source_answer_id: str, query: str, top_k: int = 5
    ) -> tuple[list[RetrievedHit], RetrievalRun]:
        """Same as retrieve() but also builds the reproducibility record
        (RetrievalRun) with the tenant filter pinned (SEC-007 / RAG-013)."""
        hits = self.retrieve(scope, query, top_k=top_k)
        run = RetrievalRun(
            run_id=run_id,
            source_answer_id=source_answer_id,
            client_id=scope.client_id,           # isolation key propagated
            subqueries=[query],
            filters={
                "tenant_scope": scope.client_id,  # SEC-002: filter recorded, always present
                "include_shared": scope.include_shared,
                "top_k": top_k,
            },
            candidate_chunk_ids=[h.doc_id for h in hits],
            selected_chunk_ids=[h.doc_id for h in hits],
        )
        return hits, run


def count_cross_tenant_leakage(
    scope: TenantScope, hits: list[RetrievedHit], forbidden_doc_ids: Optional[list[str]] = None
) -> int:
    """Pure leakage metric used by the harness/scorer.

    A hit leaks iff it is owned by a DIFFERENT client than the query scope (SHARED
    is allowed). Any hit whose id is in `forbidden_doc_ids` also counts as a leak.
    # SEC-003 누수=교차회수 건수 > 0 → 하드게이트
    """
    forbidden = set(forbidden_doc_ids or [])
    leaks = 0
    for h in hits:
        if h.owner_client_id is not None and h.owner_client_id != scope.client_id:
            leaks += 1
        elif h.doc_id in forbidden:
            leaks += 1
    return leaks
