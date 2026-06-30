"""src/draft.py — Draft Agent (OUT-002/003/006): 11목차 검토패키지 DOCX 생성.

# OUT-002  DOCX 검토패키지 11목차 생성 (인쇄가능 DOCX)
# OUT-003  답변에 인용·검토항목·자료한계 포함 — 무인용 단정 0 (HALU-001)
# OUT-004  고객 전달본 ≠ 내부 메모 분리 (전략리스크 내부용 한정; 승인 proof 선행)
# OUT-006  11목차 필수섹션 강제 — 누락 섹션 시 생성 실패

This is the **Draft Agent**: it consumes a ``DraftPackageData`` (the analysis
result — slice ①~④ ``SynthesisOpinion``/``Citation`` + 선택지(StrategyOption) +
검토항목(``ReviewItem`` from slice ⑤ ``src.review_items``)) and renders a
DETERMINISTIC 11-목차 검토패키지 DOCX via python-docx.

CORE INVARIANTS (절대):
  * OUT-006 : all 11 required sections are present, each carrying its mandatory
    근거/증빙/검토항목 payload. A missing section / empty mandatory payload raises
    ``DraftValidationError`` (생성 실패) — never a silent half-package.
  * OUT-003 : 무인용 단정 금지. Every legal assertion (리스크·쟁점 검토메모) carries
    at least one ``Citation`` id that resolves to a registered 근거; an uncited
    legal claim raises ``DraftValidationError``.
  * OUT-004 : 고객 전달본(client deliverable) ≠ 내부 메모. The client DOCX cannot be
    produced without an approving ``ReleaseAuthorization`` (slice ⑤ HITL proof) and
    it EXCLUDES the internal 전략리스크/검토항목 sections.

Determinism: the builder is pure (no LLM, no network, no wall-clock in the body
text). ``build_demo_draft_package`` assembles a canonical, representative package
from OFFLINE law fixture replay (real version-object Citations) so the DOCX test
and the frontend fixture replay identically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from contract.base import ApplicableBasis, SourceKind
from contract.cluster_f_qa import Citation, SynthesisOpinion
from contract.cluster_h_review import ReleaseAuthorization, ReviewItem
from src.source_registry import CitationVerificationError, SourceRegistry

# DOCX core-properties 고정 timestamp (P2: byte 결정성 — wall-clock 비유입).
_DETERMINISTIC_TS = datetime(2024, 1, 1, 0, 0, 0)

# --------------------------------------------------------------------------- #
# 11목차 필수 섹션 (OUT-006, docs/03 §117·§123 / 설계서 §4-3)
# --------------------------------------------------------------------------- #
# 13목차(변경② OUT-007 §8 채널별 + 변경③ OUT-008 §10 추론·법령추적 도식 신설).
REQUIRED_SECTIONS: list[str] = [
    "1. Executive Summary",
    "2. 회사 개요·검토 범위",
    "3. 입력 자료 목록",
    "4. 주요 세무 리스크",
    "5. 절세 기회",
    "6. 선택지별 세부담·리스크 비교표",
    "7. 쟁점별 검토 메모",
    "8. 출처 채널별 독립 결과",          # OUT-007(변경②) — 종합 전 ①②③ 병렬(내부 전용)
    "9. 관련 법령·근거 자료",
    "10. 법령 추적 경로 + 추론 과정 도식",  # OUT-008/HALU-015(변경③) — 내부 전용(전체 트레이스)
    "11. 추가 요청 자료",
    "12. 회계사 검토 필요사항",
    "13. 결론 초안·추천 검토 순서",
]

# 고객 전달본에서 제외되는 내부 전용 섹션 (OUT-004: 전략리스크·채널 원본·추론도식 내부 한정)
_INTERNAL_ONLY_SECTIONS = {
    "7. 쟁점별 검토 메모",
    "8. 출처 채널별 독립 결과",          # 채널 원본(종합 전)은 내부 검토본 전용
    "10. 법령 추적 경로 + 추론 과정 도식",  # 전체 추론 트레이스는 내부 전용(고객본은 향후 축약 수록)
    "12. 회계사 검토 필요사항",
}

# OUT-007(변경②): §8 은 3소스 채널(①법령MCP·②내부RAG·③웹)을 **모두** 표시해야 한다.
# 답하지 못한 채널도 생략하지 않고 SILENT(커버리지 갭)로 남긴다 — 부분 커버리지(채널 누락)는
# "안 한 검색을 한 것처럼" 보이게 하는 정직성 위반이므로 fail-closed (codex 적발).
_OUT007_REQUIRED_CHANNELS = {"①", "②", "③"}


class DraftError(RuntimeError):
    """Base error for the Draft Agent."""


class DraftValidationError(DraftError):
    """11목차 필수섹션/근거 위반 — 생성 실패(OUT-006/OUT-003)."""


class UnapprovedClientDraftError(DraftError):
    """고객 전달본을 승인 proof 없이 생성 시도 — 차단(OUT-004/AGT-008)."""


# --------------------------------------------------------------------------- #
# View models (display-ready; deterministic serialization for DOCX + frontend)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class StrategyOption:
    """§3-5 선택지 비교표의 한 행(보수/중립/적극) — 과세논리 vs 방어논리."""

    option_key: str            # 보수 | 중립 | 적극
    label: str                 # 보수적 처리 …
    expected_tax_burden: str   # 예상 세부담 (값 포함)
    tax_risk: str              # 세무 리스크(과세논리)
    defensibility: str         # 방어 가능성(방어논리)
    required_evidence: str     # 필요 증빙
    cpa_review_point: str      # 회계사 검토 포인트
    citation_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CitationView:
    """Citation(버전객체)을 표시·링크용으로 평탄화. raw URL은 Citation에 없으므로
    (HALU-003) 공개 법령 permalink를 결정적으로 합성한다(provenance 표시·링크용)."""

    citation_id: str
    label: str                 # 법인세법 제25조(기업업무추진비의 손금불산입)
    source_kind: str
    locator: str               # pinpoint 조문
    quote: str
    effective_from: str
    as_of: str
    basis_kind: str
    authority_rank: Optional[int]
    href: str                  # 공개 법령 링크(근거 링크)

    @staticmethod
    def from_citation(cit: Citation, *, title: str = "", law_name: str = "법인세법",
                      article_label: str = "") -> "CitationView":
        basis: ApplicableBasis = cit.applicable_basis
        ef = ""
        # effective_from is carried on the version object; surface via locator/basis.
        loc = cit.source_locator or ""
        art = article_label or (loc.split()[-1] if loc else "")
        label = loc if not title else f"{loc}({title})"
        href = _law_permalink(law_name, art)
        return CitationView(
            citation_id=cit.citation_id,
            label=label,
            source_kind=cit.source_kind.value if isinstance(cit.source_kind, SourceKind) else str(cit.source_kind),
            locator=loc,
            quote=(cit.quote or "").strip(),
            effective_from=ef,
            as_of=basis.as_of_date.strftime("%Y-%m-%d") if basis and basis.as_of_date else "",
            basis_kind=basis.basis_kind.value if basis else "",
            authority_rank=cit.authority_rank,
            href=href,
        )


def _law_permalink(law_name: str, article_label: str) -> str:
    """공개 법령 permalink(국가법령정보센터). Citation엔 raw URL이 없으므로(HALU-003)
    표시·링크용으로 결정적으로 구성한다."""
    if article_label:
        return f"https://www.law.go.kr/법령/{law_name}/{article_label}"
    return f"https://www.law.go.kr/법령/{law_name}"


@dataclass(frozen=True)
class IssueMemo:
    """쟁점별 검토메모 — 모든 법적 주장은 인용을 동반(OUT-003)."""

    topic: str
    analysis: str
    citation_ids: list[str]
    escalation: str = ""


@dataclass(frozen=True)
class RiskItem:
    title: str
    description: str
    citation_ids: list[str]
    severity: str = "MEDIUM"      # LOW|MEDIUM|HIGH


@dataclass(frozen=True)
class OpportunityItem:
    title: str
    description: str
    citation_ids: list[str]


@dataclass(frozen=True)
class InputMaterial:
    name: str
    status: str                   # 수집 | 없음 | 모름 | 결손
    confidentiality: str = "L1"


@dataclass(frozen=True)
class ChannelResult:
    """OUT-007(변경②): 종합 *전* 의 한 소스 채널(①법령MCP·②내부RAG·③웹) 독립 결과.

    종합의견(synthesis)으로 합치기 전의 각 채널 ``SourceAnswer`` 를 그대로 보여주기 위한
    display 모델. 내부 RAG 코퍼스 부재 등으로 답하지 못한 채널은 status=SILENT 로 정직하게
    남긴다(없는 자료 합성 ✕, RAG-014). 채널 원본 ⟂ 종합(EVAL-002)."""

    channel: str                  # ① ② ③
    source_label: str             # ①법령MCP · ②내부RAG(실무서) · ③공식웹
    status: str                   # SourceAnswerStatus value (ANSWERED|SILENT|ERROR|BLOCKED)
    answered: bool
    answer_excerpt: str           # 채널 답변 요지(또는 SILENT 커버리지 갭 사유)
    citation_locators: list[str] = field(default_factory=list)  # 이 채널이 든 인용 pinpoint


@dataclass(frozen=True)
class LawTraceEntry:
    """OUT-008(변경③): 한 쟁점의 법령 추적 1행 — 결론이 *어느 법령·조문·시행버전·시점*을
    따라갔는지(law-tracing). 실제 회수된 버전객체 Citation 에서 도출(날조 ✕)."""

    issue: str                    # 쟁점 표시 제목
    law_name: str                 # 법령명 (법인세법·소득세법 …)
    article: str                  # 조문 라벨 (제25조)
    as_of: str                    # 적용시점(귀속연도)
    basis_kind: str               # 적용기준
    locator: str                  # pinpoint
    quote_excerpt: str            # 인용 발췌


@dataclass(frozen=True)
class ReasoningStep:
    """OUT-008/HALU-015(변경③): 오케스트레이션 한 단계의 구조화 기록.

    *사후 서사*가 아니라 실제 실행 단계의 기록이어야 한다 — refs(source_answer_id 등)는
    실제 산출과 정합하고, 법적 판단 단계는 인용(pinpoint)을 동반한다(HALU-015)."""

    seq: int
    stage: str                    # INTAKE|ISSUE_SPOTTING|RESEARCH_CH1_LAW|RESEARCH_CH2_RAG|RESEARCH_CH3_WEB|SYNTHESIS|STRATEGY|DRAFT
    decision: str                 # 판단/근거 요지
    citation_locators: list[str] = field(default_factory=list)
    refs: dict = field(default_factory=dict)  # source_answer_id/synthesis_id 등 실제 산출 참조


@dataclass(frozen=True)
class ReasoningTrace:
    """OUT-008/HALU-015(변경③): 질의 1건의 사고 과정 — 단계 시퀀스 + 법령 추적.

    검토패키지 §10 도식(DOCX 네이티브) / 프론트 Mermaid 의 *동일 자료원*."""

    steps: list[ReasoningStep] = field(default_factory=list)
    law_trace: list[LawTraceEntry] = field(default_factory=list)


@dataclass
class DraftPackageData:
    """The Draft Agent input — slice ①~④ 분석결과 + 선택지 + 검토항목."""

    # 회사/검토 개요
    matter_id: str
    client_id: str
    company_name: str
    fiscal_year: str
    as_of_date: date
    review_scope: str
    high_risk: bool

    # 1. Executive Summary
    executive_summary: str

    # 3. 입력 자료 목록
    input_materials: list[InputMaterial]

    # 4. 주요 세무 리스크 / 5. 절세 기회
    risks: list[RiskItem]
    opportunities: list[OpportunityItem]

    # 6. 선택지별 비교표
    strategy_options: list[StrategyOption]

    # 7. 쟁점별 검토메모
    issue_memos: list[IssueMemo]

    # 8. 관련 법령·근거 자료 (버전객체 Citation 상속 — 슬라이스 ①~④; 법령·예규·판례·웹 모두 수용)
    citations: list[Citation]

    # 9. 추가 요청 자료
    additional_requests: list[str]

    # 10. 회계사 검토 필요사항 (slice ⑤ review_items)
    review_items: list[ReviewItem]

    # 11. 결론 초안·추천 검토 순서
    conclusion: str
    recommended_order: list[str]

    # 자료 한계 꼬리표(INTK-004 / OUT-003)
    data_limits: list[str] = field(default_factory=list)

    # 종합의견(slice ④ SynthesisOpinion) — 인용 상속, 새 인용 0
    synthesis: Optional[SynthesisOpinion] = None

    # 인용 검증용 버전 소스객체(슬라이스 ①~④ 산출 version object: ProvisionVersion 등).
    # OUT-003: 인용된 Citation 이 실제 등록 소스객체로 해소되는지 SourceRegistry 로
    # 검증해 날조/댕글링 인용을 거부한다(require_citation 재사용).
    source_objects: list[object] = field(default_factory=list)

    # OUT-007(변경②): 종합 *전* 의 채널별 독립 결과(①법령MCP·②내부RAG·③웹). 검토패키지
    # §8 에 병렬 표시(종합의견과 분리). 비어 있으면 §8 렌더는 생략된다(점진 도입).
    channel_results: list[ChannelResult] = field(default_factory=list)

    # OUT-008/HALU-015(변경③): 추론 과정 + 법령 추적(§10 도식 자료원). None 이면 §10 생략.
    reasoning_trace: Optional[ReasoningTrace] = None

    # -- helpers --------------------------------------------------------- #
    @property
    def citation_index(self) -> dict[str, Citation]:
        return {c.citation_id: c for c in self.citations}

    def source_registry(self) -> Optional[SourceRegistry]:
        """등록된 버전 소스객체로 SourceRegistry 구성(없으면 None — cidx 존재검사만)."""
        if not self.source_objects:
            return None
        registry = SourceRegistry()
        registry.register_all(self.source_objects)
        return registry

    def citation_views(self, titles: Optional[dict[str, str]] = None,
                       articles: Optional[dict[str, str]] = None) -> list[CitationView]:
        titles = titles or {}
        articles = articles or {}
        return [
            CitationView.from_citation(
                c, title=titles.get(c.citation_id, ""),
                article_label=articles.get(c.citation_id, ""),
            )
            for c in self.citations
        ]


# --------------------------------------------------------------------------- #
# Validation (OUT-006 + OUT-003) — fail-closed before any rendering
# --------------------------------------------------------------------------- #
def validate_draft_package(data: DraftPackageData) -> None:
    """11목차 필수섹션·무인용 단정·빈 문자열·고위험 경고를 강제. 위반 → DraftValidationError."""
    cidx = data.citation_index
    registry = data.source_registry()

    def need(cond: bool, msg: str) -> None:
        if not cond:
            raise DraftValidationError(f"OUT-006 필수섹션/근거 누락: {msg}")

    def nonblank(value: object, label: str) -> None:
        """OUT-006(P1-1): 핵심 문자열 필드는 strip 기반 non-empty(빈/공백 → 실패)."""
        if not (isinstance(value, str) and value.strip()):
            raise DraftValidationError(f"OUT-006 빈 문자열 필드: {label}")

    def require_cited(label: str, citation_ids: list[str]) -> None:
        """OUT-003: 법적 주장은 (a)인용 non-empty, (b)근거목록 해소, (c)SourceRegistry
        존재/정합(require_citation) 을 모두 충족해야 한다(무인용/날조/댕글링 거부)."""
        if not citation_ids:
            raise DraftValidationError(
                f"OUT-003 무인용 단정: {label}에 인용 없음(법적 주장은 인용 필수)"
            )
        for cid in citation_ids:
            cit = cidx.get(cid)
            if cit is None:
                raise DraftValidationError(
                    f"OUT-003 인용 미해소: {label}의 인용 {cid} 가 근거목록에 없음"
                )
            # fail-closed: source_objects(버전 소스객체)로 만든 SourceRegistry가 없으면
            # 날조 인용을 검증할 수 없으므로 통과시키지 않는다(인덱스 존재만으로는 부족).
            if registry is None:
                raise DraftValidationError(
                    f"OUT-003 인용 미검증(날조 차단): {label}의 인용 {cid} 를 검증할 "
                    f"SourceRegistry 없음 — 법적 주장 인용은 source_objects(버전 소스객체) 필수"
                )
            try:
                registry.require_citation(cit)
            except CitationVerificationError as exc:
                raise DraftValidationError(
                    f"OUT-003 인용 검증 실패(SourceRegistry/날조): {label}의 인용 {cid} — {exc}"
                ) from exc

    need(bool(data.executive_summary.strip()), "1. Executive Summary 본문")
    need(bool(data.company_name.strip()) and bool(data.review_scope.strip()),
         "2. 회사 개요·검토 범위")
    need(bool(data.input_materials), "3. 입력 자료 목록(≥1)")
    need(bool(data.risks), "4. 주요 세무 리스크(≥1)")
    need(bool(data.opportunities), "5. 절세 기회(≥1)")
    # 6. 비교표: 보수/중립/적극 3종 선택지 필수(§3-5)
    keys = {o.option_key for o in data.strategy_options}
    need({"보수", "중립", "적극"}.issubset(keys),
         "6. 선택지 비교표는 보수/중립/적극 3종 필수")
    need(bool(data.issue_memos), "7. 쟁점별 검토 메모(≥1)")
    # OUT-007: §8 은 3채널(①②③)을 모두 표시 — 누락 채널은 SILENT 로 남겨야 하며,
    # 채널 자체를 빼면(부분 커버리지) 정직성 위반 → fail-closed.
    _present_channels = {cr.channel for cr in data.channel_results}
    need(_OUT007_REQUIRED_CHANNELS.issubset(_present_channels),
         "8. 출처 채널별 독립 결과는 3채널(①②③) 모두 표시 필수(누락 채널은 SILENT 로 표기, "
         f"OUT-007) — 누락 채널: {sorted(_OUT007_REQUIRED_CHANNELS - _present_channels)}")
    need(bool(data.citations), "9. 관련 법령·근거 자료(≥1 버전객체 인용)")
    # OUT-008/HALU-015: §10 은 추론 트레이스(단계) + 법령 추적(쟁점→법령) 을 모두 가져야 한다.
    need(data.reasoning_trace is not None
         and bool(data.reasoning_trace.steps) and bool(data.reasoning_trace.law_trace),
         "10. 법령 추적 경로 + 추론 과정 도식(ReasoningTrace.steps ≥1 + law_trace ≥1, OUT-008)")
    # HALU-015(codex): §10 trace 는 실제 산출과 정합해야 한다 — 존재만으로는 부족(사후 서사·
    # 날조/stale 차단). law_trace·추론단계가 *드는 인용*은 실제 패키지 인용(또는 채널 결과가
    # 든 인용)으로 backed 되어야 하며, 패키지에 없는 조문/pinpoint 를 들면 표시 차단(fail-closed).
    rt = data.reasoning_trace
    if rt is not None:
        _actual_loc = {c.source_locator for c in data.citations if c.source_locator}
        _channel_loc = {loc for cr in data.channel_results for loc in cr.citation_locators}
        _known_loc = _actual_loc | _channel_loc
        # (법령명, 조문) 쌍 — locator 가 비어 있어도 실제 인용과 매칭할 수 있게(source_locator
        # 예: "법인세법 제25조" → ("법인세법","제25조")). 빈 locator 의 미backed 날조행 차단(codex).
        _known_pairs = set()
        for c in data.citations:
            toks = (c.source_locator or "").split()
            if len(toks) >= 2:
                _known_pairs.add((toks[0], toks[-1]))
        for e in rt.law_trace:
            # 모든 law_trace 행은 locator(pinpoint) *또는* (법령명,조문) 으로 실제 인용에
            # backed 되어야 한다 — 빈 locator 라고 통과시키지 않는다.
            backed = (bool(e.locator) and e.locator in _known_loc) \
                or ((e.law_name, e.article) in _known_pairs)
            if not backed:
                raise DraftValidationError(
                    f"HALU-015 §10 law-tracing 미backed(날조/stale): 쟁점 '{e.issue}' 의 인용 "
                    f"({e.law_name} {e.article} / locator={e.locator!r}) 가 패키지 실제 인용에 "
                    f"없음(사후 서사 차단)"
                )
        for s in rt.steps:
            for loc in s.citation_locators:
                if loc not in _known_loc:
                    raise DraftValidationError(
                        f"HALU-015 §10 추론단계 날조 인용: 단계 {s.seq}({s.stage}) 의 "
                        f"{loc!r} 가 패키지 실제 인용에 없음(사후 서사 차단)"
                    )
    need(bool(data.additional_requests), "11. 추가 요청 자료(≥1)")
    need(bool(data.review_items), "12. 회계사 검토 필요사항(≥1, slice⑤ review_items)")
    need(bool(data.conclusion.strip()) and bool(data.recommended_order),
         "13. 결론 초안·추천 검토 순서")

    # P1-1: 리스트가 비어있지 않아도 내부 핵심 문자열은 strip 기반 non-empty 강제
    for m in data.input_materials:
        nonblank(m.name, "3. 입력 자료 이름")
    for req in data.additional_requests:
        nonblank(req, "9. 추가 요청 자료 항목")
    for step in data.recommended_order:
        nonblank(step, "11. 추천 검토 순서 항목")

    # OUT-003: 무인용 단정 금지 — 법적 주장을 담는 모든 필드(리스크·쟁점메모·선택지·절세기회)
    for risk in data.risks:
        nonblank(risk.title, f"리스크 제목({risk.title!r})")
        nonblank(risk.description, f"리스크 '{risk.title}' 설명")
        require_cited(f"리스크 '{risk.title}'", risk.citation_ids)
    for memo in data.issue_memos:
        nonblank(memo.topic, f"쟁점메모 주제({memo.topic!r})")
        nonblank(memo.analysis, f"쟁점메모 '{memo.topic}' 분석")
        require_cited(f"쟁점메모 '{memo.topic}'", memo.citation_ids)
    for op in data.opportunities:
        nonblank(op.title, f"절세기회 제목({op.title!r})")
        nonblank(op.description, f"절세기회 '{op.title}' 설명")
        require_cited(f"절세기회 '{op.title}'", op.citation_ids)
    for opt in data.strategy_options:
        # 선택지 행의 모든 핵심 문자열(특히 과세논리 tax_risk·방어논리 defensibility)
        for fname, fval in (
            ("label", opt.label), ("expected_tax_burden", opt.expected_tax_burden),
            ("tax_risk", opt.tax_risk), ("defensibility", opt.defensibility),
            ("required_evidence", opt.required_evidence),
            ("cpa_review_point", opt.cpa_review_point),
        ):
            nonblank(fval, f"선택지 '{opt.option_key}' {fname}")
        # tax_risk(과세논리)·defensibility(방어논리)는 법적 주장 → 인용 동반·검증
        require_cited(f"선택지 '{opt.option_key}'(과세/방어논리)", opt.citation_ids)

    # HALU-008/009: high_risk 를 적극 선택지·위험도에서 재도출 — data.high_risk=False 라도
    # 적극 선택지 존재 또는 고위험(HIGH) 리스크가 있으면 회계사 검토경고가 누락되면 안 된다.
    effective_high_risk = (
        data.high_risk
        or any(r.severity == "HIGH" for r in data.risks)
        or any(o.option_key == "적극" for o in data.strategy_options)
    )
    if effective_high_risk:
        from src.review_items import has_high_risk_warning
        if not has_high_risk_warning(data.review_items):
            raise DraftValidationError(
                "HALU-008/009: 고위험 콘텐츠(적극 선택지/HIGH 리스크)에 회계사 검토경고(검토항목) 누락"
            )


# --------------------------------------------------------------------------- #
# DOCX rendering (OUT-002) — deterministic structure
# --------------------------------------------------------------------------- #
def _render_package_docx(
    data: DraftPackageData,
    out_path: str | Path,
    *,
    internal: bool,
    titles: Optional[dict[str, str]] = None,
    articles: Optional[dict[str, str]] = None,
) -> Path:
    """11목차 검토패키지 DOCX 렌더(OUT-002) — **내부 전용 헬퍼**.

    ``internal=True`` 는 내부 검토본(11섹션 전체), ``internal=False`` 는 고객 전달본
    레이아웃(내부 전략메모·검토항목 제외, OUT-004)이다. 고객 레이아웃(``internal=False``)
    은 승인 proof 를 검증하는 ``build_client_deliverable_docx`` 만 호출하며, proof 없는
    공개 경로는 존재하지 않는다(OUT-004/AGT-008)."""
    try:
        from docx import Document
        from docx.shared import Pt
    except ImportError as exc:  # pragma: no cover - adapters extra 미설치
        raise DraftError(
            "python-docx 미설치 — `pip install -e .[adapters]` 필요(OUT-002 DOCX)"
        ) from exc

    validate_draft_package(data)
    cviews = {cv.citation_id: cv for cv in data.citation_views(titles, articles)}

    doc = Document()
    # P2: core properties timestamp 를 고정값으로 — wall-clock 비유입(byte 결정성↑).
    doc.core_properties.created = _DETERMINISTIC_TS
    doc.core_properties.modified = _DETERMINISTIC_TS
    doc.add_heading(f"{data.company_name} {data.fiscal_year} 법인세 검토패키지 초안", level=0)
    sub = doc.add_paragraph(
        f"검토기준일(as-of) {data.as_of_date:%Y-%m-%d} · "
        f"{'내부 검토본' if internal else '고객 전달본'} · "
        f"{'[고위험]' if data.high_risk else '[표준]'}"
    )
    sub.runs[0].font.size = Pt(9)
    # 자료한계 꼬리표(과신 방지 — INTK-004)
    if data.data_limits:
        lim = doc.add_paragraph("자료한계: " + " / ".join(data.data_limits))
        lim.runs[0].italic = True

    def cite_inline(citation_ids: list[str]) -> str:
        labels = [cviews[c].label for c in citation_ids if c in cviews]
        return f"  [근거: {'; '.join(labels)}]" if labels else ""

    rendered: list[str] = []

    # 1. Executive Summary
    doc.add_heading(REQUIRED_SECTIONS[0], level=1)
    doc.add_paragraph(data.executive_summary)
    rendered.append(REQUIRED_SECTIONS[0])

    # 2. 회사 개요·검토 범위
    doc.add_heading(REQUIRED_SECTIONS[1], level=1)
    doc.add_paragraph(f"회사: {data.company_name} (거래처 {data.client_id}, 사건 {data.matter_id})")
    doc.add_paragraph(f"대상 사업연도: {data.fiscal_year}")
    doc.add_paragraph(f"검토 범위: {data.review_scope}")
    rendered.append(REQUIRED_SECTIONS[1])

    # 3. 입력 자료 목록
    doc.add_heading(REQUIRED_SECTIONS[2], level=1)
    t3 = doc.add_table(rows=1, cols=3)
    t3.style = "Table Grid"
    h = t3.rows[0].cells
    h[0].text, h[1].text, h[2].text = "자료", "상태", "기밀등급"
    for m in data.input_materials:
        r = t3.add_row().cells
        r[0].text, r[1].text, r[2].text = m.name, m.status, m.confidentiality
    rendered.append(REQUIRED_SECTIONS[2])

    # 4. 주요 세무 리스크
    doc.add_heading(REQUIRED_SECTIONS[3], level=1)
    for risk in data.risks:
        doc.add_paragraph(
            f"[{risk.severity}] {risk.title} — {risk.description}{cite_inline(risk.citation_ids)}",
            style="List Bullet",
        )
    rendered.append(REQUIRED_SECTIONS[3])

    # 5. 절세 기회
    doc.add_heading(REQUIRED_SECTIONS[4], level=1)
    for op in data.opportunities:
        doc.add_paragraph(
            f"{op.title} — {op.description}{cite_inline(op.citation_ids)}",
            style="List Bullet",
        )
    rendered.append(REQUIRED_SECTIONS[4])

    # 6. 선택지별 세부담·리스크 비교표 (보수/중립/적극) — 과세/방어논리 인용 표기(OUT-003)
    doc.add_heading(REQUIRED_SECTIONS[5], level=1)
    t6 = doc.add_table(rows=1, cols=7)
    t6.style = "Table Grid"
    hdr = t6.rows[0].cells
    for i, txt in enumerate(
        ["선택지", "예상 세부담", "세무 리스크(과세논리)", "방어 가능성(방어논리)",
         "필요 증빙", "회계사 검토 포인트", "근거(인용)"]
    ):
        hdr[i].text = txt
    for o in sorted(data.strategy_options, key=_option_order):
        c = t6.add_row().cells
        c[0].text = o.label
        c[1].text = o.expected_tax_burden
        c[2].text = o.tax_risk
        c[3].text = o.defensibility
        c[4].text = o.required_evidence
        c[5].text = o.cpa_review_point
        c[6].text = "; ".join(cviews[cid].label for cid in o.citation_ids if cid in cviews)
    rendered.append(REQUIRED_SECTIONS[5])

    # 7. 쟁점별 검토 메모 (내부 전용)
    if internal:
        doc.add_heading(REQUIRED_SECTIONS[6], level=1)
        for memo in data.issue_memos:
            doc.add_heading(memo.topic, level=2)
            doc.add_paragraph(f"{memo.analysis}{cite_inline(memo.citation_ids)}")
            if memo.escalation:
                doc.add_paragraph(f"escalation: {memo.escalation}")
        rendered.append(REQUIRED_SECTIONS[6])

    # 8. 출처 채널별 독립 결과 (내부 전용 — 종합 *전* 의 ①②③ 병렬, OUT-007 변경②)
    if internal:
        doc.add_heading(REQUIRED_SECTIONS[7], level=1)
        doc.add_paragraph(
            "종합의견으로 합치기 전, 각 출처 채널이 독립적으로 낸 결과입니다(채널 원본 ⟂ 종합). "
            "답하지 못한 채널은 SILENT(커버리지 갭)로 정직하게 표기합니다."
        )
        t8 = doc.add_table(rows=1, cols=5)
        t8.style = "Table Grid"
        for i, txt in enumerate(["채널", "출처", "상태", "답변 요지", "인용(pinpoint)"]):
            t8.rows[0].cells[i].text = txt
        for cr in data.channel_results:
            r = t8.add_row().cells
            r[0].text = cr.channel
            r[1].text = cr.source_label
            r[2].text = cr.status if cr.answered else f"{cr.status} (커버리지 갭)"
            r[3].text = cr.answer_excerpt or ("—" if cr.answered else "(근거 없음)")
            r[4].text = "; ".join(cr.citation_locators)
        rendered.append(REQUIRED_SECTIONS[7])

    # 9. 관련 법령·근거 자료 (법령·예규·판례·웹 — 실제 인용된 근거만 본문에 나열)
    doc.add_heading(REQUIRED_SECTIONS[8], level=1)
    for cv in cviews.values():
        rank = f"(권위 {cv.authority_rank})" if cv.authority_rank else ""
        doc.add_paragraph(
            f"{cv.label} {rank} — 적용시점 {cv.as_of}({cv.basis_kind}) · "
            f"인용: “{cv.quote[:120]}” · 링크: {cv.href}",
            style="List Bullet",
        )
    rendered.append(REQUIRED_SECTIONS[8])

    # 10. 법령 추적 경로 + 추론 과정 도식 (내부 전용 — OUT-008/HALU-015 변경③)
    if internal:
        doc.add_heading(REQUIRED_SECTIONS[9], level=1)
        rt = data.reasoning_trace
        # (a) 법령 추적(law-tracing): 쟁점 → 법령·조문·시행시점·pinpoint·인용
        doc.add_heading("10-1. 법령 추적 경로 (law-tracing)", level=2)
        t10a = doc.add_table(rows=1, cols=5)
        t10a.style = "Table Grid"
        for i, txt in enumerate(["쟁점", "법령·조문", "적용시점", "pinpoint", "인용 발췌"]):
            t10a.rows[0].cells[i].text = txt
        for e in (rt.law_trace if rt else []):
            r = t10a.add_row().cells
            r[0].text = e.issue
            r[1].text = f"{e.law_name} {e.article}"
            r[2].text = f"{e.as_of}({e.basis_kind})" if e.as_of else e.basis_kind
            r[3].text = e.locator
            r[4].text = e.quote_excerpt
        # (b) 추론 과정 도식(ReasoningTrace) — DOCX 네이티브 단계 흐름 + 트레이스 표
        doc.add_heading("10-2. 추론 과정 (ReasoningTrace)", level=2)
        if rt and rt.steps:
            doc.add_paragraph(" → ".join(f"[{s.stage}]" for s in rt.steps))  # 네이티브 흐름 도식
            t10b = doc.add_table(rows=1, cols=4)
            t10b.style = "Table Grid"
            for i, txt in enumerate(["#", "단계", "판단·근거", "인용"]):
                t10b.rows[0].cells[i].text = txt
            for s in rt.steps:
                r = t10b.add_row().cells
                r[0].text = str(s.seq)
                r[1].text = s.stage
                r[2].text = s.decision
                r[3].text = "; ".join(s.citation_locators)
        rendered.append(REQUIRED_SECTIONS[9])

    # 11. 추가 요청 자료
    doc.add_heading(REQUIRED_SECTIONS[10], level=1)
    for req in data.additional_requests:
        doc.add_paragraph(req, style="List Bullet")
    rendered.append(REQUIRED_SECTIONS[10])

    # 12. 회계사 검토 필요사항 (내부 전용 — slice⑤ review_items)
    if internal:
        doc.add_heading(REQUIRED_SECTIONS[11], level=1)
        for it in data.review_items:
            mark = " ⚠검토경고" if it.requires_warning else ""
            doc.add_paragraph(
                f"[{it.gate or '-'}/{it.category.value}/{it.severity}]{mark} {it.description}",
                style="List Bullet",
            )
        rendered.append(REQUIRED_SECTIONS[11])

    # 13. 결론 초안·추천 검토 순서
    doc.add_heading(REQUIRED_SECTIONS[12], level=1)
    doc.add_paragraph(data.conclusion)
    doc.add_paragraph("추천 검토 순서:")
    for i, step in enumerate(data.recommended_order, start=1):
        doc.add_paragraph(f"{i}. {step}", style="List Number")
    rendered.append(REQUIRED_SECTIONS[12])

    # OUT-006: 내부본은 13섹션 모두, 고객본은 내부 전용 4섹션(7·8·10·12) 제외가 의도된 누락
    expected = REQUIRED_SECTIONS if internal else [
        s for s in REQUIRED_SECTIONS if s not in _INTERNAL_ONLY_SECTIONS
    ]
    if rendered != expected:
        raise DraftValidationError(
            f"OUT-006 섹션 누락/순서 오류: {set(expected) - set(rendered)}"
        )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path


def _option_order(o: StrategyOption) -> int:
    return {"보수": 0, "중립": 1, "적극": 2}.get(o.option_key, 9)


def build_review_package_docx(
    data: DraftPackageData,
    out_path: str | Path,
    *,
    titles: Optional[dict[str, str]] = None,
    articles: Optional[dict[str, str]] = None,
) -> Path:
    """**내부 검토본** 11목차 검토패키지 DOCX 생성(OUT-002, internal 전용).

    OUT-004(P0-2): 이 공개 경로는 고객 레이아웃을 만들지 않는다 — 고객 전달본은
    승인 proof(ReleaseAuthorization)를 검증하는 ``build_client_deliverable_docx`` 로만
    생성된다. 따라서 proof 없이 고객 레이아웃을 만드는 공개 경로는 존재하지 않는다."""
    return _render_package_docx(
        data, out_path, internal=True, titles=titles, articles=articles
    )


def build_client_deliverable_docx(
    data: DraftPackageData,
    out_path: str | Path,
    *,
    release_proof: Optional[ReleaseAuthorization],
    titles: Optional[dict[str, str]] = None,
    articles: Optional[dict[str, str]] = None,
) -> Path:
    """고객 전달본 DOCX — 승인 proof(ReleaseAuthorization) 없이는 생성 차단(OUT-004).

    proof 가 본 패키지의 테넌트/스코프에 묶이고 필수 게이트(H5, 고위험 시 H4)가
    승인되어 있어야 한다(slice ⑤ HITL). 내부 전략메모(7)·검토항목(10)은 제외된다."""
    if release_proof is None:
        raise UnapprovedClientDraftError(
            "OUT-004/AGT-008: 승인 proof(ReleaseAuthorization) 없이 고객 전달본 생성 불가"
        )
    if release_proof.client_id != data.client_id or release_proof.matter_id != data.matter_id:
        raise UnapprovedClientDraftError(
            "OUT-004/SEC-003: 승인 proof가 본 패키지의 테넌트/스코프와 불일치"
        )
    if release_proof.high_risk != data.high_risk:
        raise UnapprovedClientDraftError(
            "OUT-004: 승인 proof의 위험등급이 패키지와 불일치(고위험은 H4+H5 선행)"
        )
    # ReleaseAuthorization validator 가 필수 게이트 승인을 이미 강제(생성 불가 시 차단).
    # 고객 레이아웃(internal=False)은 proof 검증을 통과한 이 경로에서만 렌더된다(OUT-004).
    return _render_package_docx(
        data, out_path, internal=False, titles=titles, articles=articles
    )


# --------------------------------------------------------------------------- #
# Fixture serialization (frontend) — slice 산출 fixture(JSON)
# --------------------------------------------------------------------------- #
def draft_package_to_fixture(
    data: DraftPackageData,
    *,
    titles: Optional[dict[str, str]] = None,
    articles: Optional[dict[str, str]] = None,
) -> dict:
    """프론트 3화면(②선택지·③DOCX미리보기)이 렌더할 분석결과 JSON."""
    cviews = data.citation_views(titles, articles)
    return {
        "matter_id": data.matter_id,
        "client_id": data.client_id,
        "company_name": data.company_name,
        "fiscal_year": data.fiscal_year,
        "as_of_date": data.as_of_date.strftime("%Y-%m-%d"),
        "review_scope": data.review_scope,
        "high_risk": data.high_risk,
        "data_limits": list(data.data_limits),
        "sections": list(REQUIRED_SECTIONS),
        "executive_summary": data.executive_summary,
        "input_materials": [
            {"name": m.name, "status": m.status, "confidentiality": m.confidentiality}
            for m in data.input_materials
        ],
        "risks": [
            {"title": r.title, "description": r.description, "severity": r.severity,
             "citation_ids": list(r.citation_ids)}
            for r in data.risks
        ],
        "opportunities": [
            {"title": o.title, "description": o.description, "citation_ids": list(o.citation_ids)}
            for o in data.opportunities
        ],
        "strategy_options": [
            {
                "option_key": o.option_key, "label": o.label,
                "expected_tax_burden": o.expected_tax_burden,
                "tax_risk": o.tax_risk, "defensibility": o.defensibility,
                "required_evidence": o.required_evidence,
                "cpa_review_point": o.cpa_review_point,
                "citation_ids": list(o.citation_ids),
            }
            for o in sorted(data.strategy_options, key=_option_order)
        ],
        "issue_memos": [
            {"topic": m.topic, "analysis": m.analysis,
             "citation_ids": list(m.citation_ids), "escalation": m.escalation}
            for m in data.issue_memos
        ],
        "citations": [
            {
                "citation_id": cv.citation_id, "label": cv.label,
                "source_kind": cv.source_kind, "locator": cv.locator,
                "quote": cv.quote, "as_of": cv.as_of, "basis_kind": cv.basis_kind,
                "authority_rank": cv.authority_rank, "href": cv.href,
            }
            for cv in cviews
        ],
        "additional_requests": list(data.additional_requests),
        "review_items": [
            {
                "item_id": it.item_id, "category": it.category.value,
                "description": it.description, "gate": it.gate,
                "severity": it.severity, "requires_warning": it.requires_warning,
            }
            for it in data.review_items
        ],
        "conclusion": data.conclusion,
        "recommended_order": list(data.recommended_order),
        "synthesis_opinion": data.synthesis.opinion_text if data.synthesis else "",
        # OUT-007(변경②): 채널별 독립 결과(①②③) — 프론트 §8 렌더용
        "channel_results": [
            {
                "channel": cr.channel, "source_label": cr.source_label,
                "status": cr.status, "answered": cr.answered,
                "answer_excerpt": cr.answer_excerpt,
                "citation_locators": list(cr.citation_locators),
            }
            for cr in data.channel_results
        ],
        # OUT-008/HALU-015(변경③): 추론 과정 + 법령 추적 — 프론트 §10 Mermaid 도식용
        "reasoning_trace": (
            {
                "steps": [
                    {"seq": s.seq, "stage": s.stage, "decision": s.decision,
                     "citation_locators": list(s.citation_locators), "refs": dict(s.refs)}
                    for s in data.reasoning_trace.steps
                ],
                "law_trace": [
                    {"issue": e.issue, "law_name": e.law_name, "article": e.article,
                     "as_of": e.as_of, "basis_kind": e.basis_kind, "locator": e.locator,
                     "quote_excerpt": e.quote_excerpt}
                    for e in data.reasoning_trace.law_trace
                ],
            }
            if data.reasoning_trace else None
        ),
    }
