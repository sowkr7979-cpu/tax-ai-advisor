"""src/isolation.py — deterministic tenant-isolation rules (slice ⑥).

Implements the structural guarantees from docs/01 §4:
  - SEC-001: NULL isolation key on client material → load REJECTED.
  - SEC-002: retrieval requires a TenantScope (filter cannot be omitted/disabled).
  - SEC-003/RAG-007: client material → TENANT index; reference knowledge → SHARED.

This module is pure (no I/O, no vendor SDK). The adapter (src/ai/chroma_backend.py)
must preserve the SAME contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from contract.base import ConfidentialityLevel, IndexScope
from contract.cluster_c_documents import Chunk


class IsolationError(RuntimeError):
    """Raised when an isolation invariant would be violated (fail-closed)."""


@dataclass(frozen=True)
class TenantScope:
    """The MANDATORY retrieval scope. SEC-002: a query cannot run without one.

    `client_id` is required and non-empty — a blank scope is rejected here, so a
    caller can never accidentally widen the boundary by passing an empty filter.
    """

    client_id: str
    include_shared: bool = True  # SHARED reference knowledge is read-allowed cross-client

    def __post_init__(self) -> None:
        # SEC-002 격리필터 비활성 불가 — 빈 스코프 거부
        if not self.client_id or not self.client_id.strip():
            raise IsolationError("SEC-002: TenantScope.client_id must be a non-empty isolation key")


@dataclass
class IngestTarget:
    scope: IndexScope
    client_id: Optional[str]


def classify_target_scope(
    confidentiality_level: ConfidentialityLevel, client_id: Optional[str]
) -> IngestTarget:
    """Decide which index a unit belongs to (SEC-003 SHARED ⟂ TENANT).

    Client-identifying material (L3/L4) MUST carry a client_id and goes to that
    client's TENANT partition. Reference knowledge (L0/L1/L2) goes to SHARED and
    must NOT carry a client_id.
    """
    if confidentiality_level.is_client_scoped:
        if not client_id or not client_id.strip():
            # SEC-001 NULL 격리키 적재 거부
            raise IsolationError(
                f"SEC-001: client-scoped material ({confidentiality_level.value}) "
                "requires a non-empty client_id — load rejected"
            )
        return IngestTarget(scope=IndexScope.TENANT, client_id=client_id)
    # reference knowledge
    if client_id:
        # SEC-003: shared reference must not be tagged to a tenant
        raise IsolationError(
            f"SEC-003: shared material ({confidentiality_level.value}) must not carry a client_id"
        )
    return IngestTarget(scope=IndexScope.SHARED, client_id=None)


def assert_ingestable(chunk: Chunk) -> IngestTarget:
    """Gate a Chunk before it enters any index. Re-derives the target scope and
    raises IsolationError if the isolation key is missing/inconsistent."""
    return classify_target_scope(chunk.confidentiality_level, chunk.client_id)
