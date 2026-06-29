"""Cluster I — 평가 (docs/04 §1-I, §5; docs/09 rubric).

The RubricResult is what `python -m tiw.eval` produces and PROMPT.md §5 reads to
decide completion. Hard-gate flags cap the total deterministically (docs/09 §2).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field

from .base import TIWModel


class Visibility(str, Enum):
    HIDDEN = "HIDDEN"   # frozen freeze-set — NOT read by implementation code
    PUBLIC = "PUBLIC"   # rotating practice set


class TargetKind(str, Enum):
    SOURCE_ANSWER = "SOURCE_ANSWER"
    SYNTHESIS = "SYNTHESIS"
    SLICE = "SLICE"            # infrastructure slice (e.g. ⑥ isolation)


class Score(TIWModel):
    """One rubric dimension (docs/09 §3). Dimension partial score is 0/25/50/75/100."""

    dimension: str
    weight: int
    score: Optional[float] = None     # 0..100 (None = N/A for this slice)
    applicable: bool = True
    detail: Optional[str] = None


class FailureMode(TIWModel):
    """A hard-gate hit (docs/09 §2) or a soft failure note."""

    code: str                  # e.g. SEC-003-LEAK
    description: str
    hard_gate: bool = False
    cap: Optional[int] = None  # score ceiling imposed when hard_gate is True


class RubricResult(TIWModel):
    """Per-case / per-slice score (docs/04 §5)."""

    case_id: str
    slice: int
    target_kind: TargetKind
    target_id: str
    visibility: Visibility = Visibility.PUBLIC
    dimension_scores: list[Score] = Field(default_factory=list)
    failure_modes: list[FailureMode] = Field(default_factory=list)
    cap: Optional[int] = None       # tightest hard-gate cap applied (None = no cap)
    raw_total: float = 0.0          # weighted, renormalized over applicable dims
    total: float = 0.0              # raw_total after applying cap
    metrics: dict = Field(default_factory=dict)  # leakage_count, recall, etc.

    @property
    def hard_gate_hit(self) -> bool:
        return any(f.hard_gate for f in self.failure_modes)


# --- gold-set case schema (tests/golden/*) ------------------------------- #
class CorpusDoc(TIWModel):
    doc_id: str
    confidentiality_level: str
    client_id: Optional[str] = None
    text: str
    chunk_type: str = "재무"
    expect_reject: bool = False   # SEC-001 negative ingestion case


class GoldQuery(TIWModel):
    query_id: str
    as_client: str
    text: str
    gold_doc_ids: list[str] = Field(default_factory=list)      # intra-tenant recall
    forbidden_doc_ids: list[str] = Field(default_factory=list)  # leakage set (must be 0)
    expect_shared: list[str] = Field(default_factory=list)     # SHARED docs allowed


class EvaluationCase(TIWModel):
    case_id: str
    slice: int
    visibility: Visibility
    adversarial: bool = False
    description: str = ""
    corpus: list[CorpusDoc] = Field(default_factory=list)
    queries: list[GoldQuery] = Field(default_factory=list)
    top_k: int = 5
