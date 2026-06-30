"""src/orchestrator.py — TIW Orchestrator (설계서 §4-1 업무흐름 · §4-2 아키텍처).

Chains the 6 completed slices into ONE live end-to-end run — "새 질문 → 검토패키지
DOCX" — following the §4-1 flow:

  Intake(자료수집·결손/한계 고지)            ← company fixture (deterministic)
    → 쟁점 도출                              ← TB 계정 → 조문 매핑
    → 3소스 Research (각각 독립 SourceAnswer):
        ① law_anchor   (src.legal_research / src.law_anchor — channel ①, LAW_MCP)
        ② internal_rag (src.internal_rag    — channel ②, INTERNAL_RAG, 테넌트 격리)
        ③ web_research (src.web_research     — channel ③, WEB, 공식소스 승격)
    → Synthesis (src.synthesis — ConflictResolution, 권위 위계·시점)
    → Risk 식별                              ← research.risks + 보조 쟁점
    → Strategy (src.strategy — 보수/중립/적극 선택지, 인용=회수 버전객체)
    → Evidence (쟁점 ↔ 증빙 최소)
    → Draft (src.draft — DraftPackageData → 11목차 DOCX)

미해소 충돌·고위험은 검토항목(src.review_items)으로 승격된다.

MODE TOGGLE (live ⟂ replay):
  * ``replay`` (default) — hermetic: LLM/embedding/web/law all replay from
    ``tests/fixtures/`` (NO network, NO key). Deterministic.
  * ``live`` — the orchestrator's OWN new LLM(gen+strategy) + embedding(model2vec)
    calls are made LIVE and RECORDED (additive new fixture keys); the SHARED
    law bodies + official web content REPLAY from prior live recordings (the same
    record/replay pattern every slice uses) so no existing fixture is overwritten.

INVARIANTS (강제):
  * 인용 검증 — every package citation is a version source object verified through a
    ``SourceRegistry`` (날조 차단, OUT-003 via ``src.draft.validate_draft_package``).
  * HITL — a 고객 전달본 needs an approving ``ReleaseAuthorization`` (OUT-004/AGT-008);
    without it only the 내부 검토본 is produced (fail-closed) + guidance.
  * 테넌트 격리 — the client_id isolation key is propagated into the RAG ``TenantScope``
    and every client-scoped artifact (SEC-002/003).
  * fail-closed — a missing/mismatched fixture in replay raises (never a silent pass).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Optional

from contract.base import (
    BasisKind,
    ConfidentialityLevel,
    ScopeType,
    SourceAnswerStatus,
    SourceType,
)
from contract.cluster_a_tenancy import RoleAssignment, RoleName
from contract.cluster_f_qa import Citation, SourceAnswer
from contract.cluster_h_review import GateType, ReleaseAuthorization
from rules.tax_law_mapping import (  # ORCH-015 다세목 매핑 레지스트리(변경①)
    article_by_issue,
    law_name_for,
    tax_type_for,
)
from src.ai.law_data_source import LawSourceError, default_law_source
from src.ai.llm_client import LLMClient, LLMConfig, default_llm_client
from src.chunking import chunk_client_doc, chunk_provision
from src.draft import (
    ChannelResult,
    DraftPackageData,
    InputMaterial,
    IssueMemo,
    OpportunityItem,
    RiskItem,
    StrategyOption,
    build_client_deliverable_docx,
    build_review_package_docx,
    draft_package_to_fixture,
    validate_draft_package,
)
from src.hitl import HitlWorkflow, TenantBoundaryError
from src.internal_rag import InternalRagIndex, RagAnswer
from src.isolation import IsolationError
from src.law_anchor import REVIEW_WARNING, build_law_source_answer
from src.legal_research import (
    ResearchGenerationError,
    ResearchLiteAnswer,
    generate_research_answer,
)
from src.review_items import generate_review_items
from src.source_registry import CitationVerificationError, SourceRegistry
from src.strategy import StrategyAgent, StrategyResult
from src.synthesis import SourceContribution, SynthesisEngine, SynthesisResult
from src.web_research import WebResearchPipeline, WebSourceAnswer

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPANY_FIXTURE = (
    _REPO_ROOT / "tests" / "fixtures" / "company" / "A제조_2026.json"
)

# Lookup at the 시행일 버전(efYd) the law fixtures are recorded on; as-of (귀속연도)
# is the company FY. The 2024 시행버전이 FY2026 기준 in-force 버전이다(ef 2024 ≤ 2026).
_LOOKUP_DATE = date(2024, 1, 1)

# TB account 의 issue_key → (조문, 조문제목, 표시제목) 매핑 (쟁점 도출 — deterministic).
# ORCH-015(변경①): 코드 하드코딩 대신 rules/tax_law_mapping.yaml 레지스트리에서 로드해
# 세목·쟁점→법령을 일반화한다(법인세 한 세목에 고정 ✕). 법인세 항목은 기존 하드코딩과
# 문자 단위 동일 → 기존 슬라이스 회귀 0.
_ARTICLE_BY_ISSUE: dict[str, tuple[str, str, str]] = article_by_issue()
# 기본 세목(법인세)의 법령명. 쟁점별 법령명은 레지스트리(law_name_for)로 조회한다 —
# 소득세·부가세 등 비-법인세 세목 조회 시 사용(현재 데모 fixture 는 전부 법인세).
_LAW_NAME = "법인세법"

# 질문에서 주쟁점을 식별하는 키워드(쟁점별). 질문이 특정 쟁점을 명시하면 그 쟁점을 주쟁점으로
# 승격하고, 명시가 없으면 최고위험(기업업무추진비) 우선(데모 정책). 잘못된 주쟁점 고정 방지.
_ISSUE_QUERY_TERMS: dict[str, tuple[str, ...]] = {
    "기업업무추진비": ("기업업무추진비", "접대비"),
    "기부금": ("기부금",),
    "업무용승용차": ("업무용승용차", "업무용 승용차", "승용차", "운행기록부"),
    "지급이자": ("지급이자", "가지급금", "인정이자"),
}

# 쟁점별 추가 요청 자료(증빙) — 실제 식별된 쟁점에만 해당 항목을 요청한다(접대비/승용차
# 자료를 무관한 쟁점에 무조건 요구하던 오류 차단). `_EVIDENCE_GENERIC`는 전 쟁점 공통.
_EVIDENCE_BY_ISSUE: dict[str, str] = {
    "기업업무추진비": "접대비 적격증빙(법인카드 전표·세금계산서) 및 원장 매칭 명세 — 손금 인정 요건 검토용",
    "기부금": "기부금 영수증·기부처 적격성(법정/지정기부금) 확인 자료 — 한도·이월공제 검토용",
    "업무용승용차": "업무용 승용차 운행기록부 — 업무사용비율·차량 관련비용 손금 한도 검토용",
    "지급이자": "차입금 명세·가지급금 잔액 명세 — 지급이자 손금불산입 검토용",
}
_EVIDENCE_GENERIC = "이사회의사록·주요 계약서 — 거래 업무관련성 소명자료"
# Web channel reuses the recorded 제25조 기업업무추진비 official-source fixture (as-of
# 2024 so plan_queries(year=2024) matches the recorded Tavily query key).
_WEB_AS_OF = date(2024, 1, 1)

# OUT-007(변경②): 채널 라벨 → 표시용 소스명(검토패키지 §8 채널별 독립 결과).
_CHANNEL_SOURCE_LABEL: dict[str, str] = {
    "①": "①법령MCP", "②": "②내부RAG(실무서)", "③": "③공식웹",
}

# Invariant-critical failures that must NEVER be swallowed by a graceful-degrade
# branch (in ANY mode): a tenant isolation breach, a fabricated/unverifiable
# citation, or a tenant-boundary violation. A research channel may degrade to a
# coverage gap on an OPERATIONAL error (live network/key), but never on one of
# these — re-raise so the run fails closed (TENANT_LEAK/FABRICATED_CITATION=0).
_NEVER_SWALLOW = (IsolationError, CitationVerificationError, TenantBoundaryError)


# --------------------------------------------------------------------------- #
# In-process LLM memoization (determinism across channels)
# --------------------------------------------------------------------------- #
class _MemoLLMClient:
    """Wraps an ``LLMClient`` and MEMOIZES by (max_tokens, system, user).

    Channels ①②③ ground on the SAME 조문 본문 + the SAME question, so their
    ``generate_research_answer`` prompt is BYTE-IDENTICAL — the same LLM request
    key. Without memoization a LIVE run would issue 3 separate live calls (3
    different stochastic completions) while the recorded manifest keeps only the
    LAST — so the live DOCX would differ from the replayed one. Caching makes the
    one shared completion authoritative: ONE live call, ONE fixture, and live DOCX
    == replay DOCX (deterministic). Strategy's prompt differs → its own call."""

    def __init__(self, inner: LLMClient) -> None:
        self._inner = inner
        self._cache: dict[tuple, object] = {}

    def complete(self, *, system: str, user: str, tag: str = "llm",
                 max_tokens: Optional[int] = None):
        key = (max_tokens, system, user)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        resp = self._inner.complete(system=system, user=user, tag=tag, max_tokens=max_tokens)
        self._cache[key] = resp
        return resp

    @property
    def calls(self):
        return self._inner.calls

    @property
    def total_cost_usd(self) -> float:
        return self._inner.total_cost_usd

    @property
    def total_tokens(self) -> tuple[int, int]:
        return self._inner.total_tokens


