"""Cluster I — 평가 (docs/04 §1-I, §5; docs/09 rubric).

The RubricResult is what `python -m tiw.eval` produces and PROMPT.md §5 reads to
decide completion. Hard-gate flags cap the total deterministically (docs/09 §2).
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import Field, computed_field

from .base import BasisKind, TIWModel


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
    # PENDING_JUDGE (docs/09 §7): dimensions that this slice WOULD exercise but
    # that require the LLM-judge / human-CPA pass which is not yet wired. They are
    # NEITHER scored full (anti-gaming) NOR treated as N/A — they are EXPLICITLY
    # withheld. A slice carrying pending dimensions can never be reported as a
    # ≥90 completion (runner forces passed=False). These names do NOT enter the
    # weighted total (raw_total/total are computed only over scored dims).
    pending_dimensions: list[str] = Field(default_factory=list)

    @property
    def hard_gate_hit(self) -> bool:
        return any(f.hard_gate for f in self.failure_modes)

    @property
    def has_pending(self) -> bool:
        return bool(self.pending_dimensions)

    # Headline separation (codex P2-B). `total` is the weighted mean over the
    # SCORED (deterministic) dimensions after caps — when this case has any
    # PENDING_JUDGE dimension that is a SUBTOTAL, not a completion score. These
    # serialized fields make the distinction explicit so a programmatic reader of
    # the result cannot mistake the judge-free subtotal for a ≥90 completion.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def deterministic_subtotal(self) -> float:
        """Judge-free weighted subtotal (== ``total``)."""
        return self.total

    @computed_field  # type: ignore[prop-decorator]
    @property
    def completion_score(self) -> Optional[float]:
        """Completion headline — ``None`` while any dimension is PENDING_JUDGE
        (the case is INCOMPLETE, so there is no completion score to report)."""
        return None if self.has_pending else self.total


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


# --- slice ① law-anchor gold schema (API-002/003/004, PROV-003/012) ------ #
class LawAnchorGoldCitation(TIWModel):
    """The version-pinned provision a slice-① answer MUST anchor to.

    Deterministic checks compare the resolved ProvisionVersion against these
    fields (gold). `title_contains` catches stale-version retrieval (e.g. the
    pre-2022 '접대비' text when the as-of-date demands '기업업무추진비')."""

    law_name: str                       # 법인세법
    source_type: str = "법률"           # 법률|시행령|시행규칙|...
    article_label: str                  # 제25조
    expected_effective_from: date       # the version's 시행일 (PROV-012)
    title_contains: str                 # substring the 조문제목/본문 must contain
    expected_promulgated_date: Optional[date] = None


class LawAnchorQuery(TIWModel):
    """One slice-① question: 'which provision, as-of which date'."""

    query_id: str
    question_text: str
    law_name: str
    article_label: str
    basis_kind: BasisKind = BasisKind.FISCAL_YEAR
    as_of_date: date                    # selects the 시행일 version (API-003)
    high_risk: bool = False             # if True, answer must carry a review warning
    gold: list[LawAnchorGoldCitation] = Field(default_factory=list)


class EvaluationCase(TIWModel):
    case_id: str
    slice: int
    visibility: Visibility
    adversarial: bool = False
    description: str = ""
    corpus: list[CorpusDoc] = Field(default_factory=list)
    queries: list[GoldQuery] = Field(default_factory=list)
    top_k: int = 5
    # slice ① only (empty for other slices)
    law_queries: list[LawAnchorQuery] = Field(default_factory=list)
