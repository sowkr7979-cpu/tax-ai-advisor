"""contract.base — shared enums + invariant base models (ERD §6 횡단 불변식).

This module encodes the THREE invariants from docs/04_ERD §0 at the type/runtime
level (pydantic v2). Every cluster module builds on these.

  ① 격리키 전파 (SEC-001)  — client_id NOT NULL on client-derived records.
  ② 인용=버전객체 (HALU-003) — Citation → ProvisionVersion/Ruling/CasePrecedent/
     SourceSnapshot (XOR), never a raw URL/free string.
  ③ 시점 유효성 (PROV-012) — legal conclusions carry an ApplicableBasis date fact.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator


def _require_non_blank(value: str) -> str:
    """Reject NULL/whitespace-only isolation & scope keys (SEC-001).

    A blank ("   ") key passes a bare ``min_length=1`` yet still defeats the
    tenant filter, so it is refused at construction time — the SAME guard
    ``ClientScopedModel`` applies to ``client_id``, made reusable for the
    cluster-A identity keys (Client/Engagement/Matter/RoleAssignment)."""
    if not value or not value.strip():
        raise ValueError("SEC-001: isolation/scope key must be non-empty (no whitespace-only)")
    return value


# Reusable non-blank string for isolation/scope id fields.
NonBlankStr = Annotated[str, AfterValidator(_require_non_blank)]


class TIWModel(BaseModel):
    """Base for all contract entities. Strict-ish: reject unknown fields so a
    typo'd isolation key (e.g. ``cleint_id``) fails loudly instead of silently
    dropping the tenant boundary."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class ConfidentialityLevel(str, Enum):
    """docs/01 §3 data classification. Ordering matters: >= L3 is client-identifying
    and MUST carry an isolation key + stay inside the tenant boundary."""

    L0_PUBLIC = "L0_PUBLIC"
    L1_LICENSED = "L1_LICENSED"
    L2_INTERNAL = "L2_INTERNAL"
    L3_CLIENT = "L3_CLIENT"
    L4_RESTRICTED = "L4_RESTRICTED"

    @property
    def rank(self) -> int:
        return _CONF_RANK[self]

    @property
    def is_client_scoped(self) -> bool:
        """L3/L4 = client-identifying → tenant partition only (docs/01 §4)."""
        return self.rank >= ConfidentialityLevel.L3_CLIENT.rank


_CONF_RANK = {
    ConfidentialityLevel.L0_PUBLIC: 0,
    ConfidentialityLevel.L1_LICENSED: 1,
    ConfidentialityLevel.L2_INTERNAL: 2,
    ConfidentialityLevel.L3_CLIENT: 3,
    ConfidentialityLevel.L4_RESTRICTED: 4,
}


class IndexScope(str, Enum):
    """VectorIndex.scope — SHARED reference knowledge ⟂ TENANT client material.
    SEC-003 / RAG-007: these are PHYSICALLY separate indexes."""

    SHARED = "SHARED"   # L0/L1/L2 reference knowledge, read-only, no client_id
    TENANT = "TENANT"   # L3/L4 client material, partitioned by client_id


class SourceType(str, Enum):
    """SourceAnswer.source_type — exactly one channel per source answer."""

    LAW_MCP = "LAW_MCP"
    INTERNAL_RAG = "INTERNAL_RAG"
    WEB = "WEB"


class SourceAnswerStatus(str, Enum):
    ANSWERED = "ANSWERED"
    SILENT = "SILENT"
    ERROR = "ERROR"
    BLOCKED = "BLOCKED"


class SourceKind(str, Enum):
    """The four version-pinned source-object kinds a Citation may point at."""

    PROVISION_VERSION = "ProvisionVersion"
    RULING = "Ruling"
    CASE_PRECEDENT = "CasePrecedent"
    SOURCE_SNAPSHOT = "SourceSnapshot"


class AlignmentStatus(str, Enum):
    AGREE = "AGREE"
    CONFLICT = "CONFLICT"
    SILENT = "SILENT"


class BasisKind(str, Enum):
    """Invariant ③: which date fact anchors temporal validity (docs/04 §0)."""

    TRANSACTION_DATE = "TRANSACTION_DATE"
    ACCRUAL_YEAR = "ACCRUAL_YEAR"
    FISCAL_YEAR = "FISCAL_YEAR"
    FILING_DATE = "FILING_DATE"
    ASSESSMENT_DATE = "ASSESSMENT_DATE"
    AMENDED_RETURN_DATE = "AMENDED_RETURN_DATE"
    ADVISORY_DATE = "ADVISORY_DATE"


class ScopeType(str, Enum):
    MATTER = "MATTER"
    ENGAGEMENT = "ENGAGEMENT"


# --------------------------------------------------------------------------- #
# Invariant ① — isolation key propagation (SEC-001)
# --------------------------------------------------------------------------- #
class ClientScopedModel(TIWModel):
    """Base for every client-derived record (clusters A-client/B/F/H + client
    chunks). ``client_id`` is REQUIRED and non-empty — a NULL/blank isolation key
    is rejected at construction time.

    # SEC-001 격리키 전파 — NULL 격리키 적재 거부 (NULL isolation key load rejected)
    """

    client_id: str = Field(..., min_length=1, description="tenant isolation key (NOT NULL)")
    matter_id: Optional[str] = Field(
        default=None, description="narrower scope; required for matter-scoped records"
    )

    @field_validator("client_id")
    @classmethod
    def _client_id_not_blank(cls, v: str) -> str:
        # Guard against whitespace-only keys that would defeat the filter.
        if not v or not v.strip():
            raise ValueError("SEC-001: client_id (isolation key) must be non-empty")
        return v


# --------------------------------------------------------------------------- #
# Invariant ③ — temporal validity anchor (PROV-012)
# --------------------------------------------------------------------------- #
class ApplicableBasis(TIWModel):
    """The date fact that selects the applicable law version (invariant ③).

    # PROV-012 시점 유효성 — 결론은 거래일/귀속/신고일 등 실제 날짜에 묶인다
    """

    basis_kind: BasisKind
    as_of_date: date
    tax_year_id: Optional[str] = None
    matter_id: Optional[str] = None
    fact_pattern_id: Optional[str] = None


def utc_now() -> datetime:
    return datetime.utcnow()
