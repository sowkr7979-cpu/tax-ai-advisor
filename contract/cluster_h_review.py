"""Cluster H — 검토 · HITL · 산출 (docs/04 §1-H, §2).

HITL invariant: a FinalMemo (and any 고객 전달본 / ClientDeliverable) MUST be
preceded by an approving ReviewerDecision (H4 for high-risk, H5 for sign-off) —
``ORCH-007`` / ``AGT-008`` / ``OUT-004``. Enforced at construction time so a
non-eval consumer can never materialize an unapproved client deliverable.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field, model_validator

from .base import ClientScopedModel, TIWModel, utc_now
from datetime import datetime


class DraftPackage(ClientScopedModel):
    draft_id: str
    matter_id: str = Field(..., min_length=1)
    answer_run_id: Optional[str] = None
    high_risk: bool = False


class Review(ClientScopedModel):
    review_id: str
    draft_id: str
    reviewer_user_id: str


# --- HITL 게이트 운영계약 (docs/03 §5: H1~H5) ------------------------------ #
class GateType(str, Enum):
    """The five HITL gates (docs/03 §5). Each binds trigger·approver·timeout·
    escalation·audit-record — operationalised in ``src/hitl.py``."""

    H1_INTAKE = "H1"        # 입력 마감 (approver CPA)
    H2_CALC = "H2"          # 계산 플래그 (approver CPA → Reviewer)
    H3_CONFLICT = "H3"      # 충돌/시점 (approver CPA → Reviewer)
    H4_HIGH_RISK = "H4"     # 고위험/적극 절세 (approver Reviewer → Manager)
    H5_APPROVAL = "H5"      # 승인·서명 (approver Reviewer → Manager) → FinalMemo


class ReviewerDecision(ClientScopedModel):
    decision_id: str
    review_id: str
    approved: bool
    reviewer_user_id: str
    decided_at: datetime = Field(default_factory=utc_now)
    escalation: Optional[str] = None
    # additive (slice ⑤): which gate this decision resolves + its outcome.
    gate: Optional[str] = None                 # H1..H5
    outcome: str = "APPROVED"                  # APPROVED|REJECTED|TIMEOUT|ESCALATED


class Correction(ClientScopedModel):
    correction_id: str
    decision_id: str
    note: str


class ReleaseAuthorization(TIWModel):
    """승인 proof — HITL 게이트 충족을 입증하는 값객체 (ORCH-007/AGT-008/OUT-004).

    ``FinalMemo`` / ``ClientDeliverable`` 은 이 proof **없이는 생성 불가**하다(아래
    필수 필드). proof 는 신뢰 워크플로(``src.hitl``)가 *실제 승인된* ``ReviewerDecision``
    으로 구성하며, 생성 시 validator 가:
      (a) 필요한 게이트(저위험 H5 / 고위험 H4+H5)가 모두 ``approved`` 이고,
      (b) 모든 결정의 ``client_id``/``matter_id`` 가 정합(테넌트·스코프 일치)인지
    검증한다 — 아니면 ``ValidationError``. 워크플로의 ``missing_release_gates`` 게이트를
    우회한 직접 생성도 contract 레이어에서 막는 **defense-in-depth**.
    """

    high_risk: bool
    client_id: str = Field(..., min_length=1)
    matter_id: str = Field(..., min_length=1)
    decisions: list[ReviewerDecision] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _verify_release_proof(self) -> "ReleaseAuthorization":
        required = {GateType.H5_APPROVAL.value}
        if self.high_risk:
            required.add(GateType.H4_HIGH_RISK.value)          # 고위험: H4 도 선행
        approved_gates = {d.gate for d in self.decisions if d.approved and d.gate}
        missing = sorted(required - approved_gates)
        if missing:
            raise ValueError(
                f"ORCH-007: 승인 proof에 필수 게이트 승인 누락 {missing} "
                f"(저위험 H5 / 고위험 H4+H5)"
            )
        for d in self.decisions:
            if d.client_id != self.client_id:
                raise ValueError(
                    "SEC-003: 승인 proof의 ReviewerDecision이 다른 client에 속함(교차 테넌트)"
                )
            if d.matter_id is not None and d.matter_id != self.matter_id:
                raise ValueError(
                    "ORCH-007: 승인 proof의 ReviewerDecision이 다른 matter에 속함(스코프 불일치)"
                )
        return self

    @property
    def signoff_decision_id(self) -> str:
        """H5 사인오프 결정의 ``decision_id`` (전달본/최종본 binding 용)."""
        for d in self.decisions:
            if d.gate == GateType.H5_APPROVAL.value and d.approved:
                return d.decision_id
        raise ValueError("ORCH-007: 승인 proof에 H5 사인오프 결정 없음")  # post-validation 도달 불가


def _bind_release_proof(*, proof: ReleaseAuthorization, client_id: str,
                        matter_id: Optional[str], decision_id: str) -> None:
    """proof 가 본 산출물의 테넌트/스코프/사인오프 결정에 묶이는지 검증(binding)."""
    if proof.client_id != client_id:
        raise ValueError("ORCH-007/SEC-003: 승인 proof의 client가 산출물과 불일치")
    if matter_id is not None and proof.matter_id != matter_id:
        raise ValueError("ORCH-007: 승인 proof의 matter가 산출물과 불일치(스코프)")
    if decision_id != proof.signoff_decision_id:
        raise ValueError("ORCH-007: decision_id는 H5 사인오프 결정과 일치해야 한다")


class FinalMemo(ClientScopedModel):
    """# ORCH-007 HITL — 승인 proof(ReleaseAuthorization) 없이 생성 금지."""

    final_memo_id: str
    draft_id: str
    decision_id: str = Field(..., min_length=1)  # approval must precede
    approved: bool
    release_proof: ReleaseAuthorization          # ORCH-007: 승인 proof 필수(우회 불가)

    @model_validator(mode="after")
    def _requires_approval(self) -> "FinalMemo":
        if not self.approved:
            raise ValueError(
                "ORCH-007: FinalMemo requires an approving ReviewerDecision (HITL gate)"
            )
        _bind_release_proof(
            proof=self.release_proof, client_id=self.client_id,
            matter_id=self.matter_id, decision_id=self.decision_id,
        )
        return self


