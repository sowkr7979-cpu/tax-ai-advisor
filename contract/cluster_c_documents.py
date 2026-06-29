"""Cluster C — 문서 · RAG (docs/04 §1-C, §3, §3-1).

This is the cluster that slice ⑥ (tenant isolation) is built on.

Enforced here at construction time:
  - SEC-001/SEC-004: a client-identifying chunk (L3/L4) MUST carry client_id;
    a SHARED reference chunk (L0/L1/L2) MUST NOT carry one.
  - SEC-003/RAG-007: VectorIndex.scope SHARED ⟂ TENANT — a TENANT index is bound
    to exactly one client_id; a SHARED index has none.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import Field, model_validator

from .base import ConfidentialityLevel, IndexScope, TIWModel


class SourceLicense(TIWModel):
    """Proof a source is allowed to be ingested (SEC-004 hard gate input)."""

    license_id: str
    kind: str          # PUBLIC|LICENSED_PUBLICATION|SYNTHETIC|INTERNAL_PLAYBOOK|CLIENT_ENGAGEMENT
    holder: Optional[str] = None
    terms: Optional[str] = None


class RetentionPolicy(TIWModel):
    policy_id: str
    retention_days: int
    legal_hold: bool = False


class Document(TIWModel):
    document_id: str
    title: str
    confidentiality_level: ConfidentialityLevel
    client_id: Optional[str] = None
    license_id: Optional[str] = None
    retention_policy_id: Optional[str] = None

    @model_validator(mode="after")
    def _isolation_and_license(self) -> "Document":
        if self.confidentiality_level.is_client_scoped:
            # SEC-001 격리키 전파 — 고객자료는 client_id 필수
            if not self.client_id or not self.client_id.strip():
                raise ValueError(
                    "SEC-001: client-scoped document (L3/L4) requires a non-empty client_id"
                )
        else:
            # Shared reference knowledge must NOT smuggle a client key.
            if self.client_id:
                raise ValueError(
                    "SEC-003: shared (L0/L1/L2) document must not carry a client_id"
                )
        return self


class DocumentVersion(TIWModel):
    document_version_id: str
    document_id: str
    version: int
    content_hash: str


class Chunk(TIWModel):
    """A retrievable unit. The isolation key + confidentiality drive which index
    it may enter (see src.isolation.classify_target_scope)."""

    chunk_id: str
    document_version_id: str
    chunk_text: str
    chunk_type: str                      # 법령/예규/판례/메모/실무서/계약/재무
    source_locator: Optional[str] = None  # 조·항·호·목 / page / paragraph
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    tax_type: Optional[str] = None
    fiscal_year: Optional[int] = None
    confidentiality_level: ConfidentialityLevel
    client_id: Optional[str] = None       # NULL only for SHARED (L0/L1/L2)
    license_id: Optional[str] = None
    content_hash: Optional[str] = None

    @model_validator(mode="after")
    def _isolation_key(self) -> "Chunk":
        if self.confidentiality_level.is_client_scoped:
            # SEC-001 격리필터의 전제: 고객 chunk에 client_id 없으면 적재 거부
            if not self.client_id or not self.client_id.strip():
                raise ValueError(
                    "SEC-001: client-scoped chunk (L3/L4) requires a non-empty client_id"
                )
        else:
            if self.client_id:
                raise ValueError(
                    "SEC-003: shared chunk (L0/L1/L2) must not carry a client_id"
                )
        return self


class EmbeddingModel(TIWModel):
    model_name: str
    dimension: int
    multilingual: bool = True


class VectorIndex(TIWModel):
    """SHARED ⟂ TENANT physical separation (SEC-003 / RAG-007)."""

    index_id: str
    scope: IndexScope
    client_id: Optional[str] = None   # set iff scope == TENANT
    embedding_model: str
    version: str = "v1"

    @model_validator(mode="after")
    def _scope_key_consistency(self) -> "VectorIndex":
        if self.scope is IndexScope.TENANT:
            if not self.client_id or not self.client_id.strip():
                raise ValueError("SEC-003: TENANT index requires a client_id")
        else:  # SHARED
            if self.client_id:
                raise ValueError("SEC-003: SHARED index must not carry a client_id")
        return self


class Embedding(TIWModel):
    embedding_id: str
    chunk_id: str
    model_name: str
    dimension: int
    index_id: str
    # vector data itself is runtime storage (not committed source); kept optional here
    vector: Optional[list[float]] = None
