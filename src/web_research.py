"""src/web_research.py — channel ③ Web Research pipeline (docs/06).

Web Research is a **최신 공식근거 수집기, NOT an answer generator** (docs/06 대원칙):
the search engine is a DISCOVERY tool, never an authority. A web candidate can
only ground a conclusion once it is PROMOTED to an authority source object —
official original + cross-checked against the 법령 원문 (channel ①).

The 8-step pipeline (docs/06 §2) made concrete:
  ① Query Planner (+ 한국어 확장, WEB-008)
  ② Source Policy 사전 (허용 공식도메인만 질의 — Tavily include_domains)
  ③ Search API (Tavily, src.ai.tavily_client — RECORD/REPLAY)
  ④ Page Extraction → SourceSnapshot (원문·발행기관·retrieved_at·content_hash, WEB-005)
  ⑤ Source Policy 사후 (mirror/블로그/요약/구버전 사후 탈락 — WEB-002/004/007)
  ⑥ Source Scoring (공식성·최신성·쟁점관련성·**적용시점 유효성**; 최신성⟂적용시점 분리 WEB-012)
  ⑦ Conflict Check (법령①/RAG② 와 충돌 표시 — 평균 금지; full 종합은 slice ④)
  ⑧ Promotion (공식·시점유효·법령대조된 것만 권위 소스로 승격 — WEB-011)

GROUNDING (docs/06 §9 웹 단독 단정 금지): a promoted source's conclusion is anchored
to the AUTHORITATIVE version-pinned ``ProvisionVersion`` obtained from channel ①
(``src.ai.law_data_source``) — the web provides DISCOVERY + provenance, ① provides
version authority. With NO promotable official source the pipeline ABSTAINS (no
tax 단정) rather than concluding from web alone.

The WEB ``SourceAnswer`` reuses the slice-① generator (``src.legal_research``,
``source_type=WEB``, channel ③) so the LLM legal reasoning, citation grounding,
registry verification and DETERMINISTIC entailment are shared (no new answer path).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from contract.base import ApplicableBasis, BasisKind, SourceKind, SourceType
from contract.cluster_d_provenance import ProvisionVersion, SourceSnapshot
from contract.cluster_f_qa import Citation, Claim
from src.ai.law_data_source import (
    LawSourceError,
    ProvisionLookupResult,
    default_law_source,
)
from src.ai.llm_client import LLMClient
from src.ai.tavily_client import (
    OFFICIAL_DOMAINS,
    PUBLISHER_BY_DOMAIN,
    TavilyResult,
    default_tavily_client,
    official_domain_of,
)
from src.judge import _normalize, _provision_subject
from src.legal_research import ResearchLiteAnswer, generate_research_answer
from src.source_registry import SourceRegistry

# Discovery → provenance authority rank by domain (docs/02 §5 권위 위계). law.go.kr
# is the law original; NTS/MOEF are administrative authorities; 심판원/대법원 판례.
_DOMAIN_AUTHORITY = {
    "law.go.kr": 1, "nts.go.kr": 2, "moef.go.kr": 3, "scourt.go.kr": 3, "tt.go.kr": 4,
}

# Non-official signals the 사후 필터 hard-rejects even if a search API returned them
# (docs/06 §4: 미러/요약/블로그/카페/광고). Domain check is primary; these catch a
# mirror hosted on a look-alike host.
_UNOFFICIAL_MARKERS = ("blog.", "cafe.", "tistory.", "brunch.", "youtube.", "namu.")

_ARTICLE_RE = re.compile(r"제\s*\d+\s*조(?:의\s*\d+)?")


# --------------------------------------------------------------------------- #
# ① Query Planner (+ 한국어 확장, WEB-008)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class QueryPlan:
    primary: str
    expansions: list[str]

    @property
    def all_queries(self) -> list[str]:
        seen: list[str] = []
        for q in [self.primary, *self.expansions]:
            if q and q not in seen:
                seen.append(q)
        return seen


def plan_queries(*, law_name: str, article_label: str, as_of_date: date,
                 issue: str, tax_type: str = "법인세") -> QueryPlan:
    """Korean query expansion (WEB-008): 법령명·조문번호 형식 변형·세목·연도. A single
    PRIMARY query is what the recorded fixture is keyed on; expansions are recorded
    for auditability (the planner is deterministic so the fixture key is stable)."""
    year = as_of_date.year
    art = article_label.replace(" ", "")
    art_num = _ARTICLE_RE.search(art)
    art_compact = art_num.group(0).replace("제", "").replace("조", "") if art_num else art
    primary = f"{law_name} {art} {issue} {year} 손금 한도 공식".strip()
    expansions = [
        f"{law_name} {art} {issue}",
        f"{law_name} 제{art_compact}조 {issue} {year} 시행",
        f"국세청 {tax_type} {issue} {year}",
    ]
    return QueryPlan(primary=primary, expansions=expansions)


# --------------------------------------------------------------------------- #
# ④ SourceSnapshot from a Tavily result
# --------------------------------------------------------------------------- #
def _parse_published(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(s[: len(fmt) + 2], fmt).date()
        except ValueError:
            continue
    m = re.search(r"(20\d{2})", s)
    return date(int(m.group(1)), 1, 1) if m else None


def _parse_retrieved_at(s: Optional[str]) -> datetime:
    if s:
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def snapshot_from_result(result: TavilyResult, *, idx: int,
                         retrieved_at: Optional[str] = None) -> SourceSnapshot:
    """④ Page Extraction → SourceSnapshot (WEB-005): 원문·발행기관·retrieved_at·
    content_hash. ``content_hash`` pins the EXTRACTED original text (snippet 금지).
    ``retrieved_at`` comes from the recorded Tavily fixture (manifest recorded_at)
    so replay is reproducible — not a wall-clock now()."""
    dom = official_domain_of(result.url)
    return SourceSnapshot(
        snapshot_id=f"web_snap_{idx}_{result.content_hash[:12]}",
        url=result.url,
        canonical_title=result.title or result.url,
        publisher=PUBLISHER_BY_DOMAIN.get(dom) if dom else None,
        published_date=_parse_published(result.published_date),
        effective_date=None,
        retrieved_at=_parse_retrieved_at(retrieved_at),
        extraction_method="HTML",
        content_hash=result.content_hash,
        official=dom is not None,
    )


# --------------------------------------------------------------------------- #
# ⑥ Source Scoring (WEB-012: 최신성 ⟂ 적용시점 유효성 분리 저장)
# --------------------------------------------------------------------------- #
def _freshness(snapshot: SourceSnapshot) -> float:
    """최신성: recency of the web PUBLICATION (published_date) only. Deterministic
    (no wall-clock — replay-stable): year mapped to [0,1] over 2010..2026. Unknown
    date = 0.4 (mild). This is NOT applicable-time validity (WEB-012)."""
    d = snapshot.published_date
    if d is None:
        return 0.4
    return max(0.0, min(1.0, (d.year - 2010) / (2026 - 2010)))


def _candidate_header_subject(text: str, title: str) -> Optional[str]:
    """The 조문 SUBJECT a candidate explicitly describes, parsed from a ``제N조(<제목>)``
    header in its title/content (same deterministic parse as the judge). Used to
    detect a source describing a DIFFERENT-era version than the one in force at
    as_of (e.g. '접대비' vs '기업업무추진비')."""
    for blob in (title, text):
        subj = _provision_subject(blob or "")
        if subj:
            return subj
    return None


def _applicable_validity(*, snapshot: SourceSnapshot, result: TavilyResult,
                         pv: ProvisionVersion, as_of: date) -> tuple[float, str]:
    """적용시점 유효성 (WEB-012) — SEPARATE from 최신성.

    A source is applicable iff (a) the AUTHORITATIVE version (channel ①) is in force
    at as_of [window check], AND (b) the candidate does not explicitly describe a
    DIFFERENT-era version of the article. (b) is detected by parsing the candidate's
    OWN ``제N조(<제목>)`` header subject and comparing it to the authoritative subject
    — a candidate headed '제25조(접대비…)' queried for a 2024 basis (auth subject
    '기업업무추진비') is the most-recent-looking-but-stale trap WEB-012 warns about."""
    window_valid = pv.effective_from <= as_of and (pv.effective_to is None or as_of < pv.effective_to)
    if not window_valid:
        return 0.0, "권위 버전 시행창 밖(시점 불일치)"
    auth_subject = _provision_subject(pv.text)
    cand_subject = _candidate_header_subject(result.content, result.title)
    if auth_subject and cand_subject and cand_subject != auth_subject and auth_subject not in (
        _normalize(result.content) + " " + _normalize(result.title)
    ):
        return 0.0, f"후보가 다른 시행버전('{cand_subject}')을 기술 — 적용시점('{auth_subject}') 불일치"
    return 1.0, "권위 버전 시행창 내 + 후보 기술버전 일치/중립"


def _issue_relevance(result: TavilyResult, *, law_name: str, article_label: str,
                     issue: str, subject: str) -> float:
    hay = _normalize(result.title) + " " + _normalize(result.content)
    terms = [t for t in [law_name, article_label.replace(" ", ""), issue, subject] if t]
    hit = sum(1 for t in terms if t and t in hay)
    return hit / len(terms) if terms else 0.0


# WEB-011 대조 임계값: 후보 원문이 법령 원문(① ProvisionVersion)과 공유하는 최장
# 공통 부분문자열의 최소 길이. 실측상 진짜 조문 본문 페이지는 법령 원문과 500~900자
# 이상 일치하고, 안내/내비게이션 페이지는 ≤30자에 그친다 — 토큰 존재가 아니라 *실제
# 본문 일치*를 요구해야 '공식 원문 대조'가 의미를 갖는다(codex P0).
_CORROBORATION_MIN = 40


def _longest_common_excerpt(web_content: str, pv_text: str) -> tuple[int, str]:
    """The longest verbatim substring shared by the (whitespace-normalized) web
    page content and the authoritative provision text. This is the REAL 법령 원문
    대조 (WEB-011): a token-presence check would pass for an official navigation
    page that merely names '법인세법'; this requires the page to actually carry a
    contiguous chunk of the statute. Deterministic (difflib, autojunk off)."""
    a = _normalize(web_content)
    b = _normalize(pv_text)
    if not a or not b:
        return 0, ""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    m = sm.find_longest_match(0, len(a), 0, len(b))
    # strip leading HTML/list artifacts; the result stays a substring of BOTH a,b
    excerpt = a[m.a : m.a + m.size].strip().lstrip(">").strip()
    return m.size, excerpt


def content_corroborated(web_content: str, pv_text: str,
                         min_len: int = _CORROBORATION_MIN) -> tuple[bool, int, str]:
    """(corroborated?, match_len, excerpt) — WEB-011 실질 대조 결과 + the verbatim
    excerpt to cite (verbatim substring of BOTH the official content and pv.text)."""
    n, excerpt = _longest_common_excerpt(web_content, pv_text)
    return (n >= min_len), n, excerpt


@dataclass
class ScoredCandidate:
    result: TavilyResult
    snapshot: SourceSnapshot
    officiality: float
    freshness: float            # WEB-012: 최신성 (web 게시 recency)
    issue_relevance: float
    applicable_validity: float  # WEB-012: 적용시점 유효성 (별도 신호)
    authority_corroborated: bool          # WEB-011: 실질 원문 대조 통과 여부
    corroboration_len: int                # 법령 원문과 공유한 최장 verbatim 길이
    corroboration_excerpt: str            # 그 verbatim 발췌 (web 인용 quote 후보)
    authority_rank: int
    promotable: bool
    reason: str

    @property
    def combined(self) -> float:
        # ordering only (best promoted candidate). NOT a rubric score. Officiality &
        # applicable-validity dominate; freshness/relevance break ties. Authority rank
        # (lower=better) and 원문 대조 강도(공유 본문 길이) are the final tie-breaks so
        # the page that actually carries 법령 원문(law.go.kr) wins.
        return (
            2.0 * self.officiality
            + 2.0 * self.applicable_validity
            + 1.0 * self.issue_relevance
            + 0.5 * self.freshness
            + 0.001 * min(self.corroboration_len, 1000)
            - 0.1 * self.authority_rank
        )


# --------------------------------------------------------------------------- #
# Pipeline result objects
# --------------------------------------------------------------------------- #
@dataclass
class PromotedSource:
    """⑧ A web candidate PROMOTED to an authority source object (WEB-011): official
    original + provenance + cross-checked against the 법령 원문 (channel ①)."""

    candidate: ScoredCandidate
    snapshot: SourceSnapshot
    official_content: str
    lookup: ProvisionLookupResult     # the authoritative version it was cross-checked TO

    @property
    def provision_version(self) -> ProvisionVersion:
        return self.lookup.provision_version


@dataclass
class WebSourceAnswer:
    """The channel-③ output for one web query."""

    scored_candidates: list[ScoredCandidate]
    promoted: Optional[PromotedSource]
    abstained: bool
    research: Optional[ResearchLiteAnswer]      # reused slice-① generator (source_type=WEB)
    web_claim: Optional[Claim]
    web_citation: Optional[Citation]            # SOURCE_SNAPSHOT provenance citation
    answer_text: str
    review_warnings: list[str] = field(default_factory=list)
    conflict_flags: list[str] = field(default_factory=list)
    registry: SourceRegistry = field(default_factory=SourceRegistry)

    @property
    def source_objects(self) -> list[object]:
        objs: list[object] = []
        if self.research is not None:
            objs.extend(self.research.bundle.source_objects)   # pv + ① snapshot
        if self.promoted is not None:
            objs.append(self.promoted.snapshot)                # web snapshot
        return objs

    @property
    def claims(self) -> list[Claim]:
        cl: list[Claim] = list(self.research.claims) if self.research else []
        if self.web_claim is not None:
            cl.append(self.web_claim)
        return cl

    @property
    def citations(self) -> list[Citation]:
        ci: list[Citation] = list(self.research.citations) if self.research else []
        if self.web_citation is not None:
            ci.append(self.web_citation)
        return ci

    @property
    def llm(self):
        return self.research.llm if self.research else None


# --------------------------------------------------------------------------- #
# The pipeline
# --------------------------------------------------------------------------- #
ABSTAIN_NOTE = (
    "[웹 단독 단정 금지] 공식 출처에서 승격(법령 원문 대조)된 근거가 없어 결론을 보류합니다. "
    "웹 검색 결과는 참고·동향으로만 표기하며, 회계사(CPA)·법령/예규 권위 소스 확인이 필요합니다."
)


class WebResearchPipeline:
    """Runs the 8-step web-research pipeline for one query.

    ``tavily`` / ``law_source`` / ``llm_client`` are injectable so adversarial tests
    can feed a blog-injected candidate set, a missing law cross-check, or an empty
    LLM fixture through the SAME path and prove the pipeline excludes / abstains /
    fails-closed (anti-gaming evidence)."""

    def __init__(self, tavily=None, law_source=None) -> None:
        self._tavily = tavily or default_tavily_client()
        self._law = law_source or default_law_source()

    # -- ②③④⑤⑥ search → snapshots → policy → score ---------------------- #
    def gather(self, *, law_name: str, article_label: str, as_of_date: date,
               issue: str, tax_type: str = "법인세",
               extra_candidates: Optional[list[TavilyResult]] = None) -> tuple[list[ScoredCandidate], ProvisionLookupResult]:
        plan = plan_queries(law_name=law_name, article_label=article_label,
                            as_of_date=as_of_date, issue=issue, tax_type=tax_type)
        # ③ Search (Tavily, official-biased include_domains = 사전 정책 WEB-002/003)
        resp = self._tavily.search(plan.primary, include_domains=OFFICIAL_DOMAINS)
        retrieved_at = resp.retrieved_at
        results = list(resp.results)
        if extra_candidates:                 # adversarial injection point (tests)
            results = results + list(extra_candidates)

        # ① cross-check authority resolved up front (WEB-011 대조 대상)
        auth_lookup = self._law.lookup_provision(law_name, article_label, as_of_date)
        pv = auth_lookup.provision_version
        subject = _provision_subject(pv.text)

        scored: list[ScoredCandidate] = []
        for i, r in enumerate(results):
            snap = snapshot_from_result(r, idx=i, retrieved_at=retrieved_at)
            # ⑤ Source Policy 사후 (WEB-007): re-check the RETURNED url. A mirror/blog
            # that slipped through include_domains is rejected here.
            official = official_domain_of(r.url) is not None and not any(
                m in (r.url or "").lower() for m in _UNOFFICIAL_MARKERS
            )
            officiality = 1.0 if official else 0.0
            freshness = _freshness(snap)
            app_valid, app_reason = _applicable_validity(
                snapshot=snap, result=r, pv=pv, as_of=as_of_date
            )
            relevance = _issue_relevance(
                r, law_name=law_name, article_label=article_label, issue=issue, subject=subject
            )
            # WEB-011 대조 (codex P0): the page must carry a verbatim chunk of the ①
            # ProvisionVersion text — REAL 원문 대조, not mere token presence. ① has
            # already resolved the authoritative version, so this confirms the
            # official page actually contains the statute it claims to.
            corro_ok, corro_len, corro_excerpt = content_corroborated(r.content, pv.text)
            corroborated = official and corro_ok
            promotable = bool(officiality > 0 and corroborated and app_valid >= 1.0
                              and snap.content_hash and snap.publisher and corro_excerpt)
            dom = official_domain_of(r.url)
            reason = (
                f"공식={official} 원문대조={corroborated}(공유 {corro_len}자) "
                f"적용시점={app_valid:.0f}({app_reason})"
                if officiality else "비공식 도메인 — 사후 정책 배제(WEB-004)"
            )
            scored.append(ScoredCandidate(
                result=r, snapshot=snap, officiality=officiality, freshness=freshness,
                issue_relevance=relevance, applicable_validity=app_valid,
                authority_corroborated=corroborated, corroboration_len=corro_len,
                corroboration_excerpt=corro_excerpt,
                authority_rank=_DOMAIN_AUTHORITY.get(dom, 9),
                promotable=promotable, reason=reason,
            ))
        return scored, auth_lookup

    # -- ⑧ promote ------------------------------------------------------- #
    def promote(self, scored: list[ScoredCandidate], auth_lookup: ProvisionLookupResult) -> Optional[PromotedSource]:
        promotable = [c for c in scored if c.promotable]
        if not promotable:
            return None
        best = max(promotable, key=lambda c: (c.combined, -c.authority_rank, c.snapshot.snapshot_id))
        return PromotedSource(
            candidate=best, snapshot=best.snapshot,
            official_content=best.result.content, lookup=auth_lookup,
        )

    # -- ⑦⑨ build the WEB SourceAnswer ----------------------------------- #
    def run(self, *, question_text: str, law_name: str, article_label: str,
            as_of_date: date, issue: str, tax_type: str = "법인세",
            high_risk: bool = False, basis_kind: BasisKind = BasisKind.FISCAL_YEAR,
            source_answer_id: str, answer_run_id: str,
            llm_client: Optional[LLMClient] = None,
            registry: Optional[SourceRegistry] = None,
            extra_candidates: Optional[list[TavilyResult]] = None) -> WebSourceAnswer:
        scored, auth_lookup = self.gather(
            law_name=law_name, article_label=article_label, as_of_date=as_of_date,
            issue=issue, tax_type=tax_type, extra_candidates=extra_candidates,
        )
        promoted = self.promote(scored, auth_lookup)
        reg = registry or SourceRegistry()

        # docs/06 §9 웹 단독 단정 금지: with NO promoted official source, ABSTAIN.
        if promoted is None:
            return WebSourceAnswer(
                scored_candidates=scored, promoted=None, abstained=True,
                research=None, web_claim=None, web_citation=None,
                answer_text=f"[법령 앵커 — 채널 ③] {ABSTAIN_NOTE}",
                review_warnings=[ABSTAIN_NOTE], registry=reg,
            )

        # ⑨ reuse the slice-① generator, channel ③ / source_type=WEB. The legal
        # reasoning is anchored to the AUTHORITATIVE pv (version-correct), grounded
        # only in PUBLIC statute text + the question (L0 — no client material).
        research = generate_research_answer(
            lookup=auth_lookup, question_text=question_text,
            client_id="client_eval", answer_run_id=answer_run_id,
            source_answer_id=source_answer_id,
            source_type_label=(auth_lookup_source_type(auth_lookup)),
            high_risk=high_risk, basis_kind=basis_kind,
            answer_source_type=SourceType.WEB, channel_label="③",
            llm_client=llm_client,
        )
        reg.register_all(research.bundle.source_objects)
        reg.register(promoted.snapshot)

        # web-provenance citation → the promoted SourceSnapshot (Citation=소스객체).
        # The quote is the verbatim 원문 대조 excerpt — a contiguous chunk shared by
        # the OFFICIAL web content AND the authoritative ① provision (codex P0-2): it
        # is a substring of the snapshot content (the web source actually carries it)
        # AND of pv.text (matches the law original). The snapshot carries the web
        # url/publisher/retrieved_at/content_hash (WEB-011 provenance).
        pv = promoted.provision_version
        quote = promoted.candidate.corroboration_excerpt.strip()
        quote = quote[:280] + "…" if len(quote) > 280 else quote
        web_citation = Citation(
            citation_id=f"cit_{source_answer_id}_web",
            source_answer_id=source_answer_id,
            source_kind=SourceKind.SOURCE_SNAPSHOT,
            source_object_id=promoted.snapshot.snapshot_id,
            claim_span="web-official-provenance",
            source_locator=promoted.snapshot.url,
            quote=quote,
            applicable_basis=ApplicableBasis(basis_kind=basis_kind, as_of_date=as_of_date),
            support_type="DIRECT",
            authority_rank=promoted.candidate.authority_rank,
        )
        reg.require_citation(web_citation)
        web_claim = Claim(
            claim_id=f"claim_{source_answer_id}_web",
            source_answer_id=source_answer_id,
            proposition=(
                f"위 결론의 공식 출처는 {promoted.snapshot.publisher}"
                f"({promoted.snapshot.url})에서 확인되었고, 법령 원문(채널 ①, {law_name} "
                f"{article_label} 시행 {pv.effective_from:%Y-%m-%d} 버전)과 대조되어 승격되었다."
            ),
            claim_span="web-official-provenance",
            citation_ids=[web_citation.citation_id],
        )

        # ⑦ conflict flag (light; full 종합은 slice ④): web vs ① version subject.
        conflicts: list[str] = []
        # (promotion already enforced applicable-validity, so no version conflict on
        #  the promoted source; non-promoted stale candidates stay 참고/동향.)

        prov_note = (
            f"\n■ 공식 출처(승격, 채널 ③): {promoted.snapshot.publisher} — {promoted.snapshot.url}\n"
            f"  (retrieved_at={promoted.snapshot.retrieved_at:%Y-%m-%d}, "
            f"content_hash={promoted.snapshot.content_hash[:12]}…, 법령 원문 대조 완료)"
        )
        non_promoted = [c for c in scored if not c.promotable and c.officiality > 0]
        if non_promoted:
            prov_note += (
                f"\n■ 참고·동향(미승격 {len(non_promoted)}건): 공식이나 시점/대조 미충족 — "
                f"결론 근거 아님(참고만)."
            )
        answer_text = research.answer_text + prov_note

        return WebSourceAnswer(
            scored_candidates=scored, promoted=promoted, abstained=False,
            research=research, web_claim=web_claim, web_citation=web_citation,
            answer_text=answer_text,
            review_warnings=list(research.review_warnings),
            conflict_flags=conflicts, registry=reg,
        )


def auth_lookup_source_type(lookup: ProvisionLookupResult) -> str:
    """The authority_rank label for the cited provision (법률 default)."""
    return "법률"


def default_pipeline(web_fixtures_dir=None, law_fixtures_dir=None) -> WebResearchPipeline:
    tavily = default_tavily_client(web_fixtures_dir) if web_fixtures_dir else default_tavily_client()
    law = default_law_source(law_fixtures_dir) if law_fixtures_dir else default_law_source()
    return WebResearchPipeline(tavily=tavily, law_source=law)