# --------------------------------------------------------------------------- #
# Inputs / outputs
# --------------------------------------------------------------------------- #
@dataclass
class CompanyProfile:
    """The Intake fixture — a company's collected materials + accounts (§4-1-0)."""

    client_id: str
    matter_id: str
    company_name: str
    fiscal_year: str
    as_of_date: date
    high_risk: bool
    review_scope: str
    industry: str
    default_question: str
    trial_balance: list[dict]
    prior_year: dict
    materials: list[dict]
    internal_memo: dict

    @staticmethod
    def from_fixture(path: str | Path) -> "CompanyProfile":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return CompanyProfile(
            client_id=data["client_id"],
            matter_id=data["matter_id"],
            company_name=data["company_name"],
            fiscal_year=data["fiscal_year"],
            as_of_date=date.fromisoformat(data["as_of_date"]),
            high_risk=bool(data.get("high_risk", True)),
            review_scope=data["review_scope"],
            industry=data.get("industry", ""),
            default_question=data.get("default_question", ""),
            trial_balance=list(data.get("trial_balance", [])),
            prior_year=dict(data.get("prior_year", {})),
            materials=list(data.get("materials", [])),
            internal_memo=dict(data.get("internal_memo", {})),
        )


@dataclass
class OrchestratorResult:
    package: DraftPackageData
    titles: dict[str, str]
    articles: dict[str, str]
    docx_path: Optional[Path]
    is_client_deliverable: bool
    synthesis: Optional[SynthesisResult]
    strategy: Optional[StrategyResult]
    contributions: list[SourceContribution]
    log: list[str] = field(default_factory=list)

    def to_fixture(self) -> dict:
        return draft_package_to_fixture(self.package, titles=self.titles, articles=self.articles)


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
class Orchestrator:
    """Drives the §4-1 chain. ``mode`` selects live(record)/replay transports."""

    def __init__(
        self,
        *,
        mode: str = "replay",
        llm_client: Optional[LLMClient] = None,
        embedder: Optional[object] = None,
        law_source: Optional[object] = None,
        web_pipeline: Optional[WebResearchPipeline] = None,
    ) -> None:
        if mode not in ("live", "replay"):
            raise ValueError(f"mode must be 'live' or 'replay', got {mode!r}")
        self.mode = mode
        self._record_embedder = None
        self.llm = _MemoLLMClient(llm_client or self._build_llm_client(mode))
        self.embedder = embedder if embedder is not None else self._build_embedder(mode)
        # law + web ALWAYS replay (shared bodies / official content recorded once) —
        # never overwritten, so existing slice fixtures stay byte-identical (회귀 0).
        self.law = law_source or default_law_source()
        self.web = web_pipeline or WebResearchPipeline(law_source=self.law)
        self.engine = SynthesisEngine()
        self.strategy_agent = StrategyAgent(self.llm)
        self.log: list[str] = []

    # -- transport construction ------------------------------------------- #
    def _build_llm_client(self, mode: str) -> LLMClient:
        if mode == "live":
            from src.ai.llm_client import DEFAULT_LLM_FIXTURES_DIR, RecordingLLMTransport
            config = LLMConfig.from_vendors()
            return LLMClient(config=config,
                             transport=RecordingLLMTransport(config, DEFAULT_LLM_FIXTURES_DIR))
        return default_llm_client()

    def _build_embedder(self, mode: str):
        if mode == "live":
            from src.ai.embedding_client import CachedEmbedder, Model2VecEmbedder
            emb = CachedEmbedder(backend=Model2VecEmbedder(), record=True)
            self._record_embedder = emb
            return emb
        from src.ai.embedding_client import default_rag_embedder
        return default_rag_embedder()

    def _say(self, line: str) -> None:
        self.log.append(line)

    # -- lookups ---------------------------------------------------------- #
    def _lookup(self, law_name: str, article: str, as_of: date):
        # ORCH-015(변경①): 법령명을 쟁점별로 받는다(하드코딩 _LAW_NAME 제거) — 소득세 등
        # 비-법인세 쟁점은 자기 세법으로 조회한다. 미녹화 세법은 law source 가 fail-closed.
        lk = self.law.lookup_provision(law_name, article, _LOOKUP_DATE)
        return replace(lk, as_of_date=as_of)

    # ------------------------------------------------------------------ #
    # MAIN
    # ------------------------------------------------------------------ #
    def run(
        self,
        *,
        company: CompanyProfile,
        question: str,
        out_path: Optional[str | Path] = None,
        audience: str = "internal",
        approve_demo: bool = False,
        write_docx: bool = True,
    ) -> OrchestratorResult:
        self.log = []
        as_of = company.as_of_date
        registry = SourceRegistry()

        # -- ① Intake (자료 수집·결손/한계 고지) ----------------------------- #
        materials, deficits, limits = self._intake(company)
        self._say(f"[Intake] {company.company_name} {company.fiscal_year} — 자료 "
                  f"{sum(1 for m in materials if m.status=='수집')}/{len(materials)} 수집, "
                  f"결손/모름/없음 {len(deficits)}건 고지.")

        # -- 쟁점 도출 (TB 계정 → 조문; 질문이 명시한 쟁점을 주쟁점으로) ----- #
        issues = self._spot_issues(company, question)
        primary = issues[0]
        self._say(f"[쟁점 도출] {len(issues)}개 쟁점 — 주쟁점: {primary['title']} "
                  f"({primary['law_name']} {primary['article']}).")

        # -- 3소스 Research (각각 독립 SourceAnswer) ----------------------- #
        primary_lookup = self._lookup(primary["law_name"], primary["article"], as_of)
        contributions, primary_research, web_answer = self._three_source_research(
            company=company, question=question, primary=primary,
            primary_lookup=primary_lookup, as_of=as_of, registry=registry,
        )

        # -- Synthesis (3소스 종합 — ConflictResolution) ------------------- #
        synthesis = self._synthesize(
            contributions=contributions, primary_research=primary_research,
            as_of=as_of, company=company, primary=primary,
        )
        unresolved = self._unresolved_conflicts(synthesis, primary=primary)

        # -- 패키지 인용(버전 객체) — 주쟁점 + 보조 쟁점 (deterministic) ----- #
        citations, titles, articles, by_issue, source_objects = self._build_citations(
            company=company, issues=issues, as_of=as_of,
        )
        primary_cit = self._cmap(citations)[by_issue[primary["issue_key"]]]
        registry.register_all(source_objects)

        # -- Risk 식별 / 절세 기회 / 쟁점 메모 (Evidence) ------------------ #
        risks = self._risks(issues, by_issue, citations, primary_research)
        opportunities = self._opportunities(issues, by_issue, citations)
        issue_memos = self._issue_memos(issues, by_issue, citations, unresolved)

        # -- Strategy (보수/중립/적극 선택지, 인용=회수 버전객체) ----------- #
        strategy = self.strategy_agent.generate(
            lookup=primary_lookup, issue=primary["title"],
            synthesis_opinion=synthesis.synthesis.opinion_text,
            risks=[r.title for r in risks],
            citation=primary_cit, registry=registry,
            anchor_quote=primary_cit.quote, high_risk=company.high_risk,
            tag=f"strategy_{company.matter_id}_{primary['issue_key']}",
        )
        self._say(f"[Strategy] 보수/중립/적극 {len(strategy.options)}종 선택지 생성 — "
                  f"인용 검증 OK(버전객체), grounding={'OK' if strategy.entailment_supported else '부분'}.")

        # -- 검토항목 (HALU-008) ------------------------------------------- #
        review_items = generate_review_items(
            answer=primary_research, client_id=company.client_id, matter_id=company.matter_id,
            high_risk=company.high_risk, aggressive=True,
            unresolved_conflicts=unresolved, data_limits=deficits, prefix="ri_orch",
        )

        # -- Draft (DraftPackageData → 11목차) ----------------------------- #
        # 요약에 "어떤 출처가 실제로 응답했는지"를 정직하게 반영하기 위해 응답 채널 집합 전달
        # (웹이 보류했는데 ③웹 회수를 주장하는 거짓 요약 차단).
        answered_channels = {c.channel_label for c in contributions if c.answered}
        package = self._assemble_package(
            company=company, question=question, primary=primary, materials=materials,
            limits=limits, risks=risks, opportunities=opportunities, strategy=strategy,
            issue_memos=issue_memos, citations=citations, source_objects=source_objects,
            review_items=review_items,
            additional_requests=self._evidence_requests(issues, deficits),
            answered_channels=answered_channels, synthesis=synthesis,
            channel_results=self._channel_results(contributions),  # OUT-007(변경②)
        )

        # -- OUT-003 하드게이트 — 무인용 단정/날조 차단은 DOCX 출력 여부와 무관하게 항상
        #    검증한다(write_docx=False 로 패키지만 받아가는 호출에서도 fail-closed).
        validate_draft_package(package)

        # -- render DOCX (internal default; client needs HITL proof) ------- #
        docx_path, is_client = self._render(
            package=package, titles=titles, articles=articles, out_path=out_path,
            audience=audience, approve_demo=approve_demo, company=company,
            write_docx=write_docx,
        )

        # -- live: persist the recorded embedding cache -------------------- #
        if self.mode == "live" and self._record_embedder is not None:
            self._record_embedder.save()
            self._say(f"[live] 임베딩 캐시 저장({len(self._record_embedder)} 벡터) + "
                      f"LLM 호출 {len(self.llm.calls)}회(~${self.llm.total_cost_usd:.4f}).")

        return OrchestratorResult(
            package=package, titles=titles, articles=articles, docx_path=docx_path,
            is_client_deliverable=is_client, synthesis=synthesis, strategy=strategy,
            contributions=contributions, log=list(self.log),
        )

    # ================================================================== #
    # Steps
    # ================================================================== #
    def _intake(self, company: CompanyProfile):
        materials = [
            InputMaterial(m["name"], m.get("status", "모름"), m.get("confidentiality", "L2"))
            for m in company.materials
        ]
        deficits = [
            f"{m.name}({m.status})" for m in materials if m.status in ("없음", "모름", "결손")
        ]
        limits = [
            "자료 결손(없음/모름/결손) 항목 관련 결론에는 '자료한계' 꼬리표가 부착됩니다(INTK-004).",
            f"적용시점은 {company.fiscal_year}(귀속연도) 기준 가정 — 실제 거래일 확정 필요(PROV-013).",
        ]
        return materials, deficits, limits

    def _spot_issues(self, company: CompanyProfile, question: str = "") -> list[dict]:
        """TB 계정의 issue_key → 조문 매핑(deterministic). 주쟁점은 **질문이 명시한 쟁점**을
        우선하고, 명시가 없으면 최고위험(기업업무추진비)을 우선한다(질문과 무관한 주쟁점
        고정 → 잘못된 요약 방지)."""
        issues: list[dict] = []
        for row in company.trial_balance:
            key = row.get("issue_key")
            if key in _ARTICLE_BY_ISSUE:
                article, art_title, title = _ARTICLE_BY_ISSUE[key]
                issues.append({
                    "issue_key": key, "article": article, "article_title": art_title,
                    "title": title, "account": row.get("account", ""),
                    "amount": row.get("amount"), "note": row.get("note", ""),
                    # ORCH-015(변경①): 세목별 법령명·세목을 레지스트리에서 주입 →
                    # 하드코딩 _LAW_NAME 대신 이 값으로 조회(소득세 쟁점이 법인세법으로
                    # 잘못 조회되는 것을 방지; codex 적발). 법인세 쟁점은 법인세법/법인세 동일.
                    "law_name": law_name_for(key) or _LAW_NAME,
                    "tax_type": tax_type_for(key) or "법인세",
                })
        if not issues:
            raise ValueError("쟁점 도출 실패: 회사 자료에 매핑 가능한 손금 계정이 없음")
        q = question or ""

        def _named_in_question(key: str) -> bool:
            return any(term in q for term in _ISSUE_QUERY_TERMS.get(key, (key,)))

        # 1차 키: 질문이 명시한 쟁점(0) 우선, 2차 키: 최고위험(기업업무추진비, 0) 우선,
        # 3차 키: 원래 TB 순서(stable). 데모 질문은 기업업무추진비/접대비를 명시 → 동일 순서.
        issues.sort(key=lambda i: (
            not _named_in_question(i["issue_key"]),
            i["issue_key"] != "기업업무추진비",
        ))
        return issues

    def _three_source_research(
        self, *, company: CompanyProfile, question: str, primary: dict,
        primary_lookup, as_of: date, registry: SourceRegistry,
    ) -> tuple[list[SourceContribution], ResearchLiteAnswer, Optional[WebSourceAnswer]]:
        ar = f"ar_{company.matter_id}"
        # stance 는 주쟁점에서 도출한다. 데모 주쟁점(기업업무추진비)은 기존 녹화 fixture 키와
        # 동일한 문자열을 유지(stance → 종합 opinion → strategy 프롬프트로 전파되므로 replay
        # 결정성 보존)하고, 다른 쟁점이 주쟁점이면 해당 쟁점 기준으로 정정한다(접대비 stance 오용 차단).
        if primary["issue_key"] == "기업업무추진비":
            stance = "기업업무추진비 한도초과·적격증빙 미수취분 손금불산입(법령 원문 기준)"
        else:
            stance = f"{primary['title']} 한도·요건 위반분 손금불산입(법령 원문 기준)"
        topic = f"{primary['issue_key']}_손금한도"
        contributions: list[SourceContribution] = []

        # ① law_anchor (channel ①, LAW_MCP) — PRIMARY 법리 (generate_research_answer)
        primary_research = generate_research_answer(
            lookup=primary_lookup, question_text=question, client_id=company.client_id,
            answer_run_id=ar, source_answer_id=f"sa_{company.matter_id}_law",
            source_type_label="법률", high_risk=company.high_risk,
            answer_source_type=SourceType.LAW_MCP, channel_label="①", llm_client=self.llm,
        )
        registry.register_all(primary_research.bundle.source_objects)
        contributions.append(self._contribution(
            primary_research, channel="①", source_type=SourceType.LAW_MCP,
            authority="법률", topic=topic, stance=stance, is_primary=True,
        ))
        self._say(f"[Research ①法令] {primary['law_name']} {primary['article']} 앵커 + 법리(인용 "
                  f"{len(primary_research.citations)}건, 검토경고={'O' if primary_research.review_warnings else 'X'}).")

        # ② internal_rag (channel ②, INTERNAL_RAG) — 테넌트 격리 회수 + 인용근거 답변
        rag = self._run_internal_rag(company, question, primary, as_of, ar)
        if rag is not None and rag.grounded and rag.answer is not None:
            registry.register_all(rag.answer.bundle.source_objects)
            contributions.append(self._contribution(
                rag.answer, channel="②", source_type=SourceType.INTERNAL_RAG,
                authority="실무서", topic=topic, stance=stance, is_primary=False,
            ))
            self._say(f"[Research ②內部RAG] 테넌트 격리 회수 {len(rag.retrieved)}건(누수 0) → "
                      f"공개 조문 grounding 답변(L3 메모 외부 LLM 미송신).")
        else:
            contributions.append(self._silent("②", SourceType.INTERNAL_RAG, "실무서", topic,
                                              f"sa_{company.matter_id}_rag", ar, company.client_id))
            self._say("[Research ②內部RAG] 회수 결과 grounding 불가 → 침묵(커버리지 갭).")

        # ③ web_research (channel ③, WEB) — 공식소스 승격(WEB-011) or abstain
        web_answer = self._run_web(company, question, primary, ar)
        if web_answer is not None and not web_answer.abstained and web_answer.research is not None:
            registry.register_all(web_answer.source_objects)
            contributions.append(self._contribution(
                web_answer.research, channel="③", source_type=SourceType.WEB,
                authority="웹", topic=topic, stance=stance, is_primary=False,
                extra_citations=([web_answer.web_citation] if web_answer.web_citation else []),
            ))
            self._say("[Research ③Web] 공식소스 승격(법령 원문 대조 완료) → provenance 인용.")
        else:
            contributions.append(self._silent("③", SourceType.WEB, "웹", topic,
                                              f"sa_{company.matter_id}_web", ar, company.client_id))
            self._say("[Research ③Web] 승격 가능한 공식근거 없음 → abstain(웹 단독 단정 금지).")

        return contributions, primary_research, web_answer

    def _run_internal_rag(self, company, question, primary, as_of, ar) -> Optional[RagAnswer]:
        store = None
        try:
            from src.ai.chroma_backend import ChromaVectorStore
            store = ChromaVectorStore(embedder=self.embedder)
            index = InternalRagIndex(store=store)
            law_set = chunk_provision(primary["law_name"], primary["article"],
                                      _LOOKUP_DATE.year, tax_type=primary["tax_type"])
            memo = company.internal_memo
            memo_chunk = chunk_client_doc(
                doc_id=memo.get("doc_id", f"memo_{company.client_id}"),
                text=memo.get("text", ""),
                client_id=company.client_id,
                confidentiality_level=ConfidentialityLevel(memo.get("confidentiality", "L3_CLIENT")),
                doc_type=memo.get("doc_type", "메모"), tax_type=memo.get("tax_type", "법인세"),
            )
            index.ingest(law_set.all_chunks + [memo_chunk])
            from src.isolation import TenantScope
            scope = TenantScope(client_id=company.client_id)
            return index.answer(
                question_text=question, scope=scope, as_of=as_of,
                source_answer_id=f"sa_{company.matter_id}_rag", answer_run_id=ar,
                run_id=f"rr_{company.matter_id}_rag", high_risk=company.high_risk,
                llm_client=self.llm,
            )
        except _NEVER_SWALLOW:
            raise  # 격리/날조/테넌트경계 위반은 어떤 모드에서도 fail-closed (절대 미삼킴).
        except Exception as exc:  # noqa: BLE001
            if self.mode == "replay":
                # hermetic replay: 누락/변조 fixture·재현불가는 결정성 붕괴 →
                # fail-closed (Invariant 5). silent degrade 금지.
                raise
            # live 한정: 운영성 실패(네트워크/키/일시)만 graceful degrade → 커버리지 갭.
            self._say(f"[Research ②內部RAG] 비활성(graceful degrade·live): "
                      f"{type(exc).__name__}: {str(exc)[:200]}")
            return None
        finally:
            if store is not None:
                store.close()

    def _run_web(self, company, question, primary, ar) -> Optional[WebSourceAnswer]:
        if primary["issue_key"] != "기업업무추진비":
            return None  # only the 제25조 official-source fixture is available
        try:
            return self.web.run(
                question_text=question, law_name=primary["law_name"],
                article_label=primary["article"], as_of_date=_WEB_AS_OF,
                issue=primary["issue_key"], tax_type=primary["tax_type"], high_risk=company.high_risk,
                source_answer_id=f"sa_{company.matter_id}_web", answer_run_id=ar,
                llm_client=self.llm,
            )
        except _NEVER_SWALLOW:
            raise  # 격리/날조/테넌트경계 위반은 어떤 모드에서도 fail-closed.
        except Exception as exc:  # noqa: BLE001
            if self.mode == "replay":
                # hermetic replay: 누락/변조 fixture(법령 replay·공식웹·LLM)는 결정성
                # 붕괴 → fail-closed (Invariant 5). silent abstain 로 가리지 않는다.
                raise
            self._say(f"[Research ③Web] 비활성(graceful degrade·live): "
                      f"{type(exc).__name__}: {str(exc)[:200]}")
            return None

    # -- contribution builders ------------------------------------------- #
    def _contribution(self, research: ResearchLiteAnswer, *, channel: str,
                      source_type: SourceType, authority: str, topic: str, stance: str,
                      is_primary: bool, extra_citations: Optional[list[Citation]] = None,
                      ) -> SourceContribution:
        citations = list(research.citations) + list(extra_citations or [])
        return SourceContribution(
            source_type=source_type, channel_label=channel, authority_label=authority,
            status=SourceAnswerStatus.ANSWERED, source_answer=research.source_answer,
            topic_key=topic, stance=stance, dispositive=True, fact_match=True,
            version_based=False, provision_version=research.provision_version,
            claims=list(research.claims), citations=citations, research=research,
            is_primary=is_primary, fabricated=False,
        )

    def _silent(self, channel, source_type, authority, topic, sa_id, ar, client_id):
        sa = SourceAnswer(
            source_answer_id=sa_id, answer_run_id=ar, source_type=source_type,
            status=SourceAnswerStatus.SILENT, answer_text="(침묵: 해당 채널 근거 없음 — 커버리지 갭)",
            client_id=client_id,
        )
        return SourceContribution(
            source_type=source_type, channel_label=channel, authority_label=authority,
            status=SourceAnswerStatus.SILENT, source_answer=sa, topic_key=topic, stance="",
            provision_version=None,
        )

    def _synthesize(self, *, contributions, primary_research, as_of, company, primary):
        synthesis = self.engine.synthesize(
            contributions=contributions, as_of_date=as_of,
            answer_run_id=f"ar_{company.matter_id}", synthesis_id=f"syn_{company.matter_id}",
            client_id=company.client_id, high_risk=company.high_risk,
            primary_research=primary_research,
        )
        answered = [c for c in contributions if c.answered]
        lineage_ok = not synthesis.untraceable_claims() and not synthesis.new_citations
        self._say(f"[Synthesis] 응답 소스 {len(answered)}/{len(contributions)} → "
                  f"{'합의(AGREE)' if not synthesis.abstained else '보류(abstain)'} · "
                  f"lineage={'100%' if lineage_ok else '검토항목 승격'} · 신규인용 {len(synthesis.new_citations)}.")
        return synthesis

    def _unresolved_conflicts(self, synthesis: SynthesisResult, *, primary: dict) -> list[str]:
        # 1차: 종합엔진이 실제로 검토 승격한 충돌만(synthesis.reconciliations 유래).
        items: list[str] = [
            r.conflict_flag.description
            for r in synthesis.reconciliations
            if r.conflict_flag is not None and r.conflict_flag.escalated_to_review
        ]
        # 2차: 접대비 적격증빙 부인 범위는 예규(과세) vs 심판례(납세자)가 실무상 미해소다.
        # 단, 이 caveat 는 **주쟁점이 실제 기업업무추진비일 때만** 승격한다(쟁점 범위 밖
        # 질문에 무관한 충돌을 주입하지 않음 — 동일 충돌은 제25조 버전객체 인용을 단
        # 쟁점 메모에도 적시되어 lineage 가 있다).
        if primary.get("issue_key") == "기업업무추진비":
            items.append(
                "접대비 적격증빙 손금 부인 범위 — 예규(과세) vs 심판례(납세자) 미해소(사실관계 의존)"
            )
        return items

    # -- deterministic version-object citations -------------------------- #
    def _build_citations(self, *, company, issues, as_of):
        citations: list[Citation] = []
        titles: dict[str, str] = {}
        articles: dict[str, str] = {}
        by_issue: dict[str, str] = {}
        source_objects: list[object] = []
        # dedup 은 (법령명, 조문) 키로 — 다세목에서 조문번호가 같아도(예: 법인세법 제22조
        # vs 소득세법 제22조) 다른 법이면 별개 인용(ORCH-015; 조문라벨 단독 dedup 오결합 차단).
        seen: dict[tuple[str, str], str] = {}
        for issue in issues:
            law_name = issue["law_name"]
            art = issue["article"]
            key = (law_name, art)
            if key in seen:
                by_issue[issue["issue_key"]] = seen[key]
                continue
            lookup = self._lookup(law_name, art, as_of)
            bundle = build_law_source_answer(
                lookup=lookup, client_id=company.client_id,
                answer_run_id=f"ar_{company.matter_id}",
                source_answer_id=f"sa_{company.matter_id}_{issue['issue_key']}",
                source_type_label="법률", matter_id=company.matter_id,
            )
            cit = bundle.citation
            citations.append(cit)
            source_objects.extend(bundle.source_objects)
            titles[cit.citation_id] = lookup.article_title
            articles[cit.citation_id] = art
            by_issue[issue["issue_key"]] = cit.citation_id
            seen[key] = cit.citation_id
        return citations, titles, articles, by_issue, source_objects

    def _cmap(self, citations: list[Citation]) -> dict[str, Citation]:
        return {c.citation_id: c for c in citations}

    def _risks(self, issues, by_issue, citations, primary_research) -> list[RiskItem]:
        cidx = self._cmap(citations)
        risks: list[RiskItem] = []
        for issue in issues:
            cid = by_issue[issue["issue_key"]]
            sev = "HIGH" if issue["issue_key"] in ("기업업무추진비",) else "MEDIUM"
            desc = (issue["note"] or f"{issue['title']} 검토 필요").strip()
            risks.append(RiskItem(
                title=f"{issue['title']} 손금불산입 리스크",
                description=f"{issue['account']} {self._won(issue.get('amount'))} — {desc}.",
                citation_ids=[cid], severity=sev,
            ))
        # 주쟁점에 생성기가 flag 한 리스크(과세논리) 1건을 추가 인용과 함께 표면화.
        # 제목은 주쟁점에서 도출(접대비 전용 제목을 다른 쟁점에 붙이지 않음 — 내용/제목 불일치 차단).
        if primary_research.risks:
            primary_issue = issues[0]
            risk_title = (
                "적격증빙 미수취분 손금 부인(과세논리)"
                if primary_issue["issue_key"] == "기업업무추진비"
                else f"{primary_issue['title']} 과세 리스크(과세논리)"
            )
            risks.insert(1, RiskItem(
                title=risk_title,
                description=primary_research.risks[0],
                citation_ids=[by_issue[primary_issue["issue_key"]]], severity="HIGH",
            ))
        return risks

    def _opportunities(self, issues, by_issue, citations) -> list[OpportunityItem]:
        ops: list[OpportunityItem] = []
        templ = {
            "기업업무추진비": ("기업업무추진비 한도 최적화",
                          "수입금액 기준 한도·문화접대비 추가한도 활용으로 손금 가능액 확대 여지."),
            "기부금": ("기부금 이월공제 활용", "당기 한도 초과 기부금의 이월공제로 차기 손금 산입 기회."),
            "업무용승용차": ("업무용 승용차 손금 한도 관리",
                        "운행기록부 작성으로 업무사용비율 인정·손금 한도 확대(자료 보완 전제)."),
            "지급이자": ("가지급금 정리·지급이자 부인 최소화",
                      "업무무관 가지급금 정리·약정이자 수령으로 지급이자 손금불산입·인정이자 익금 축소 여지."),
        }
        for issue in issues:
            t = templ.get(issue["issue_key"])
            if t:
                ops.append(OpportunityItem(t[0], t[1], citation_ids=[by_issue[issue["issue_key"]]]))
        return ops

    def _issue_memos(self, issues, by_issue, citations, unresolved) -> list[IssueMemo]:
        memos: list[IssueMemo] = []
        for i, issue in enumerate(issues):
            cid = by_issue[issue["issue_key"]]
            if issue["issue_key"] == "기업업무추진비":
                analysis = (
                    f"{issue['law_name']} {issue['article']}는 한도 초과액과 적격증빙 미수취분을 손금불산입한다. "
                    "증빙 매칭 자료가 미확인('모름')이라 부인 범위 정량화가 제한되며, 예규(과세)와 "
                    "심판례(납세자) 충돌이 미해소되어 단정하지 않고 회계사 검토로 승격한다."
                )
                esc = "H3(충돌/시점) → 미해소 충돌 단정 금지"
            elif issue["issue_key"] == "업무용승용차":
                analysis = (f"{issue['article']} 업무사용비율·한도는 운행기록부에 의존하나 운행기록부가 "
                            "결손이라 검토를 보류한다(자료한계).")
                esc = "H1(입력) → 운행기록부 결손 보완 필요"
            else:
                analysis = (f"{issue['article']} 한도 계산과 이월공제/손금불산입 잔액의 정합성을 전기 "
                            "신고서와 대조한다.")
                esc = "H2(계산) → 한도 계산 검산"
            memos.append(IssueMemo(topic=f"쟁점 {i+1}. {issue['title']}", analysis=analysis,
                                   citation_ids=[cid], escalation=esc))
        return memos

    def _evidence_requests(self, issues, deficits) -> list[str]:
        """식별된 쟁점에만 해당 증빙을 요청 + 전 쟁점 공통 거버넌스 자료(접대비/승용차 자료를
        무관한 쟁점에 무조건 요구하던 오류 차단). 순서는 주쟁점 우선(issues 정렬을 따름)."""
        reqs = [
            _EVIDENCE_BY_ISSUE[i["issue_key"]]
            for i in issues if i["issue_key"] in _EVIDENCE_BY_ISSUE
        ]
        reqs.append(_EVIDENCE_GENERIC)
        return reqs

    @staticmethod
    def _summary_texts(
        company: CompanyProfile, primary: dict,
        answered_channels: Optional[set[str]] = None,
    ) -> tuple[str, str, list[str]]:
        """주쟁점에서 도출한 (executive_summary, conclusion, recommended_order).

        접대비 전용 심화 절(예규·심판례 미해소·증빙 부인 범위)은 주쟁점이 **실제
        기업업무추진비일 때만** 포함한다. 출처 기술은 **실제로 응답한 채널만** 정직하게
        나열한다(웹이 보류했는데 ③웹 회수를 주장하지 않음)."""
        ptitle = primary["title"]
        is_meal = primary["issue_key"] == "기업업무추진비"
        meal_caveat = (
            " 적격증빙 부인 범위는 예규·심판례 충돌이 미해소되어 회계사 검토(HITL)로 승격한다."
            if is_meal else ""
        )
        # 응답 채널만 정직하게 기술(미지정이면 보수적으로 ①②만 가정).
        chans = answered_channels if answered_channels is not None else {"①", "②"}
        labels = {"①": "①법령", "②": "②내부RAG", "③": "③공식웹"}
        answered = [labels[c] for c in ("①", "②", "③") if c in chans]
        src_phrase = (
            f"{len(answered)}개 독립 출처({'·'.join(answered)})를 회수해"
            if answered else "법령 원문을 회수해"
        )
        web_note = "" if "③" in chans else " ③공식웹은 적용 가능한 공식근거가 없어 보류했다."
        # primary 는 _spot_issues 가 tax_type/law_name 을 주입하지만, 단위호출 호환을 위해
        # 누락 시 법인세 기본값으로 폴백(실제 흐름은 항상 키 보유 → 동일 출력).
        _tt = primary.get("tax_type", "법인세")
        _ln = primary.get("law_name", _LAW_NAME)
        exec_summary = (
            f"{company.company_name} {company.fiscal_year} {_tt} 검토 결과, "
            f"{ptitle}({_ln} {primary['article']}) 관련 손금불산입이 핵심 리스크다. "
            f"{src_phrase} 권위 위계·시점으로 종합했으며, 보수/중립/적극 선택지의 "
            f"세부담·과세리스크·방어가능성을 비교 제시한다.{meal_caveat}{web_note} "
            f"모든 법적 주장은 법령 원문(버전 객체) 인용을 동반하며, 결손 자료에는 자료한계 "
            f"꼬리표를 부착했다."
        )
        conclusion_tail = (
            "적격증빙 부인 범위와 업무용 승용차 한도는" if is_meal
            else "세부 적용 요건과 한도 계산은"
        )
        conclusion = (
            f"{ptitle} 손금불산입은 법령 원문으로 확정되나, {conclusion_tail} 자료 보완·회계사 "
            "판단이 선행되어야 한다. 중립적 처리를 기준안으로 제시하되 최종 선택지와 고객 전달본은 "
            "Reviewer 승인(H4·H5) 후 확정한다."
        )
        recommended_order = [
            "자료 결손 항목 보완(원장·증빙 등, H1)",
            f"{ptitle} 한도 계산 검산(H2)",
        ]
        if is_meal:
            recommended_order.append("적격증빙 부인 범위 예규·심판례 재검토(H3, 미해소 충돌)")
        recommended_order += [
            "선택지 확정 및 고위험 가드레일 검토(H4)",
            "검토패키지 사인오프·고객 전달본 생성(H5)",
        ]
        return exec_summary, conclusion, recommended_order

    def _channel_results(self, contributions: list[SourceContribution]) -> list[ChannelResult]:
        """OUT-007(변경②): 종합 *전* 의 채널별 독립 결과(①②③)를 display 모델로.

        각 채널의 SourceAnswer 를 그대로 — answered 면 답변 발췌 + 인용 pinpoint, SILENT 면
        커버리지 갭 사유를 정직하게 남긴다(합성 ✕). 채널 순서(①②③)는 입력 순서를 따른다."""
        results: list[ChannelResult] = []
        for c in contributions:
            text = (c.source_answer.answer_text or "").strip() if c.source_answer else ""
            excerpt = text[:200] + ("…" if len(text) > 200 else "")
            locators = [
                cit.source_locator
                for cit in (getattr(c, "citations", None) or [])
                if getattr(cit, "source_locator", None)
            ]
            status = c.status.value if hasattr(c.status, "value") else str(c.status)
            results.append(ChannelResult(
                channel=c.channel_label,
                source_label=_CHANNEL_SOURCE_LABEL.get(c.channel_label, c.channel_label),
                status=status, answered=bool(c.answered), answer_excerpt=excerpt,
                citation_locators=locators,
            ))
        return results

    def _assemble_package(self, *, company, question, primary, materials, limits, risks,
                          opportunities, strategy: StrategyResult, issue_memos, citations,
                          source_objects, review_items, additional_requests, synthesis,
                          channel_results: Optional[list[ChannelResult]] = None,
                          answered_channels: Optional[set[str]] = None,
                          ) -> DraftPackageData:
        # 요약/결론/권고순서는 **실제 주쟁점 + 실제 응답 출처에서 도출**한다(하드코딩된
        # 접대비 서사·거짓 웹 회수 주장을 비-데모 입력에 출력하던 오류 차단).
        exec_summary, conclusion, recommended_order = self._summary_texts(
            company, primary, answered_channels)
        return DraftPackageData(
            matter_id=company.matter_id, client_id=company.client_id,
            company_name=company.company_name, fiscal_year=company.fiscal_year,
            as_of_date=company.as_of_date, review_scope=company.review_scope,
            high_risk=company.high_risk, executive_summary=exec_summary,
            input_materials=materials, risks=risks, opportunities=opportunities,
            strategy_options=list(strategy.options), issue_memos=issue_memos,
            citations=citations, additional_requests=additional_requests,
            review_items=review_items, conclusion=conclusion,
            recommended_order=recommended_order,
            data_limits=limits, synthesis=synthesis.synthesis, source_objects=source_objects,
            channel_results=list(channel_results or []),  # OUT-007(변경②) 채널별 독립 결과
        )

    # -- render ----------------------------------------------------------- #
    def _render(self, *, package, titles, articles, out_path, audience, approve_demo,
                company, write_docx):
        if out_path is None or not write_docx:
            return None, False
        out_path = Path(out_path)
        if audience == "client":
            proof = self._client_release_proof(company) if approve_demo else None
            if proof is None:
                # fail-closed (OUT-004): no HITL proof → 내부 검토본만 + 안내.
                self._say("[HITL] 고객 전달본 차단(OUT-004/AGT-008): 승인 proof(ReleaseAuthorization) "
                          "없음 → 내부 검토본만 생성. --client 와 함께 H4·H5 승인(데모: --approve-demo)이 필요.")
                build_review_package_docx(package, out_path, titles=titles, articles=articles)
                return out_path, False
            build_client_deliverable_docx(package, out_path, release_proof=proof,
                                          titles=titles, articles=articles)
            self._say("[HITL] 고객 전달본 생성(H4·H5 승인 proof 선행, 내부 전략메모·검토항목 제외).")
            return out_path, True
        build_review_package_docx(package, out_path, titles=titles, articles=articles)
        self._say(f"[Draft] 내부 검토본 11목차 DOCX 생성 → {out_path}")
        return out_path, False

    def _client_release_proof(self, company: CompanyProfile) -> ReleaseAuthorization:
        """데모 HITL 승인 경로: Reviewer 가 H4·H5 를 승인 → ReleaseAuthorization proof.

        실제 워크플로(src.hitl)를 그대로 구동해 proof 를 구성한다(우회 생성 아님)."""
        reviewer = "user_reviewer_demo"
        ra = [RoleAssignment(
            assignment_id="ra_demo_reviewer", user_id=reviewer, role_id="role_reviewer",
            scope_type=ScopeType.MATTER, scope_id=company.matter_id, client_id=company.client_id,
        )]
        wf = HitlWorkflow(
            client_id=company.client_id, matter_id=company.matter_id,
            draft_id=f"draft_{company.matter_id}", role_assignments=ra,
            roles={"role_reviewer": RoleName.REVIEWER},
        )
        for gate in (GateType.H4_HIGH_RISK, GateType.H5_APPROVAL):
            wf.trigger(gate)
            wf.decide(gate, approver_user_id=reviewer, approved=True)
        # 공개 경로로 생성 — 교차테넌트 차단 + 미승인 게이트 재검증(fail-closed) +
        # 의무 release 감사이벤트(RELEASE_ATTEMPT)를 모두 거친 뒤 proof 를 반환한다.
        # (private _build_release_proof 직접 호출은 이 감사·재검증을 우회하므로 지양.)
        deliverable = wf.produce_client_deliverable(high_risk=company.high_risk)
        return deliverable.release_proof

    # -- small helpers ---------------------------------------------------- #
    @staticmethod
    def _won(amount) -> str:
        if not isinstance(amount, (int, float)):
            return ""
        return f"{int(amount):,}원"


def run_orchestrator(
    *, company_path: str | Path = DEFAULT_COMPANY_FIXTURE, question: Optional[str] = None,
    out_path: Optional[str | Path] = None, mode: str = "replay", audience: str = "internal",
    approve_demo: bool = False, write_docx: bool = True,
) -> OrchestratorResult:
    """Convenience entry: load the company fixture and run the §4-1 chain."""
    company = CompanyProfile.from_fixture(company_path)
    q = question or company.default_question
    orch = Orchestrator(mode=mode)
    return orch.run(company=company, question=q, out_path=out_path, audience=audience,
                    approve_demo=approve_demo, write_docx=write_docx)