class ClientDeliverable(ClientScopedModel):
    """고객 전달본 (OUT-004: 내부 메모와 분리). H4/H5 승인 없이는 생성 불가
    (AGT-008/OUT-004) — FinalMemo 와 동일한 승인 proof 선행 불변식 + 내부 전략리스크 제외."""

    deliverable_id: str
    draft_id: str
    decision_id: str = Field(..., min_length=1)  # approval must precede
    approved: bool
    excludes_internal_strategy: bool = True      # OUT-004: 내부 전략리스크 비포함
    release_proof: ReleaseAuthorization          # AGT-008/OUT-004: 승인 proof 필수(우회 불가)

    @model_validator(mode="after")
    def _requires_approval(self) -> "ClientDeliverable":
        if not self.approved:
            raise ValueError(
                "AGT-008/OUT-004: 고객 전달본은 승인된 ReviewerDecision 없이 생성 불가"
            )
        if not self.excludes_internal_strategy:
            raise ValueError(
                "OUT-004: 고객 전달본은 내부 전략리스크/내부 메모를 제외해야 한다"
            )
        _bind_release_proof(
            proof=self.release_proof, client_id=self.client_id,
            matter_id=self.matter_id, decision_id=self.decision_id,
        )
        return self


# --- HALU-008 회계사 검토항목 자동생성 ------------------------------------- #
class ReviewItemCategory(str, Enum):
    """Auto-derived reviewer check-item kinds (docs/08 §7, HALU-008)."""

    UNCERTAIN = "UNCERTAIN"                    # 불확실 결론 (되물음 필요)
    INTERPRETATION = "INTERPRETATION"         # 해석 판단 (사실인정·법적평가)
    UNRESOLVED_CONFLICT = "UNRESOLVED_CONFLICT"  # 미해소 소스 충돌
    HIGH_RISK_AGGRESSIVE = "HIGH_RISK_AGGRESSIVE"  # 고위험/적극 절세 (검토경고 필수)
    DATA_LIMIT = "DATA_LIMIT"                 # 자료 한계/에이전트 장애 누락
    WEAK_BASIS = "WEAK_BASIS"                 # 근거 약한 주장
    TEMPORAL_ASSUMPTION = "TEMPORAL_ASSUMPTION"  # 시점 가정


class ReviewItem(ClientScopedModel):
    """One auto-generated reviewer check item (HALU-008). A high-risk/aggressive
    item MUST carry the review warning (``requires_warning``) — its absence on a
    high-risk answer trips MISSING_REVIEW_WARNING (HALU-009, cap 60)."""

    item_id: str
    category: ReviewItemCategory
    description: str
    gate: Optional[str] = None                # which HITL gate this feeds (H1..H5)
    severity: str = "MEDIUM"                   # LOW|MEDIUM|HIGH
    requires_warning: bool = False             # HALU-009 review-warning carrier
    source_ref: Optional[str] = None           # claim/citation/answer reference


class ReviewHistory(ClientScopedModel):
    """Tamper-evident HITL event log (SEC-017). Hash-chained in ``src/hitl.py``:
    each entry pins ``prev_hash`` so a deleted/edited transition breaks the chain."""

    history_id: str
    matter_id: str = Field(..., min_length=1)
    event: str
    # additive (slice ⑤): hash-chain + provenance for tamper-evidence.
    seq: int = 0
    actor: Optional[str] = None
    gate: Optional[str] = None
    prev_hash: Optional[str] = None
    entry_hash: Optional[str] = None


class TaxMemory(ClientScopedModel):
    """거래처별 재활용 지식 — client-scoped (never crosses tenant boundary)."""

    memory_id: str
    topic: str
    content: str
