"""src/strategy_plan.py — 회사 다(多)전략 절세 종합검토 데이터 + 대표 데모(리노공업㈜).

가업승계 한 가지가 아니라 **법인 절세전략 전체를 재무제표에 대해 스크리닝**해 적용/조건부/
미해당으로 분류하고, 적용 전략을 카테고리별로 상세화한다. 재무제표는 **DART 공시 그대로(원
단위 raw 값)** 사용한다(억원 환산 ✕).

대표 데모의 **재무수치는 리노공업㈜의 DART 전자공시(FY2024, 재무제표 단위: 원) 실제값**이며,
비재무 가정(승계·투자·고용 계획 등)과 절세효과는 **TIW 스크리닝 역량 시연을 위한 예시·추정**
으로 특정 회사에 대한 실제 자문이 아니다. 인용은 오프라인 법령 재현의 실제 시행일 버전객체만
사용한다(날조 0).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Optional

from contract.cluster_f_qa import Citation
from src.ai.law_data_source import default_law_source
from src.law_anchor import build_law_source_answer
from src.tax_plan import FinancialLine, FinancialStatement, TimelineStep
from src.tax_strategies import (
    CompanyProfile, StrategyCard, corporate_strategy_catalog, screen_strategies,
)

_CLIENT, _MATTER = "client_rino_demo", "matter_rino_2026"
_AS_OF, _LOOKUP = date(2026, 1, 1), date(2024, 1, 1)


@dataclass(frozen=True)
class JournalEntry:
    """분개장 한 줄(차변=대변). ``strategy_key`` 로 절세전략과 연결."""

    seq: int
    date: str
    summary: str                          # 적요
    debit_acct: str
    debit_amt: float
    credit_acct: str
    credit_amt: float
    strategy_key: str = ""                # 연계 전략
    issue: str = ""                       # 세무 쟁점 요지(강조)


@dataclass(frozen=True)
class LedgerLine:
    date: str
    summary: str
    debit: float
    credit: float
    balance: float


@dataclass(frozen=True)
class LedgerAccount:
    """계정별원장(주요 세무 계정)."""

    account: str
    opening: float
    lines: list[LedgerLine]
    closing: float
    strategy_key: str = ""
    note: str = ""                        # 세무 쟁점·검토 요지


@dataclass(frozen=True)
class RagDbEvidence:
    """내부 RAG DB(실무 가이드) 회수 근거 1건 — 출처(파일·페이지) 보존."""

    source: str            # "<가이드 파일명> p.<페이지>"
    text: str              # 회수된 passage(발췌)
    score: float = 0.0
    tax_type: str = ""


@dataclass(frozen=True)
class ChannelAnswer:
    """3소스 리서치의 한 채널(①법령 / ②내부RAG / ③공식웹) 답변."""

    channel: str                                   # "①법령" | "②내부RAG" | "③공식웹"
    authority: str                                 # 법률 | 실무서 | 공식웹
    answer: str                                    # 채널별 자연어 답변(요지)
    citation_articles: list = field(default_factory=list)   # [(법령명, 조문)] — 검증 대상
    web_url: str = ""                              # ③ 공식 출처 URL(있으면)
    rag_evidence: list = field(default_factory=list)        # ② RAG DB 회수 근거(RagDbEvidence)
    abstained: bool = False                        # 근거 없어 보류(침묵) 여부
    note: str = ""                                 # 보조 설명(보류 사유 등)


@dataclass
class ResearchSynthesis:
    """①법령·②RAG·③웹 3소스 리서치 + 종합의견(채널별 답변을 한 데 모아 종합)."""

    question: str
    channels: list                                 # list[ChannelAnswer] (①②③ 순)
    opinion: str                                   # 종합의견(권위 위계·시점 반영)
    method_note: str = ""                          # 방법 고지(웹/RAG 단독 단정 금지 등)


@dataclass
class StrategyPlanData:
    title: str
    company_name: str
    as_of: date
    source_note: str                      # DART 출처·단위 고지
    objective: str
    executive_summary: str
    overview: list[str]
    balance_sheet: FinancialStatement
    income_statement: FinancialStatement
    strategies: list[StrategyCard]        # 스크리닝 완료(applies set)
    timeline: list[TimelineStep]
    citations: list[Citation]
    art_to_cid: dict                      # (법령명, 조문) -> citation_id
    review_points: list[str]
    conclusion: str
    data_limits: list[str]
    source_objects: list = field(default_factory=list)
    ledgers: list = field(default_factory=list)        # 계정별원장(주요 세무 계정)
    journal: list = field(default_factory=list)        # 분개장(세무 쟁점 거래)
    research: Optional[ResearchSynthesis] = None       # 3소스 리서치 + 종합의견(선택)

    @property
    def citation_index(self) -> dict:
        return {c.citation_id: c for c in self.citations}

    @property
    def applied(self) -> list[StrategyCard]:
        return [s for s in self.strategies if s.applies]


def _cite(law_name: str, article: str, key: str):
    """오프라인 법령 재현의 실제 버전객체 인용 + 표시 메타."""
    law = default_law_source()
    lk = replace(law.lookup_provision(law_name, article, _LOOKUP), as_of_date=_AS_OF)
    b = build_law_source_answer(
        lookup=lk, client_id=_CLIENT, answer_run_id=f"ar_{_MATTER}",
        source_answer_id=f"sa_{_MATTER}_{key}", source_type_label="법률", matter_id=_MATTER)
    return b.citation, lk.article_title, b.source_objects


def _resolve_citations(strategies: list[StrategyCard]):
    """전략들이 참조하는 (법령,조문)을 한 번씩 오프라인 인용으로 해소."""
    citations: list[Citation] = []
    titles: dict[str, str] = {}
    articles: dict[str, str] = {}
    art_to_cid: dict = {}
    source_objects: list = []
    seen: dict = {}
    for s in strategies:
        for (law_name, art) in s.citation_articles:
            if (law_name, art) in seen:
                continue
            key = f"{s.key}_{len(seen)}"
            cit, title, sobjs = _cite(law_name, art, key)
            seen[(law_name, art)] = cit.citation_id
            art_to_cid[(law_name, art)] = cit.citation_id
            titles[cit.citation_id] = title
            articles[cit.citation_id] = art
            citations.append(cit)
            source_objects.extend(sobjs)
    return citations, titles, articles, art_to_cid, source_objects


# --------------------------------------------------------------------------- #
# 대표 데모 — 리노공업㈜ FY2024 (DART 공시 실제값, 단위: 원)
# --------------------------------------------------------------------------- #
def build_demo_strategy_plan() -> tuple[StrategyPlanData, dict, dict]:
    """리노공업㈜ FY2024 재무제표(DART 원본, 원 단위)에 대한 다전략 종합검토 데모."""
    # --- 재무상태표 (원, DART fnlttSinglAcntAll OFS 그대로) --- #
    bs = FinancialStatement(
        title="재무상태표", period="리노공업㈜ · 2024년 12월 31일 현재 (DART 전자공시)",
        unit="단위: 원 (DART 공시 그대로)",
        lines=[
            FinancialLine("[자산]", None, bold=True),
            FinancialLine("유동자산", 449_498_090_730, indent=1, bold=True),
            FinancialLine("현금및현금성자산", 54_759_251_381, indent=2),
            FinancialLine("기타금융자산(단기)", 325_041_999_477, is_issue=True,
                          issue_label="대규모 현금성 자산 — 잉여금 환원·승계 설계의 재원(현금배당·유상감자 검토)",
                          citation_ids=[], indent=2),
            FinancialLine("매출채권", 51_075_599_798, is_issue=True,
                          issue_label="대손충당금 한도 설정·대손금 손금산입 시기 관리 대상",
                          citation_ids=[("법인세법", "제34조")], indent=2),
            FinancialLine("재고자산", 12_959_312_526, indent=2),
            FinancialLine("기타채권", 3_480_223_276, indent=2),
            FinancialLine("기타자산", 2_181_704_272, indent=2),
            FinancialLine("비유동자산", 207_945_690_026, indent=1, bold=True),
            FinancialLine("유형자산", 181_362_679_776, is_issue=True,
                          issue_label="감가상각 방법·내용연수 최적화 + 신규 설비투자 시 통합투자세액공제 여지",
                          citation_ids=[("법인세법", "제23조")], indent=2),
            FinancialLine("기타금융자산(장기)", 22_988_728_704, indent=2),
            FinancialLine("무형자산", 1_959_270_745, indent=2),
            FinancialLine("이연법인세자산", 1_569_384_971, indent=2),
            FinancialLine("기타채권(장기)", 65_625_830, indent=2),
            FinancialLine("자산총계", 657_443_780_756, bold=True),
            FinancialLine("[부채]", None, bold=True),
            FinancialLine("유동부채", 30_614_692_642, indent=1, bold=True),
            FinancialLine("당기법인세부채", 18_322_324_767, indent=2),
            FinancialLine("기타채무", 6_798_405_442, indent=2),
            FinancialLine("매입채무", 4_642_128_455, indent=2),
            FinancialLine("기타부채", 770_708_930, indent=2),
            FinancialLine("리스부채(유동)", 81_125_048, indent=2),
            FinancialLine("비유동부채", 4_199_975_951, indent=1, bold=True),
            FinancialLine("기타장기종업원급여부채", 3_910_514_525, indent=2),
            FinancialLine("순확정급여부채", 188_815_200, indent=2),
            FinancialLine("리스부채(비유동)", 100_646_226, indent=2),
            FinancialLine("부채총계", 34_814_668_593, bold=True),
            FinancialLine("[자본]", None, bold=True),
            FinancialLine("자본금", 7_621_185_000, indent=1),
            FinancialLine("자본잉여금", 5_601_810_444, indent=1),
            FinancialLine("자본조정", -2_353_516_350, indent=1),
            FinancialLine("이익잉여금", 611_759_633_069, is_issue=True,
                          issue_label="누적 이익잉여금 약 6,118억원 — 수입배당금 익금불산입·의제배당으로 "
                          "법인 단계 저(무)과세 환원 여지(승계가치 인하)",
                          citation_ids=[("법인세법", "제18조의2"), ("법인세법", "제16조")], indent=1),
            FinancialLine("자본총계", 622_629_112_163, bold=True),
            FinancialLine("부채와자본총계", 657_443_780_756, bold=True),
        ],
    )
    # --- 손익계산서(포괄손익계산서) (원, DART 그대로) --- #
    is_ = FinancialStatement(
        title="손익계산서", period="리노공업㈜ · 2024년 1월 1일~12월 31일 (DART 전자공시)",
        unit="단위: 원 (DART 공시 그대로)",
        lines=[
            FinancialLine("매출액", 278_186_189_427, is_issue=True,
                          issue_label="수입금액 기준 기업업무추진비(접대비) 한도 재계산·적격증빙 관리 대상",
                          citation_ids=[("법인세법", "제25조")]),
            FinancialLine("매출원가", 140_020_108_110, indent=1),
            FinancialLine("매출총이익", 138_166_081_317, bold=True),
            FinancialLine("판매비와관리비", 13_964_737_445, indent=1),
            FinancialLine("영업이익", 124_201_343_872, bold=True),
            FinancialLine("금융수익", 10_957_192_803, indent=1),
            FinancialLine("금융원가", 7_604_344, indent=1),
            FinancialLine("기타수익", 13_700_970_478, indent=1),
            FinancialLine("기타비용", 2_312_820_865, indent=1),
            FinancialLine("법인세비용차감전순이익", 146_539_081_944, bold=True),
            FinancialLine("법인세비용", 33_260_035_516, is_issue=True,
                          issue_label="연구·인력개발비·고용·투자 세액공제로 산출세액 직접 절감 여지(적격성 입증 전제)",
                          citation_ids=[("조세특례제한법", "제10조")], indent=1),
            FinancialLine("당기순이익", 113_279_046_428, bold=True),
        ],
    )

    profile = CompanyProfile(
        name="리노공업㈜",
        retained_earnings=611_759_633_069,
        tangible_assets=181_362_679_776,
        revenue=278_186_189_427,
        borrowings=81_125_048 + 100_646_226,   # 리스부채만(실질 차입 미미)
        is_sme=False,
        rnd_active=True,
        family_controlled=True,
        has_idle_land=False,
        has_company_cars=True,
        expects_new_investment=True,
        expects_headcount_growth=False,
    )
    strategies = screen_strategies(profile)
    citations, titles, articles, art_to_cid, source_objects = _resolve_citations(strategies)

    # 재무제표 쟁점행의 citation_ids 가 (법령,조문) 튜플로 들어 있으니 실제 citation_id 로 치환
    def remap(stmt: FinancialStatement) -> FinancialStatement:
        new_lines = []
        for ln in stmt.lines:
            if ln.is_issue and ln.citation_ids:
                cids = [art_to_cid[t] for t in ln.citation_ids if t in art_to_cid]
                new_lines.append(replace(ln, citation_ids=cids))
            else:
                new_lines.append(ln)
        return replace(stmt, lines=new_lines)

    bs, is_ = remap(bs), remap(is_)

    A = art_to_cid
    timeline = [
        TimelineStep(1, "2026.1분기", "현황 진단·전략 스크리닝(재무제표 대비 적용 전략 도출)",
                     "적용/조건부/미해당 분류로 검토 범위 확정", []),
        TimelineStep(2, "2026.1분기", "R&D·고용·투자 세액공제 자료 정비(연구노트·투자·고용 증빙)",
                     "산출세액 직접 공제 기반 마련", [A.get(("조세특례제한법", "제10조"))]),
        TimelineStep(3, "2026.2분기", "접대비·승용차·충당금 손금 관리 정비",
                     "한도 초과·증빙 미비 손금부인 예방", [A.get(("법인세법", "제25조"))]),
        TimelineStep(4, "2026.2~3분기", "잉여금 환원 구조 설계(수입배당금 익금불산입·유상감자)",
                     "법인 단계 저(무)과세 환원 + 승계가치 인하(요건 충족 시)",
                     [A.get(("법인세법", "제18조의2")), A.get(("법인세법", "제16조"))]),
        TimelineStep(5, "2026.3분기 이후", "가업승계 설계(해당 시) · 보충적평가",
                     "정리 후 낮아진 평가액에 가업승계 증여세 과세특례 적용 검토",
                     [A.get(("조세특례제한법", "제30조의6"))]),
        TimelineStep(6, "2026 신고기", "연간 신고 반영 · 사후관리 모니터링",
                     "세액공제 추징요건·고용유지·사후관리 점검", []),
    ]

    # --- 분개장(시연용 가상 거래, 원 단위 — 실제 계정구조와 일관) --- #
    journal = [
        JournalEntry(1, "2024.02.10", "거래처 접대(법인카드 결제)",
                     "기업업무추진비", 8_000_000, "미지급금", 8_000_000,
                     strategy_key="entertain", issue="수입금액 기준 한도·건당 적격증빙 검토"),
        JournalEntry(2, "2024.03.25", "정기주주총회 결의 배당 지급",
                     "이월이익잉여금", 30_000_000_000, "미지급배당금", 30_000_000_000,
                     strategy_key="recv_div", issue="지주 수령분 수입배당금 익금불산입(요건 충족 시)"),
        JournalEntry(3, "2024.03.31", "1분기 연구개발비(연구인력 인건비·재료비)",
                     "경상연구개발비", 3_800_000_000, "현금", 3_800_000_000,
                     strategy_key="rnd_credit", issue="연구·인력개발비 세액공제 적격비용 구분"),
        JournalEntry(4, "2024.04.15", "반도체 검사설비 신규 취득",
                     "기계장치", 20_000_000_000, "보통예금", 20_000_000_000,
                     strategy_key="invest_credit", issue="통합투자세액공제 적격자산·내용연수"),
        JournalEntry(5, "2024.06.30", "임원 업무용승용차 유지비",
                     "차량유지비", 12_000_000, "현금", 12_000_000,
                     strategy_key="company_car", issue="운행기록부·전용보험 요건"),
        JournalEntry(6, "2024.12.31", "유형자산 감가상각비 계상",
                     "감가상각비", 25_000_000_000, "감가상각누계액", 25_000_000_000,
                     strategy_key="depreciation", issue="상각방법·내용연수 적정성"),
        JournalEntry(7, "2024.12.31", "매출채권 대손충당금 설정",
                     "대손상각비", 510_000_000, "대손충당금", 510_000_000,
                     strategy_key="bad_debt_reserve", issue="한도율(법정 1% 대 대손실적률)"),
        JournalEntry(8, "2024.12.31", "확정급여형 퇴직연금 납입",
                     "퇴직급여", 1_000_000_000, "현금", 1_000_000_000,
                     strategy_key="retire_reserve", issue="사외적립·손금한도"),
    ]
    # --- 계정별원장(세무 관련 주요 계정, 시연용 가상) --- #
    ledgers = [
        LedgerAccount(
            "기업업무추진비(접대비)", 0,
            [LedgerLine("2024.03.31", "1분기 집행 누계", 62_000_000, 0, 62_000_000),
             LedgerLine("2024.06.30", "2분기 집행 누계", 58_000_000, 0, 120_000_000),
             LedgerLine("2024.09.30", "3분기 집행 누계", 65_000_000, 0, 185_000_000),
             LedgerLine("2024.12.31", "4분기 집행 누계", 65_000_000, 0, 250_000_000)],
            250_000_000, strategy_key="entertain",
            note="연간 약 2.5억원 집행 — 수입금액 기준 한도(약 1.9억원) 초과분 손금부인 검토 필요"),
        LedgerAccount(
            "경상연구개발비", 0,
            [LedgerLine("2024.03.31", "1분기 연구개발비", 3_800_000_000, 0, 3_800_000_000),
             LedgerLine("2024.06.30", "2분기 연구개발비", 3_700_000_000, 0, 7_500_000_000),
             LedgerLine("2024.09.30", "3분기 연구개발비", 3_850_000_000, 0, 11_350_000_000),
             LedgerLine("2024.12.31", "4분기 연구개발비", 3_850_000_000, 0, 15_200_000_000)],
            15_200_000_000, strategy_key="rnd_credit",
            note="연간 약 152억원 — 세액공제 적격비용 구분·당기분 대 증가분 방식 비교"),
        LedgerAccount(
            "기계장치", 161_362_679_776,
            [LedgerLine("2024.04.15", "반도체 검사설비 취득", 20_000_000_000, 0, 181_362_679_776)],
            181_362_679_776, strategy_key="invest_credit",
            note="신규 설비 200억원 — 통합투자세액공제 적격 검토(취득가액 기준)"),
    ]

    n_apply = sum(1 for s in strategies if s.applies)

    # --- 3소스 리서치(①법령 ②내부RAG ③공식웹) + 종합의견 --- #
    # ② RAG 근거는 라이브 임베딩 인덱스에서 attach_rag_db_research() 로 채운다(오프라인
    # 테스트에서는 빈 채로 두어 결정성 유지). 법령 인용은 art_to_cid 로 검증된다(날조 0).
    research = ResearchSynthesis(
        question="리노공업㈜의 대규모 누적 이익잉여금(약 6,118억원) 환원과 관련하여 수입배당금 "
        "익금불산입(법인세법 제18조의2)·의제배당(제16조)의 적용 요건과 한계를 ①법령 ②내부 "
        "실무자료 ③공식 웹의 3개 경로로 교차검증한다.",
        channels=[
            ChannelAnswer(
                channel="①법령", authority="법률",
                answer="내국법인이 다른 내국법인으로부터 받는 수입배당금은 출자비율 구간에 따라 일정 "
                "비율을 익금에 산입하지 않는다(법인세법 제18조의2). 차입금 이자가 있으면 그에 대응하는 "
                "금액을 익금불산입액에서 차감하고, 지급기준일 현재 보유기간 등 요건과 적용배제 사유"
                "(제2항)를 확인해야 한다. 잉여금을 유상감자로 환원할 때의 감자대가는 의제배당(제16조)"
                "으로 과세될 수 있어 함께 검토한다.",
                citation_articles=[("법인세법", "제18조의2"), ("법인세법", "제16조")],
            ),
            ChannelAnswer(
                channel="②내부자료", authority="실무서",
                answer="내부 실무자료 인덱스(2026 자본거래 세무쟁점·비상장주식 평가·가업승계 등 공개 "
                "실무 가이드를 임베딩한 벡터 검색 인덱스)에서 배당·익금불산입·자본거래 관련 실무 쟁점을 "
                "회수해 법령 해석의 실무 적용 맥락을 보강한다. 아래 회수 근거는 실제 임베딩 인덱스에서 "
                "검색된 가이드 페이지이며, 출처(파일·페이지)를 그대로 표기한다.",
                rag_evidence=[],
                note="회수 근거가 비어 있으면 내부 실무자료 인덱스 미빌드(오프라인) 상태이다 — 라이브 "
                "산출 시 실제 가이드 페이지가 채워진다.",
            ),
            ChannelAnswer(
                channel="③공식웹", authority="공식웹",
                answer="공식 출처(국가법령정보센터 법령 원문)와 대조하여 위 해석의 시점·문언을 확인한다. "
                "공식성·시점유효·법령대조를 통과한 출처만 결론 근거로 승격하며 블로그·요약본 등 비공식 "
                "자료는 근거로 쓰지 않는다(공식소스 승격 원칙).",
                citation_articles=[("법인세법", "제18조의2")],
                web_url="https://www.law.go.kr/법령/법인세법",
            ),
        ],
        opinion="세 경로가 모두 '수입배당금 익금불산입은 출자비율·보유기간·차입금이자 차감·적용배제"
        "(제2항) 요건을 충족하는 범위에서만 적용된다'는 결론에서 일치한다. 권위의 1차 근거는 법령(①)"
        "이고 내부 실무자료(②)는 실무 적용 맥락을, 공식 웹(③)은 시점·문언 대조를 제공한다. 따라서 "
        "리노공업의 잉여금 환원 설계는 제18조의2 요건 충족을 전제로 하되, 유상감자 환원 시 제16조 "
        "의제배당 과세를 함께 점검해야 한다. 구체 적용 여부·금액은 회사 지분구조·차입현황 등 상세자료로 "
        "확정한다.",
        method_note="공식 웹·내부 실무자료 단독으로 세무 결론을 단정하지 않는다 — 결론은 법령 원문"
        "(①)에 앵커링되며 회수·검색 결과는 발견·보강 용도이다(날조 차단·근거 없으면 안전 중단).",
    )

    data = StrategyPlanData(
        title="리노공업㈜ 법인 절세전략 종합검토(다전략 스크리닝)",
        company_name="리노공업㈜", as_of=_AS_OF,
        source_note="재무수치는 리노공업㈜의 DART 전자공시(2024 사업연도, 재무제표 단위: 원) 실제값을 "
        "그대로 사용했습니다. 본 보고서는 TIW의 다전략 절세 스크리닝 역량을 보여 주기 위한 시연이며, "
        "승계·투자·고용 등 비재무 가정과 절세효과는 예시·추정으로 특정 회사에 대한 실제 자문이 아닙니다.",
        objective="회사 재무제표를 기준으로 적용 가능한 법인 절세전략 전체를 스크리닝하여 (1)적용 권고, "
        "(2)조건부, (3)검토했으나 미해당으로 분류하고, 적용 전략을 근거 법령과 함께 상세화해 회계사가 "
        "바로 검토·우선순위화할 수 있게 한다.",
        executive_summary=(
            f"리노공업㈜의 2024 사업연도 재무제표(DART 공시, 원 단위 그대로)를 기준으로 법인 절세전략 "
            f"{len(strategies)}종을 스크리닝한 결과 {n_apply}종이 적용 또는 조건부 적용으로 분류되었습니다. "
            "재무 특성상 ①누적 이익잉여금이 약 6,118억원으로 매우 커 수입배당금 익금불산입·유상감자(의제"
            "배당)를 통한 법인 단계 저(무)과세 환원 여지가 크고, ②유형자산 약 1,814억원으로 감가상각 "
            "최적화와 신규 설비투자 시 통합투자세액공제, ③상시 연구개발에 따른 연구·인력개발비 세액공제가 "
            "핵심 레버입니다. 반면 매출 규모가 커 ④중소기업 특별세액감면은 미해당으로 스크리닝되었습니다. "
            "모든 법적 판단에는 근거 법령을 함께 표기하고 파란색 글씨를 누르면 국가법령정보센터 원문으로 "
            "이동합니다. 정확한 절세액은 상세자료로 별도 산정해야 하며 본문 수치는 추정·정성 등급입니다."),
        overview=[
            "업종 — 반도체 검사용 부품(테스트 소켓·프로브) 제조. 코스닥 상장 중견 제조기업(DART 공시).",
            "재무 특성 — 고수익·저부채(차입 거의 없음)·대규모 현금성 자산과 누적 이익잉여금.",
            "검토 관점 — 잉여금 환원·세액공제·손금 최적화·자산정리·승계를 한 번에 스크리닝.",
        ],
        balance_sheet=bs, income_statement=is_, strategies=strategies, timeline=timeline,
        citations=citations, art_to_cid=art_to_cid,
        review_points=[
            "수입배당금 익금불산입 적용을 위한 지분율·보유기간·과세된 재원 요건과 제18조의2 제2항 제외요건 확인",
            "연구·인력개발비 세액공제의 적격 비용 범위와 당기분·증가분 중 유리한 방식 선택",
            "통합투자세액공제 적격 투자자산·기본/추가공제 요건과 사후 처분제한(조특법 제24조 원문 확인)",
            "기업업무추진비 수입금액별 한도 재계산과 적격증빙 구비 상태 점검",
            "가업승계 적용 시 가업·업종·지분·사후관리 요건과 보충적평가액 산정(승계계획은 회사 확인 필요)",
            "각 세액공제의 최저한세·중복적용 배제·추징요건 검토",
        ],
        conclusion="리노공업㈜의 실제 재무제표를 기준으로 보면 ①잉여금 환원 ②세액공제(연구개발·투자·고용) "
        "③손금 최적화 ④(해당 시)승계가 함께 작동하는 종합 설계의 실익이 큽니다. 본 도구는 다수 전략을 "
        "재무제표에 대해 스크리닝하고 적용·미해당을 근거와 함께 제시합니다. 구체 절세액·적용 여부는 "
        "상세자료 확인과 회계사 최종 검토·승인 후 확정합니다.",
        data_limits=[
            "재무수치 = 리노공업㈜ DART 공시(FY2024, 원 단위) 실제값 / 비재무 가정(승계·투자·고용 계획)과 "
            "절세효과는 시연용 예시·추정 — 특정 회사 실제 자문 아님",
            "전략별 절세효과는 정성 등급(높음·중간·낮음)으로 표기하며 정확한 금액은 상세자료로 별도 산정 필요",
            "수입배당금 익금불산입·의제배당의 '무과세'는 지분율·보유기간·과세된 재원 등 요건 충족 전제",
            "조특법 제24조(통합투자세액공제)·법인세법 제13조(이월결손금)는 오프라인 법령 재현에서 조문 파싱이 "
            "불가해 링크 없이 검토 주(註)로 표기 — 실행 전 원문 확인 필요",
            "근거 법령은 2024.1.1 시행분 기준으로 조회(오프라인 법령 재현) 후 2026 검토기준일 문서로 표시 — "
            "2024.1.1 이후 개정분은 실행 전 최신 법령으로 재확인 필요",
        ],
        source_objects=source_objects,
        ledgers=ledgers, journal=journal,
        research=research,
    )
    return data, titles, articles


def attach_rag_db_research(
    data: StrategyPlanData,
    *,
    query: Optional[str] = None,
    top_k: int = 4,
    as_of: Optional[date] = None,
) -> StrategyPlanData:
    """라이브 임베딩 인덱스에서 ②내부RAG 채널의 회수 근거(가이드 페이지)를 채워 반환한다.

    RAG DB 인덱스(``src.rag_db_index``)가 빌드돼 있어야 한다. 인덱스가 없거나(미빌드) 회수
    0건이면 채널을 보류(abstained) 상태로 표시한다(침묵 — 날조하지 않음). 원본 ``data`` 는
    변경하지 않고 research 만 교체한 새 객체를 돌려준다."""
    import dataclasses

    if data.research is None:
        return data
    q = query or data.research.question
    as_of = as_of or data.as_of

    import src.rag_db_index as ragdb

    evidence: list = []
    abstain_note = ""
    index = None
    try:
        index = ragdb.load_index()
        result = ragdb.query_rag_db(index, q, as_of=as_of, top_k=top_k)
        evidence = [
            RagDbEvidence(source=p.source, text=p.text, score=p.score, tax_type=p.tax_type or "")
            for p in result.passages
        ]
    except Exception as exc:  # noqa: BLE001 - 인덱스 미빌드/회수실패 → 보류(침묵·날조 0)
        evidence = []
        abstain_note = f"내부 실무자료 인덱스 미가용으로 회수 보류: {type(exc).__name__}"
    finally:
        # query_rag_db 가 예외를 던져도 Chroma 핸들(underlying client 포함)을 반드시 닫는다.
        ragdb.close_index(index)

    # ②내부자료(실무서) 채널에만 회수 근거/보류를 반영(채널 라벨 변경에 견고하도록 authority 매칭).
    new_channels = list(data.research.channels)
    for i, ch in enumerate(new_channels):
        if ch.authority == "실무서":
            new_channels[i] = dataclasses.replace(
                ch, rag_evidence=evidence, abstained=not evidence,
                note=(abstain_note if abstain_note else
                      ("" if evidence else "회수 0건 — 보류(침묵)")),
            )
    new_research = dataclasses.replace(data.research, channels=new_channels)
    return dataclasses.replace(data, research=new_research)
