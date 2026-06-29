"""Cluster H — 검토 · HITL · 산출 (docs/04 §1-H, §2).

HITL invariant: a FinalMemo MUST be preceded by a ReviewerDecision (approval).
"""

from __future__ import annotations

from typing import Optional

from pydantic import Field, model_validator

from .base import ClientScopedModel, utc_now
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


class ReviewerDecision(ClientScopedModel):
    decision_id: str
    review_id: str
    approved: bool
    reviewer_user_id: str
    decided_at: datetime = Field(default_factory=utc_now)
    escalation: Optional[str] = None


class Correction(ClientScopedModel):
    correction_id: str
    decision_id: str
    note: str


class FinalMemo(ClientScopedModel):
    """# ORCH-007 HITL — 승인(ReviewerDecision) 없이 생성 금지."""

    final_memo_id: str
    draft_id: str
    decision_id: str = Field(..., min_length=1)  # approval must precede
    approved: bool

    @model_validator(mode="after")
    def _requires_approval(self) -> "FinalMemo":
        if not self.approved:
            raise ValueError(
                "ORCH-007: FinalMemo requires an approving ReviewerDecision (HITL gate)"
            )
        return self


class ReviewHistory(ClientScopedModel):
    history_id: str
    matter_id: str = Field(..., min_length=1)
    event: str


class TaxMemory(ClientScopedModel):
    """거래처별 재활용 지식 — client-scoped (never crosses tenant boundary)."""

    memory_id: str
    topic: str
    content: str
