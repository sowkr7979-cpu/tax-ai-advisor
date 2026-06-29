"""Cluster F — 질의 · 독립답변 · 종합 (docs/04 §1-F, §4, §6).

3-source model: AnswerRun → up to 3 SourceAnswer (LAW_MCP/INTERNAL_RAG/WEB,
unique per run) → SynthesisOpinion reconciles at claim level and INHERITS
citations (creates none of its own).

Invariants enforced here:
  ② Citation points at EXACTLY ONE version source object (XOR), never a raw URL.
  ③ Citation carries an ApplicableBasis (temporal validity).
  RetrievedEvidence normalizes to exactly one source (Chunk|ProvisionVersion|Snapshot).
"""

from __future__ import annotations

from typing import Optional

from pydantic import Field, model_validator

from .base import (
    AlignmentStatus,
    ApplicableBasis,
    ClientScopedModel,
    SourceAnswerStatus,
    SourceKind,
    SourceType,
    TIWModel,
    utc_now,
)
from datetime import datetime


class Question(ClientScopedModel):
    question_id: str
    matter_id: str = Field(..., min_length=1)
    text: str


class AnswerRun(ClientScopedModel):
    answer_run_id: str
    question_id: str
    policy_version: str = "v1"
    risk_tier: Optional[str] = None  # triage
    sources_planned: list[SourceType] = Field(default_factory=list)


class RetrievalRun(ClientScopedModel):
    """Reproducibility record (SEC-007 / RAG-013): exact filters + selected chunks."""

    run_id: str
    source_answer_id: str
    subqueries: list[str] = Field(default_factory=list)
    # filters MUST include the tenant scope — see src.retrieval (SEC-002).
    filters: dict = Field(default_factory=dict)
    candidate_chunk_ids: list[str] = Field(default_factory=list)
    selected_chunk_ids: list[str] = Field(default_factory=list)


class RetrievedEvidence(TIWModel):
    """Normalized: exactly ONE source object (no orphan evidence) — docs/04 §6."""

    evidence_id: str
    chunk_id: Optional[str] = None
    provision_version_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    score: Optional[float] = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "RetrievedEvidence":
        present = [
            x for x in (self.chunk_id, self.provision_version_id, self.snapshot_id) if x
        ]
        if len(present) != 1:
            raise ValueError(
                "RetrievedEvidence must reference exactly one source object "
                "(chunk|provision_version|snapshot)"
            )
        return self


class EvidenceBundle(TIWModel):
    bundle_id: str
    retrieval_run_id: str
    evidence_ids: list[str] = Field(default_factory=list)


class Citation(TIWModel):
    """Invariant ②+③ enforced. A citation belongs to a SourceAnswer (not synthesis),
    points at exactly one version source object via (source_kind, source_object_id),
    and carries an applicable_basis.

    # HALU-003 인용=버전객체 (XOR) · PROV-012 시점 유효성
    NOTE: there is intentionally NO `url` field — raw URLs live only inside a
    SourceSnapshot object that this citation may point at.
    """

    citation_id: str
    source_answer_id: str
    source_kind: SourceKind
    source_object_id: str = Field(..., min_length=1)
    claim_span: Optional[str] = None
    source_locator: Optional[str] = None  # pinpoint 조·항·호·목 / page
    quote: Optional[str] = None
    applicable_basis: ApplicableBasis
    support_type: str = "DIRECT"          # DIRECT|ANALOGOUS|CONTRARY
    authority_rank: Optional[int] = None
    confidence: Optional[float] = None

    @model_validator(mode="after")
    def _version_object_only(self) -> "Citation":
        # (source_kind, source_object_id) must resolve to a version object; the
        # required min_length=1 already blocks empty ids. Reject anything that
        # looks like a bare URL smuggled into source_object_id.
        if "://" in self.source_object_id:
            raise ValueError(
                "HALU-003: Citation must reference a version source-object id, not a raw URL "
                "(wrap the URL in a SourceSnapshot and cite that)"
            )
        return self


class Claim(TIWModel):
    claim_id: str
    source_answer_id: str
    proposition: str
    claim_span: Optional[str] = None
    citation_ids: list[str] = Field(default_factory=list)


class SourceAnswer(ClientScopedModel):
    """A complete answer from EXACTLY ONE channel (docs/04 §4-1)."""

    source_answer_id: str
    answer_run_id: str
    source_type: SourceType
    status: SourceAnswerStatus = SourceAnswerStatus.ANSWERED
    answer_text: str = ""
    version: str = "v1"
    retrieval_run_id: Optional[str] = None


class ConflictResolution(TIWModel):
    resolution_id: str
    inputs: dict = Field(default_factory=dict)  # authority_rank/temporal/fact_match/source_type
    rule_applied: str
    outcome: str  # AUTHORITY|TEMPORAL|FACT_MISMATCH|UNRESOLVED_ABSTAIN
    logged_at: datetime = Field(default_factory=utc_now)


class ClaimAlignment(TIWModel):
    alignment_id: str
    synthesis_id: str
    claim_ids: list[str] = Field(default_factory=list)
    status: AlignmentStatus
    resolution_id: Optional[str] = None


class ConflictFlag(TIWModel):
    flag_id: str
    synthesis_id: str
    claim_alignment_id: str
    sources: list[SourceType] = Field(default_factory=list)
    description: str
    escalated_to_review: bool = False


class ConfidenceScore(TIWModel):
    target_kind: str  # SOURCE_ANSWER|SYNTHESIS
    target_id: str
    retrieval_confidence: Optional[float] = None
    generation_confidence: Optional[float] = None  # separated (HALU-006)
    abstained: bool = False
    reason: Optional[str] = None


class SynthesisOpinion(ClientScopedModel):
    """Reconciles SourceAnswers at claim level. Creates NO new citations —
    inherits source citations (docs/04 §6)."""

    synthesis_id: str
    answer_run_id: str
    source_answer_ids: list[str] = Field(default_factory=list)
    policy_version: str = "v1"
    opinion_text: str = ""
    abstained: bool = False
    authority_deficit: Optional[str] = None
    confidence_cap: Optional[float] = None
