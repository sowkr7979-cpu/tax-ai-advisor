"""Cluster I — 평가 (docs/04 §1-I, §5; docs/09 rubric).

The RubricResult is what `python -m tiw.eval` produces and PROMPT.md §5 reads to
decide completion. Hard-gate flags cap the total deterministically (docs/09 §2).
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import Field, computed_field

from .base import BasisKind, ScopeType, TIWModel
from .cluster_a_tenancy import RoleName


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
    # gold expected ISSUES for issue-spotting (docs/09 §3 dim 5). Derived
    # INDEPENDENTLY from the law/사실관계 (NOT from any generated answer —
    # anti-gaming). Empty = issue-spotting not gold-anchored for this query.
    gold_issues: list[str] = Field(default_factory=list)


# --- slice ② RAG gold schema (RAG-002/005/007/013/017, HALU-003) --------- #
class RagCorpusDoc(TIWModel):
    """One ingestible unit for the internal-RAG index.

    Two kinds (docs/05 §4 분류 routes the splitter):
      * ``law``    — a SHARED reference 조문. The harness CHUNKS it from the
        committed 법제처 fixture (``effective_year`` picks the 시행일 버전 body),
        so the long statute text is NOT duplicated in the gold JSON. Structure-
        aware chunking (조/항/호/목 + metadata) happens in src.chunking.
      * ``client`` — L3/L4 client material (inline text). Routed to that client's
        TENANT partition (SEC-003); the isolation key is mandatory."""

    doc_id: str
    kind: str = "client"                     # "law" | "client"
    # law-doc fields
    law_name: Optional[str] = None
    article_label: Optional[str] = None
    effective_year: Optional[int] = None     # which 시행일 fixture (2020/2024)
    # client-doc fields
    confidentiality_level: str = "L3_CLIENT"
    client_id: Optional[str] = None
    text: str = ""
    chunk_type: str = "메모"
    tax_type: Optional[str] = None
    expect_reject: bool = False              # SEC-001 NULL-key negative ingestion


class RagQuery(TIWModel):
    """One slice-② internal-RAG question scoped to a tenant + as-of date."""

    query_id: str
    question_text: str
    as_client: str                           # TenantScope (SEC-002, 끌 수 없음)
    as_of_date: date                         # temporal validity filter (RAG-005)
    basis_kind: BasisKind = BasisKind.FISCAL_YEAR
    high_risk: bool = False
    # the version-pinned provision the citation-grounded answer MUST anchor to
    gold_law: LawAnchorGoldCitation
    gold_chunk_ids: list[str] = Field(default_factory=list)      # recall@k targets
    forbidden_chunk_ids: list[str] = Field(default_factory=list)  # leakage set (must be 0)
    expect_shared: list[str] = Field(default_factory=list)       # SHARED chunks allowed
    gold_issues: list[str] = Field(default_factory=list)         # issue-spotting (independent)


# --- slice ③ WEB gold schema (WEB-002/003/004/011/012) ------------------- #
class WebQuery(TIWModel):
    """One slice-③ web-research question.

    Channel ③ DISCOVERS official sources (Tavily, official domains) and PROMOTES
    only those cross-checked against the 법령 원문 (channel ①, version-pinned by
    ``as_of_date``). ``gold_official_domains`` are the official authorities a correct
    run must surface (search recall); ``gold_law`` is the version the promoted
    conclusion must anchor to; ``expect_promote=False`` is the web-단독-단정 adversarial
    (no promotable official source → must abstain)."""

    query_id: str
    question_text: str
    law_name: str
    article_label: str
    issue: str                              # 쟁점 키워드 (query planning + relevance)
    tax_type: str = "법인세"
    basis_kind: BasisKind = BasisKind.FISCAL_YEAR
    as_of_date: date                        # selects the 시행일 version (① cross-check)
    high_risk: bool = False
    gold_law: LawAnchorGoldCitation         # the version the promoted conclusion anchors to
    gold_official_domains: list[str] = Field(default_factory=list)  # official-recall targets
    gold_issues: list[str] = Field(default_factory=list)            # issue-spotting (independent)
    expect_promote: bool = True             # False = must abstain (web-alone 금지)


# --- slice ⑤ HITL gold schema (ORCH-007, AGT-008/OUT-004, HALU-008/009) --- #
class HitlRoleGrant(TIWModel):
    """A RoleAssignment grant for an approver (SEC-012). The approver may approve a
    gate ONLY if they hold the gate's required role in the matter scope + client."""

    user_id: str
    role_name: RoleName
    scope_type: ScopeType = ScopeType.MATTER
    scope_id: str                         # the matter_id (or engagement) of the scope
    client_id: str                        # isolation key — a cross-client grant is a leak
    expired: bool = False                 # SCIM/expiry negative (SEC-013)


class HitlGatePlan(TIWModel):
    """One HITL gate transition in a scenario: who acts, and the outcome."""

    gate: str                             # "H1".."H5"
    approver_user_id: str
    approved: bool = True
    outcome: str = "APPROVED"             # APPROVED|REJECTED|TIMEOUT


class HitlScenario(TIWModel):
    """One slice-⑤ HITL run over an upstream answer (reuses the slice-① pipeline
    so generation+judge replay deterministically from the recorded fixtures)."""

    scenario_id: str
    upstream: LawAnchorQuery              # the answer under review (reuses ① fixtures)
    as_client: str                        # tenant/isolation key (client_id)
    matter_id: str
    aggressive_tax_saving: bool = False   # H4 적극 절세 가드레일
    unresolved_conflicts: list[str] = Field(default_factory=list)  # H3 → 검토항목
    agent_failures: list[str] = Field(default_factory=list)        # ORCH-006 graceful degrade
    expected_agents: list[str] = Field(default_factory=list)       # full agent roster (degrade 분모)
    data_limits: list[str] = Field(default_factory=list)
    role_grants: list[HitlRoleGrant] = Field(default_factory=list)
    gate_plan: list[HitlGatePlan] = Field(default_factory=list)
    expect_deliverable: bool = True       # normal: 고객 전달본 생성
    expect_blocked: bool = False          # adversarial: 미승인 → 차단되어야
    gold_review_categories: list[str] = Field(default_factory=list)  # HALU-008 coverage


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
    # slice ② only (empty for other slices)
    rag_corpus: list[RagCorpusDoc] = Field(default_factory=list)
    rag_queries: list[RagQuery] = Field(default_factory=list)
    # slice ③ only (empty for other slices)
    web_queries: list[WebQuery] = Field(default_factory=list)
    # slice ⑤ only (empty for other slices)
    hitl_scenarios: list[HitlScenario] = Field(default_factory=list)
