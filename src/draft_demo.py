"""src/draft_demo.py — 대표 검토패키지/Intake fixture 빌더 (결정적, 오프라인).

Assembles a CANONICAL, representative ``DraftPackageData`` (the A제조(주) 2026
법인세 데모 — §3-4) from OFFLINE law fixture replay so the DOCX test and the
frontend fixture replay identically (no LLM, no network, no wall-clock).

  * 8. 법령 근거 : 실제 버전객체 ``Citation`` (slice ① ``build_law_source_answer``
                  replay — 제25조 기업업무추진비 / 제24조 기부금 / 제27조의2 업무용
                  승용차 / 제28조 지급이자, 2024 시행버전, as-of 2026).
  * 10. 검토항목 : slice ⑤ ``src.review_items.generate_review_items`` (HALU-008).
  * 종합의견    : slice ④ ``SynthesisOpinion`` (인용 상속, 새 인용 0).

또한 화면 ① Intake 자료수집 챗(§4-1-1, INTK)의 대표 인터뷰 세션을 구성한다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import date
from typing import Optional

from contract.cluster_f_qa import Citation, SourceAnswer, SynthesisOpinion
from contract.cluster_h_review import ReviewItem
from src.ai.law_data_source import default_law_source
from src.draft import (
    ChannelResult,
    DraftPackageData,
    InputMaterial,
    IssueMemo,
    OpportunityItem,
    RiskItem,
    StrategyOption,
    draft_package_to_fixture,
)
from src.law_anchor import build_law_source_answer
from src.legal_research import ResearchLiteAnswer
from src.review_items import generate_review_items

_CLIENT = "client_amfg"
_MATTER = "matter_amfg_2026"
# 검토기준일(귀속연도) = FY2026. 법령 replay 는 시행버전 efYd(2024-01-01)에 녹화돼 있고,
# 그 2024 시행버전이 2026 기준 in-force 버전이므로 lookup 은 시행일에서 하고
# applicable_basis(as-of)만 2026 으로 rebind 한다(시점 정합: ef 2024 ≤ as-of 2026).
_AS_OF = date(2026, 1, 1)
_LOOKUP_DATE = date(2024, 1, 1)


def _lookup_inforce(law, article: str):
    """efYd 시행일에서 replay 한 뒤 as-of 를 FY2026 으로 rebind(in-force 버전 유지)."""
    lookup = law.lookup_provision("법인세법", article, _LOOKUP_DATE)
    return replace(lookup, as_of_date=_AS_OF)


# --------------------------------------------------------------------------- #
# Intake (화면 ① — §4-1-1 / INTK)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class IntakeTurn:
    role: str          # bot | user
    text: str
    status: str = ""   # 수집 | 없음 | 모름 | (사용자 발화는 "")


@dataclass
class IntakeSession:
    goal: str
    company: str
    turns: list[IntakeTurn]
    checklist: list[InputMaterial]
    closing_scope: str
    deficits: list[str]
    limits: list[str]
    early_stopped: bool = True

    def to_fixture(self) -> dict:
        return {
            "goal": self.goal,
            "company": self.company,
            "early_stopped": self.early_stopped,
            "turns": [asdict(t) for t in self.turns],
            "checklist": [asdict(m) for m in self.checklist],
            "closing_scope": self.closing_scope,
            "deficits": list(self.deficits),
            "limits": list(self.limits),
        }


def build_demo_intake() -> IntakeSession:
    """대표 Intake 인터뷰 루프(질문→업로드/없음/모름→수집·체크→충분성→마감)."""
    turns = [
        IntakeTurn("user", "A제조(주) 2026 사업연도 법인세 절세 검토를 시작해줘."),
        IntakeTurn("bot", "전기(2025) 법인세 신고서가 있나요? 한도·이월 항목 비교에 필요합니다."),
        IntakeTurn("user", "네, 전기 법인세 신고서 PDF 올렸습니다.", "수집"),
        IntakeTurn("bot", "당기 합계잔액시산표(TB)와 계정별 원장(접대비·기부금 계정)을 올려주세요."),
        IntakeTurn("user", "엑셀 TB와 접대비 원장 업로드했습니다.", "수집"),
        IntakeTurn("bot", "업무용 승용차 운행기록부가 있나요? 손금 한도 검토에 필요합니다."),
        IntakeTurn("user", "운행기록부는 아직 없습니다.", "없음"),
        IntakeTurn("bot", "법인카드/세금계산서 등 접대비 적격증빙 매칭 자료는 어떤가요?"),
        IntakeTurn("user", "그건 잘 모르겠어요, 담당자에게 확인해야 합니다.", "모름"),
        IntakeTurn("bot", "지급이자·가지급금 관련 차입금 명세가 있나요?"),
        IntakeTurn("user", "여기까지만 입력할게요. 나머지는 나중에 보완하겠습니다."),
        IntakeTurn("bot",
                   "조기 종료를 확인했습니다. 수집 자료로 검토 가능 범위와 결손·한계를 정리하겠습니다."),
    ]
    checklist = [
        InputMaterial("전기 법인세 신고서(2025)", "수집", "L2"),
        InputMaterial("합계잔액시산표(TB, 당기)", "수집", "L2"),
        InputMaterial("계정별 원장(접대비·기부금)", "수집", "L2"),
        InputMaterial("재무제표(당기)", "수집", "L2"),
        InputMaterial("업무용 승용차 운행기록부", "없음", "L2"),
        InputMaterial("접대비 적격증빙(법인카드·세금계산서) 매칭", "모름", "L2"),
        InputMaterial("차입금 명세(지급이자·가지급금)", "결손", "L2"),
    ]
    return IntakeSession(
        goal="A제조(주) 2026 법인세 절세·리스크 검토",
        company="A제조(주)",
        turns=turns,
        checklist=checklist,
        closing_scope=(
            "검토 가능 범위: 전기 신고서·TB·접대비 원장 기반으로 기업업무추진비(접대비) "
            "한도 손금불산입과 기부금 한도, 지급이자 손금불산입 1차 검토가 가능합니다."
        ),
        deficits=[
            "업무용 승용차 운행기록부 미보유 → 차량 관련비용 손금 한도 검토 보류(결손)",
            "접대비 적격증빙 매칭 자료 미확인(모름) → 손금 부인 리스크 정량화 제한",
            "차입금 명세 결손 → 가지급금 인정이자·지급이자 손금불산입 정밀검토 보류",
        ],
        limits=[
            "운행기록부·증빙 매칭 자료 결손으로 일부 결론에는 '자료한계' 꼬리표가 부착됩니다.",
            "적용시점은 2026 사업연도(귀속연도) 기준 가정 — 실제 거래일 확정 필요(PROV-013).",
        ],
    )


# --------------------------------------------------------------------------- #
# Draft package (화면 ②/③ + DOCX)
# --------------------------------------------------------------------------- #
@dataclass
class _CiteSpec:
    key: str
    article: str
    title: str
    rank: int


_CITE_SPECS = [
    _CiteSpec("c25", "제25조", "기업업무추진비의 손금불산입", 1),
    _CiteSpec("c24", "제24조", "기부금의 손금불산입", 1),
    _CiteSpec("c27", "제27조의2", "업무용승용차 관련비용의 손금불산입 등 특례", 1),
    _CiteSpec("c28", "제28조", "지급이자의 손금불산입", 1),
]


def _build_citations() -> tuple[
    list[Citation], dict[str, str], dict[str, str], dict[str, str], list[object]
]:
    """오프라인 법령 replay로 실제 버전객체 Citation 4건 구성 + 표시 메타 + 소스객체.

    SourceRegistry 검증(OUT-003)용으로 각 bundle 의 실제 version source object
    (ProvisionVersion 등)을 함께 수집한다(날조 인용 거부의 정합 근거)."""
    law = default_law_source()
    citations: list[Citation] = []
    titles: dict[str, str] = {}     # citation_id -> 조문 제목
    articles: dict[str, str] = {}   # citation_id -> 조문 라벨
    by_key: dict[str, str] = {}     # spec.key -> citation_id
    source_objects: list[object] = []   # 등록용 version source object(ProvisionVersion 등)
    for spec in _CITE_SPECS:
        lookup = _lookup_inforce(law, spec.article)
        bundle = build_law_source_answer(
            lookup=lookup,
            client_id=_CLIENT,
            answer_run_id=f"ar_{_MATTER}",
            source_answer_id=f"sa_{_MATTER}_{spec.key}",
            source_type_label="법률",
            matter_id=_MATTER,
        )
        cit = bundle.citation
        citations.append(cit)
        source_objects.extend(bundle.source_objects)
        titles[cit.citation_id] = lookup.article_title
        articles[cit.citation_id] = spec.article
        by_key[spec.key] = cit.citation_id
    return citations, titles, articles, by_key, source_objects


def _build_review_items() -> list[ReviewItem]:
    """slice ⑤ src.review_items 로 회계사 검토항목 자동생성(HALU-008)."""
    law = default_law_source()
    lookup = _lookup_inforce(law, "제25조")
    bundle = build_law_source_answer(
        lookup=lookup, client_id=_CLIENT, answer_run_id=f"ar_{_MATTER}",
        source_answer_id=f"sa_{_MATTER}_review", source_type_label="법률", matter_id=_MATTER,
    )
    # 결정적 ResearchLiteAnswer (LLM 없이 검토항목 도출용 입력 — slice⑤ 로직 실제 실행)
    research = ResearchLiteAnswer(
        bundle=bundle,
        legal_conclusion=(
            "기업업무추진비(접대비) 한도 초과액은 손금불산입되며, 적격증빙 미수취분은 "
            "손금에 산입하지 않는다(법인세법 제25조)."
        ),
        certainty="해석",
        reasoning="한도 = 기본한도 + 수입금액 기준 한도. 적격증빙·업무관련성 충족 시 손금.",
        limits_deadlines="사업연도 단위 한도 적용 / 적격증빙 보관의무.",
        filing_impact="세무조정계산서(손금불산입·기타사외유출) 반영.",
        risks=[
            "적격증빙 미매칭분 손금 부인 가능성(과세논리)",
            "업무무관성 의심 거래의 손금 부인 리스크",
        ],
        spotted_issues=["접대비/기부금 한도 동시검토", "업무용 승용차 한도와의 상호작용"],
        needs_review=True,
        abstained=False,
        answer_text="(데모 검토항목 도출용 결정적 입력)",
        conclusion_claim=bundle.claim,
        conclusion_citation=bundle.citation,
    )
    return generate_review_items(
        answer=research,
        client_id=_CLIENT,
        matter_id=_MATTER,
        high_risk=True,
        aggressive=True,
        unresolved_conflicts=[
            "접대비 적격증빙 손금 부인 범위 — 예규(과세) vs 심판례(납세자) 미해소",
        ],
        data_limits=[
            "업무용 승용차 운행기록부 결손 — 차량 관련비용 손금 한도 검토 보류",
        ],
        prefix="ri_amfg",
    )


def build_demo_draft_package() -> tuple[DraftPackageData, dict[str, str], dict[str, str]]:
    """대표 DraftPackageData + (titles, articles) 표시 메타를 반환(결정적)."""
    citations, titles, articles, k, source_objects = _build_citations()
    review_items = _build_review_items()

    synthesis = SynthesisOpinion(
        synthesis_id=f"syn_{_MATTER}",
        answer_run_id=f"ar_{_MATTER}",
        client_id=_CLIENT,
        source_answer_ids=[f"sa_{_MATTER}_law", f"sa_{_MATTER}_rag", f"sa_{_MATTER}_web"],
        policy_version="synth-v1",
        opinion_text=(
            "[종합의견 — 채널 ④ 3소스 종합] ①법령(제25조)·②내부 실무서·③최신 웹이 각각 "
            "독립 답변을 낸 뒤 권위 위계(법률>시행령>…>실무서>웹)·시점 유효성으로 정합. "
            "접대비 한도 초과 손금불산입은 ①법령 원문으로 확정, 적격증빙 부인 범위는 예규·"
            "심판례 충돌이 미해소되어 회계사 검토로 승격(단정 보류). 종합의견은 새 인용을 "
            "만들지 않고 각 소스답변의 인용을 상속한다."
        ),
        abstained=False,
        authority_deficit=None,
        confidence_cap=None,
    )

    strategy_options = [
        StrategyOption(
            option_key="보수", label="보수적 처리",
            expected_tax_burden="증가 (+약 1,200만원)",
            tax_risk="낮음 — 한도 초과·미증빙분 전액 손금불산입",
            defensibility="높음 — 과세관청 수용 가능성 큼",
            required_evidence="기본 자료(TB·원장)",
            cpa_review_point="고객 세부담 증가 수용 가능성",
            citation_ids=[k["c25"]],
        ),
        StrategyOption(
            option_key="중립", label="중립적 처리",
            expected_tax_burden="중간 (+약 600만원)",
            tax_risk="중간 — 적격증빙 매칭분만 손금, 한도 내 처리",
            defensibility="중간 — 예규 근거 확보 시 방어 가능",
            required_evidence="계약서·계정별 원장·법인카드 매칭",
            cpa_review_point="예규 근거 확인·증빙 매칭 충실도",
            citation_ids=[k["c25"]],
        ),
        StrategyOption(
            option_key="적극", label="적극적 처리",
            expected_tax_burden="감소 (-약 300만원)",
            tax_risk="높음 — 업무관련성 폭넓게 인정·전액 손금 주장",
            defensibility="낮음~중간 — 조사 시 부인 가능성",
            required_evidence="추가 소명자료(거래 목적·상대방·업무관련성)",
            cpa_review_point="세무조사 대응 가능성·가산세 노출",
            citation_ids=[k["c25"]],
        ),
    ]

    risks = [
        RiskItem(
            "접대비 한도 초과 손금불산입",
            "기업업무추진비가 기본한도+수입금액 기준 한도를 초과한 부분은 손금불산입.",
            citation_ids=[k["c25"]], severity="HIGH",
        ),
        RiskItem(
            "적격증빙 미수취분 손금 부인",
            "건당 기준금액 초과 접대비의 적격증빙(법인카드·세금계산서) 미수취분 손금 부인 리스크.",
            citation_ids=[k["c25"]], severity="HIGH",
        ),
        RiskItem(
            "기부금 한도 초과·이월",
            "법정·지정기부금 한도 초과액의 손금불산입 및 이월공제 적정성 검토 필요.",
            citation_ids=[k["c24"]], severity="MEDIUM",
        ),
        RiskItem(
            "지급이자 손금불산입(가지급금 등)",
            "업무무관자산·가지급금 관련 지급이자 손금불산입 대상 여부 검토.",
            citation_ids=[k["c28"]], severity="MEDIUM",
        ),
    ]

    opportunities = [
        OpportunityItem(
            "기업업무추진비 한도 최적화",
            "수입금액 기준 한도·문화접대비 추가한도 활용으로 손금 가능액 확대 여지.",
            citation_ids=[k["c25"]],
        ),
        OpportunityItem(
            "업무용 승용차 손금 한도 관리",
            "운행기록부 작성으로 업무사용비율 인정·손금 한도 확대(자료 보완 전제).",
            citation_ids=[k["c27"]],
        ),
        OpportunityItem(
            "기부금 이월공제 활용",
            "당기 한도 초과 기부금의 이월공제로 차기 이후 손금 산입 기회.",
            citation_ids=[k["c24"]],
        ),
    ]

    issue_memos = [
        IssueMemo(
            topic="쟁점 1. 접대비 적격증빙 손금 부인 범위",
            analysis=(
                "제25조는 한도 초과액과 적격증빙 미수취분을 손금불산입한다. 증빙 매칭 자료가 "
                "'모름' 상태로 부인 범위 정량화가 제한되며, 예규(과세)와 심판례(납세자)가 "
                "충돌하므로 단정하지 않고 회계사 검토로 승격한다."
            ),
            citation_ids=[k["c25"]],
            escalation="H3(충돌/시점) → 미해소 충돌 단정 금지",
        ),
        IssueMemo(
            topic="쟁점 2. 기부금 한도·이월공제",
            analysis="제24조 한도 계산과 이월공제 잔액의 정합성을 전기 신고서와 대조한다.",
            citation_ids=[k["c24"]],
            escalation="H2(계산) → 한도 계산 검산",
        ),
        IssueMemo(
            topic="쟁점 3. 업무용 승용차 관련비용 한도",
            analysis=(
                "제27조의2 업무사용비율·한도는 운행기록부에 의존하나 운행기록부가 결손이라 "
                "검토를 보류한다(자료한계)."
            ),
            citation_ids=[k["c27"]],
            escalation="H1(입력) → 운행기록부 결손 보완 필요",
        ),
    ]

    additional_requests = [
        "업무용 승용차 운행기록부(2026 사업연도) — 차량 관련비용 손금 한도 검토용",
        "접대비 적격증빙(법인카드 전표·세금계산서) 및 원장 매칭 명세",
        "차입금 명세·가지급금 잔액 명세 — 지급이자 손금불산입 검토용",
        "이사회의사록·주요 계약서 — 거래 업무관련성 소명자료",
    ]

    data = DraftPackageData(
        matter_id=_MATTER,
        client_id=_CLIENT,
        company_name="A제조(주)",
        fiscal_year="2026 사업연도",
        as_of_date=_AS_OF,
        review_scope=(
            "전 세무항목 동일 구조 검토(Tax Skill Library) — 기업업무추진비(접대비)·기부금·"
            "업무용 승용차·지급이자 중심. 리스크 → 선택지 비교 → 근거 → 검산 → 검토패키지."
        ),
        high_risk=True,
        executive_summary=(
            "A제조(주) 2026 사업연도 법인세 검토 결과, 기업업무추진비(접대비) 한도 초과 및 "
            "적격증빙 미수취분 손금불산입이 핵심 리스크다. 보수/중립/적극 3개 선택지의 "
            "세부담·과세리스크·방어가능성을 비교 제시하며, 적격증빙 부인 범위는 예규·심판례 "
            "충돌이 미해소되어 회계사 검토(HITL)로 승격한다. 모든 법적 주장은 법령 원문(버전 "
            "객체) 인용을 동반하며, 운행기록부·증빙 매칭 결손에는 자료한계 꼬리표를 부착했다."
        ),
        input_materials=[
            InputMaterial("전기 법인세 신고서(2025)", "수집", "L2"),
            InputMaterial("합계잔액시산표(TB, 당기)", "수집", "L2"),
            InputMaterial("계정별 원장(접대비·기부금)", "수집", "L2"),
            InputMaterial("재무제표(당기)", "수집", "L2"),
            InputMaterial("업무용 승용차 운행기록부", "없음", "L2"),
            InputMaterial("접대비 적격증빙 매칭", "모름", "L2"),
            InputMaterial("차입금 명세(지급이자·가지급금)", "결손", "L2"),
        ],
        risks=risks,
        opportunities=opportunities,
        strategy_options=strategy_options,
        issue_memos=issue_memos,
        citations=citations,
        additional_requests=additional_requests,
        review_items=review_items,
        conclusion=(
            "접대비 한도 초과 손금불산입은 법령 원문으로 확정되나, 적격증빙 부인 범위와 "
            "업무용 승용차 한도는 자료 보완·회계사 판단이 선행되어야 한다. 중립적 처리를 "
            "기준안으로 제시하되 최종 선택지와 고객 전달본은 Reviewer 승인(H4·H5) 후 확정한다."
        ),
        recommended_order=[
            "운행기록부·증빙 매칭 자료 보완(결손 해소)",
            "접대비·기부금 한도 계산 검산(H2)",
            "적격증빙 부인 범위 예규·심판례 재검토(H3, 미해소 충돌)",
            "선택지 확정 및 고위험 가드레일 검토(H4)",
            "검토패키지 사인오프·고객 전달본 생성(H5)",
        ],
        data_limits=[
            "운행기록부·증빙 매칭·차입금 명세 결손으로 일부 결론에 자료한계 꼬리표 부착",
            "적용시점은 2026 사업연도(귀속연도) 가정 — 실제 거래일 확정 필요",
        ],
        synthesis=synthesis,
        source_objects=source_objects,
        # OUT-007(변경②): 종합 전 채널별 독립 결과(①②③) — 데모는 3소스 모두 응답(3/3 AGREE).
        channel_results=[
            ChannelResult(
                channel="①", source_label="①법령MCP", status="ANSWERED", answered=True,
                answer_excerpt="법인세법 제25조: 기업업무추진비 한도 초과액·적격증빙 미수취분 손금불산입(법령 원문).",
                citation_locators=["법인세법 제25조"],
            ),
            ChannelResult(
                channel="②", source_label="②내부RAG(실무서)", status="ANSWERED", answered=True,
                answer_excerpt="사내 실무기준: 건당 3만원(경조사비 20만원) 초과는 적격증빙 수취해야 손금 인정 — 공개 조문에 grounding(L3 메모 외부 미송신).",
                citation_locators=["법인세법 제25조"],
            ),
            ChannelResult(
                channel="③", source_label="③공식웹", status="ANSWERED", answered=True,
                answer_excerpt="국세청·법제처 공식자료를 법령 원문과 대조 후 승격 — provenance 인용(블로그/미러 배제).",
                citation_locators=["법인세법 제25조"],
            ),
        ],
    )
    return data, titles, articles


def build_frontend_fixture() -> dict:
    """프론트 3화면 전체 fixture(Intake + 선택지 + DOCX 미리보기) — 결정적 JSON."""
    intake = build_demo_intake()
    data, titles, articles = build_demo_draft_package()
    return {
        "intake": intake.to_fixture(),
        "draft": draft_package_to_fixture(data, titles=titles, articles=articles),
    }
