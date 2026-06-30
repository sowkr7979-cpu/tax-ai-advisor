"""src/tax_plan.py — 시나리오 기반 Tax Plan 데이터 모델 + 대표 데모(한맥그룹).

TIW 의 새 산출물 유형: 단순 검토패키지(13목차)를 넘어 **다단계·시점최적화 절세 시나리오
플랜**(가업승계 주식정리 수준)을 표현한다. 재무제표(쟁점 강조)·지분구조·시나리오 비교·실행
타임라인·근거 법령을 한 데이터 구조로 담아 ``src.tax_plan_report`` 가 회계사용 DOCX(그림·도표·
하이퍼링크·Noto Sans KR)로 렌더한다.

인용(Citation)은 오프라인 법령 replay 의 실제 버전객체만 사용한다(날조 0). 조문 파싱이 불가한
근거(상법 감자절차·부당행위계산부인)는 인용 없이 절차/검토 주(註)로 둔다.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Optional

from contract.cluster_f_qa import Citation
from src.ai.law_data_source import default_law_source
from src.law_anchor import build_law_source_answer


# --------------------------------------------------------------------------- #
# 표시 모델
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FinancialLine:
    """재무제표 한 줄. ``is_issue`` 면 강조표시 + ``issue_label`` 쟁점을 단다."""

    label: str
    amount_eok: Optional[float]          # 금액(억원). None 이면 소계/구분행
    is_issue: bool = False
    issue_label: str = ""                # 쟁점 요지(강조행에만)
    citation_ids: list[str] = field(default_factory=list)
    indent: int = 0
    bold: bool = False                   # 소계/합계


@dataclass(frozen=True)
class FinancialStatement:
    title: str                           # 재무상태표 / 손익계산서
    period: str                          # 기준일/기간
    unit: str                            # 단위 표기(억원)
    lines: list[FinancialLine]


@dataclass(frozen=True)
class Holding:
    holder: str
    target: str
    pct: float
    note: str = ""


@dataclass(frozen=True)
class IssueItem:
    """핵심 쟁점 1건 — 재무제표 강조행과 연결."""

    key: str
    title: str
    description: str
    citation_ids: list[str] = field(default_factory=list)
    severity: str = "MEDIUM"             # HIGH|MEDIUM|LOW


@dataclass(frozen=True)
class ScenarioRow:
    item: str                            # 계산 항목
    amount: str                          # 금액 표기(자연어 허용)
    note: str = ""


@dataclass(frozen=True)
class Scenario:
    key: str                             # A|B|C
    label: str
    summary: str
    rows: list[ScenarioRow]              # 세액 계산 표
    tax_burden_eok: float                # 추가 세부담(억원, 비교차트용)
    pros: str
    cons: str
    citation_ids: list[str] = field(default_factory=list)
    recommended: bool = False


@dataclass(frozen=True)
class TimelineStep:
    seq: int
    date_label: str
    action: str
    tax_effect: str
    citation_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WaterfallStep:
    label: str
    delta_eok: float                     # 증감(억원); 첫/마지막은 절대값
    is_total: bool = False


@dataclass
class TaxPlanData:
    title: str
    group_name: str
    as_of: date
    objective: str                       # 플랜 목표
    executive_summary: str
    entities: list[str]                  # 그룹 구성(설명 줄)
    holdings_before: list[Holding]
    holdings_after: list[Holding]
    balance_sheet: FinancialStatement
    income_statement: FinancialStatement
    issues: list[IssueItem]
    scenarios: list[Scenario]
    recommended_note: str                # 권고 시나리오 근거
    timeline: list[TimelineStep]
    gift_tax_before_eok: float           # 정리 전 증여세(억)
    gift_tax_after_eok: float            # 정리 후 증여세(억)
    gift_tax_waterfall: list[WaterfallStep]
    gift_tax_note: str
    citations: list[Citation]
    review_points: list[str]             # 회계사 검토 필요사항(인용 불요)
    procedure_notes: list[str]           # 상법 절차·부당행위 등 인용 없는 주(註)
    conclusion: str
    data_limits: list[str]
    source_objects: list[object] = field(default_factory=list)

    @property
    def citation_index(self) -> dict[str, Citation]:
        return {c.citation_id: c for c in self.citations}


# --------------------------------------------------------------------------- #
# 대표 데모 — 한맥그룹 가업승계 주식정리 Tax Plan (결정적, 오프라인)
# --------------------------------------------------------------------------- #
_CLIENT, _MATTER = "client_hanmaek", "matter_hanmaek_2026"
_AS_OF, _LOOKUP = date(2026, 1, 1), date(2024, 1, 1)


def _cite(law_name: str, article: str, key: str):
    law = default_law_source()
    lk = replace(law.lookup_provision(law_name, article, _LOOKUP), as_of_date=_AS_OF)
    b = build_law_source_answer(
        lookup=lk, client_id=_CLIENT, answer_run_id=f"ar_{_MATTER}",
        source_answer_id=f"sa_{_MATTER}_{key}", source_type_label="법률", matter_id=_MATTER)
    return b.citation, lk.article_title, b.source_objects


def build_demo_tax_plan() -> tuple[TaxPlanData, dict[str, str], dict[str, str]]:
    """한맥그룹 가업승계 주식정리 Tax Plan(대표 데모) + (titles, articles) 표시 메타."""
    c16, t16, s16 = _cite("법인세법", "제16조", "deemed")        # 의제배당
    c18, t18, s18 = _cite("법인세법", "제18조의2", "recv_div")   # 수입배당금 익금불산입
    c28, t28, s28 = _cite("법인세법", "제28조", "interest")      # 지급이자 손금불산입
    c55, t55, s55 = _cite("법인세법", "제55조의2", "land")       # 비사업용토지 양도 과세특례
    c30, t30, s30 = _cite("조세특례제한법", "제30조의6", "succ")  # 가업승계 증여세 과세특례
    cits = [c16, c18, c28, c55, c30]
    DEEMED, RECV, INT, LAND, SUCC = (c.citation_id for c in cits)
    titles = {c.citation_id: t for c, t in
              zip(cits, [t16, t18, t28, t55, t30])}
    articles = {c16.citation_id: "제16조", c18.citation_id: "제18조의2",
                c28.citation_id: "제28조", c55.citation_id: "제55조의2",
                c30.citation_id: "제30조의6"}
    source_objects = sum((list(s) for s in (s16, s18, s28, s55, s30)), [])

    # --- 재무상태표 (한맥정밀(주), 2025.12.31, 억원) — 부채·자본 합 = 자산 1,125 --- #
    bs = FinancialStatement(
        title="재무상태표(요약)", period="한맥정밀(주) · 2025년 12월 31일 현재", unit="단위: 억원",
        lines=[
            FinancialLine("[자산]", None, bold=True),
            FinancialLine("현금및현금성자산", 280, indent=1),
            FinancialLine("매출채권", 160, indent=1),
            FinancialLine("재고자산", 130, indent=1),
            FinancialLine("단기대여금(대표이사 가지급금)", 25, is_issue=True,
                          issue_label="가지급금 인정이자 익금산입·업무무관 지급이자 손금불산입 — 승계 전 회수 필요",
                          citation_ids=[INT], indent=1),
            FinancialLine("비업무용 토지", 110, is_issue=True,
                          issue_label="업무무관자산 지급이자 손금불산입 + 양도 시 비사업용토지 추가과세, 주식평가 가산",
                          citation_ids=[INT, LAND], indent=1),
            FinancialLine("토지·건물(사업용)", 240, indent=1),
            FinancialLine("기계장치 등", 180, indent=1),
            FinancialLine("자산총계", 1125, bold=True),
            FinancialLine("[부채]", None, bold=True),
            FinancialLine("매입채무", 80, indent=1),
            FinancialLine("단기차입금", 120, is_issue=True,
                          issue_label="업무무관자산·가지급금 대응분 지급이자 손금불산입 대상",
                          citation_ids=[INT], indent=1),
            FinancialLine("장기차입금", 110, indent=1),
            FinancialLine("부채총계", 310, bold=True),
            FinancialLine("[자본]", None, bold=True),
            FinancialLine("자본금(액면 5,000원×100만주)", 50, indent=1),
            FinancialLine("자본잉여금", 20, indent=1),
            FinancialLine("이익잉여금", 745, is_issue=True,
                          issue_label="환원 방법(현금배당 vs 유상감자)에 따라 세부담·주식가치가 갈림 — 의제배당·수입배당금 익금불산입",
                          citation_ids=[DEEMED, RECV], indent=1),
            FinancialLine("자본총계", 815, bold=True),
        ],
    )
    # --- 손익계산서 (한맥정밀(주), 2025, 억원) --- #
    is_ = FinancialStatement(
        title="손익계산서(요약)", period="한맥정밀(주) · 2025년 1월 1일~12월 31일", unit="단위: 억원",
        lines=[
            FinancialLine("매출액", 1320),
            FinancialLine("매출원가", 920, indent=1),
            FinancialLine("매출총이익", 400, bold=True),
            FinancialLine("판매비와관리비", 250, indent=1),
            FinancialLine("영업이익", 150, bold=True),
            FinancialLine("영업외수익(이자수익·가지급금 인정이자)", 12, is_issue=True,
                          issue_label="대표이사 가지급금 인정이자 익금산입 — 승계 전 가지급금 회수로 해소",
                          citation_ids=[INT], indent=1),
            FinancialLine("영업외비용(지급이자 등)", 20, is_issue=True,
                          issue_label="업무무관자산·가지급금 대응 지급이자 손금불산입 검토",
                          citation_ids=[INT], indent=1),
            FinancialLine("법인세비용차감전순이익", 142, bold=True),
            FinancialLine("법인세비용", 31, indent=1),
            FinancialLine("당기순이익", 111, bold=True),
        ],
    )

    issues = [
        IssueItem("env", "사업회사 누적 이익잉여금 환원(745억)",
                  "한맥정밀의 누적 이익잉여금이 745억원으로, 가업승계 전 이를 지주회사(한맥홀딩스)로 "
                  "효율적으로 환원하면 사업회사 주식가치를 낮춰 증여세 부담을 줄일 수 있습니다. 환원 방법"
                  "(현금배당 vs 유상감자)에 따라 의제배당·수입배당금 익금불산입의 적용이 달라집니다.",
                  citation_ids=[DEEMED, RECV], severity="HIGH"),
        IssueItem("land", "비업무용 토지(110억)",
                  "업무와 무관한 토지는 관련 지급이자가 손금불산입되고, 양도 시 비사업용토지 추가과세가 "
                  "적용되며, 주식평가 시 순자산에 가산되어 승계가치를 높입니다. 승계 전 정리(처분·현물배당)를 "
                  "검토합니다.", citation_ids=[INT, LAND], severity="HIGH"),
        IssueItem("loan", "대표이사 가지급금(25억)",
                  "특수관계인 대여금은 인정이자가 익금산입되고 대응 지급이자가 손금불산입되며, 부당행위계산"
                  "부인 대상이 됩니다. 승계 전 회수가 필요합니다.", citation_ids=[INT], severity="MEDIUM"),
    ]

    scenarios = [
        Scenario(
            key="①", label="현금배당 200억원",
            summary="한맥정밀이 200억원을 현금배당 → 지주회사 한맥홀딩스(95%)는 수입배당금 익금불산입으로 "
            "법인세 부담이 사실상 없으나(지분율·보유기간 요건 충족 시), 오너 직접보유분(5%)은 배당소득으로 "
            "고율 종합과세됩니다.",
            rows=[
                ScenarioRow("배당 총액", "200억원"),
                ScenarioRow("지주 수령(95%)", "190억원",
                            "지분 50% 이상 → 수입배당금 100% 익금불산입(요건 충족 시 법인세 부담 없음)"),
                ScenarioRow("오너 수령(5%)", "10억원", "배당소득 종합과세(최고세율 가정) → 약 4억원"),
                ScenarioRow("추가 세부담", "약 4억원"),
            ],
            tax_burden_eok=4.0,
            pros="절차 단순, 즉시 잉여금 환원. 지주 수령분은 익금불산입으로 사실상 무과세.",
            cons="오너 직접배당분 고율과세. 주식수 불변(가치 인하 효과는 잉여금 감소분에 한정).",
            citation_ids=[RECV]),
        Scenario(
            key="②", label="유상감자 200억원(지주 보유분 부분감자)",
            summary="한맥정밀이 지주 보유주식 일부를 200억원에 유상소각. 의제배당(감자대가-취득가액)은 "
            "수입배당금 익금불산입으로 법인세 부담이 사실상 없고(아래 재원·제외요건 확인 후 확정), 주식수가 "
            "줄어 승계가치가 추가로 낮아집니다.",
            rows=[
                ScenarioRow("감자대가", "200억원"),
                ScenarioRow("소멸주식 취득가액", "60억원", "자본환급분 — 과세 없음"),
                ScenarioRow("의제배당", "140억원", "감자대가-취득가액"),
                ScenarioRow("의제배당 익금불산입", "100%(요건 충족 시)",
                            "지분 50% 이상 + 과세된 잉여금 재원 → 익금불산입. 단 법인세법 제18조의2 제2항의 "
                            "제외(특히 피출자법인 소득에 법인세가 과세되지 않은 자본감소 의제배당) 해당 여부와 "
                            "재원을 확인한 후 확정"),
                ScenarioRow("추가 세부담", "약 0원(재원·요건 충족 시)", "오너 5%는 감자 미참여"),
            ],
            tax_burden_eok=0.0,
            pros="재원·요건 충족 시 법인 단계 무과세에 가깝게 환원 + 주식수 감소로 승계가치 추가 인하. "
            "오너 직접과세 없음.",
            cons="불균등감자 시 부당행위·증여의제 검토 필요, 채권자 보호 등 상법 절차 소요. 익금불산입 제외요건"
            "(미과세 재원)·배당가능이익 확인 필요.",
            citation_ids=[DEEMED, RECV], recommended=True),
        Scenario(
            key="③", label="혼합(비업무용 토지 현물배당 + 유상감자 90억원)",
            summary="비업무용 토지 110억원을 현물배당으로 지주에 이전해 업무무관자산을 정리하고, 잉여금 "
            "90억원을 유상감자합니다. 주식가치를 가장 크게 낮추나 토지 이전 시 양도과세가 발생합니다.",
            rows=[
                ScenarioRow("현물배당(토지)", "110억원", "비사업용토지 추가과세 검토"),
                ScenarioRow("유상감자", "90억원", "의제배당 익금불산입"),
                ScenarioRow("토지 양도과세(추가)", "약 5억원", "비사업용토지 추가세율분 가정"),
                ScenarioRow("추가 세부담", "약 5억원"),
            ],
            tax_burden_eok=5.0,
            pros="업무무관자산까지 정리 → 주식가치 최대 인하, 지급이자 손금불산입 쟁점 동시 해소.",
            cons="토지 이전 시 양도과세 발생, 현물배당 평가·절차 부담.",
            citation_ids=[LAND, DEEMED]),
    ]

    timeline = [
        TimelineStep(1, "2025.12.31", "결산·현황 진단(쟁점 식별)",
                     "가지급금·비업무용토지·잉여금 등 승계 저해요인 식별", []),
        TimelineStep(2, "2026.03", "대표이사 가지급금 25억원 회수",
                     "인정이자 익금·부당행위·지급이자 손금불산입 쟁점 해소", [INT]),
        TimelineStep(3, "2026.06.30", "감정평가 기준일 / 비업무용 토지 정리(처분·현물배당)",
                     "업무무관자산 제거 → 주식 순자산가치 인하, 비사업용토지 과세 검토", [LAND]),
        TimelineStep(4, "2026.07", "한맥정밀 유상감자 200억원(지주 보유분)",
                     "의제배당 수입배당금 익금불산입(재원·요건 충족 시 법인세 부담 없음) + 주식수 감소",
                     [DEEMED, RECV]),
        TimelineStep(5, "2026.08.31", "한맥정밀 결산(환원 후) · 한맥홀딩스 주식 보충적평가",
                     "환원·자산정리 반영된 낮은 평가액 확정(순자산·순손익)", []),
        TimelineStep(6, "2026.09.01", "가업승계 증여(가업 주식) · 증여세 신고",
                     "가업승계 증여세 과세특례 적용, 과거 증여와 10년 경과로 합산과세 회피", [SUCC]),
        TimelineStep(7, "2026.09 이후", "상법 절차 완료 · 사후관리 모니터링",
                     "채권자 보호 공고 완료, 가업 유지·지분 사후관리 요건 점검", []),
    ]

    gift_waterfall = [
        WaterfallStep("정리 전 가업주식 평가", 320, is_total=True),
        WaterfallStep("잉여금 환원(유상감자)", -110),
        WaterfallStep("비업무용 토지·가지급금 정리", -30),
        WaterfallStep("평가시점·감정평가 최적화", 0),
        WaterfallStep("정리 후 가업주식 평가", 180, is_total=True),
    ]

    data = TaxPlanData(
        title="한맥그룹 가업승계 주식정리 세무 실행계획",
        group_name="한맥그룹", as_of=_AS_OF,
        objective="가업승계를 앞두고 (1)사업회사(한맥정밀)의 누적 이익잉여금을 지주회사(한맥홀딩스)로 "
        "법인세 부담 없이 환원하고, (2)비업무용 토지·가지급금 등 업무무관자산을 정리해 주식가치를 낮추며, "
        "(3)가업승계 증여세 과세특례를 활용하고, (4)감정평가·결산·증여 시점을 정렬해 10년 증여합산을 "
        "피함으로써 전체 세부담을 최소화한다.",
        executive_summary=(
            "한맥그룹은 지주회사 한맥홀딩스(오너 100%)가 사업회사 한맥정밀을 95% 보유하는 구조로, 가업승계를 "
            "앞두고 있습니다. 한맥정밀에는 누적 이익잉여금 745억원, 비업무용 토지 110억원, 대표이사 가지급금 "
            "25억원이 있어 그대로 승계하면 주식가치가 높아 증여세 부담이 큽니다. 본 플랜은 ①잉여금 환원 방법을 "
            "비교(현금배당·유상감자·혼합)해 (재원·요건 충족 시) 법인 단계 무과세에 가까운 환원이 가능한 "
            "유상감자(의제배당 수입배당금 익금불산입)를 기준안으로 제시하고, ②가지급금 회수·비업무용 토지 정리로 "
            "업무무관자산을 제거하며, "
            "③정리 후 낮아진 평가액에 가업승계 증여세 과세특례를 적용하고, ④감정평가·결산·증여 일정을 정렬해 "
            "10년 증여합산을 피하는 4단계 전략입니다. 정리 전·후 증여세는 약 50억원에서 약 22억원으로 약 28억원 "
            "절감될 것으로 추정되며(가정 포함), 모든 법적 판단에는 근거 법령을 함께 표기하고 파란색 글씨를 "
            "누르면 원문으로 이동합니다."),
        entities=[
            "한맥홀딩스(주) — 지주회사(비상장). 창업주(오너)가 100% 보유.",
            "한맥정밀(주) — 사업회사(제조). 한맥홀딩스 95% + 오너 5% 보유.",
            "승계 대상 — 오너 보유 한맥홀딩스 주식을 자녀에게 가업승계(증여).",
        ],
        holdings_before=[
            Holding("창업주(오너)", "한맥홀딩스(주)", 100.0),
            Holding("한맥홀딩스(주)", "한맥정밀(주)", 95.0),
            Holding("창업주(오너)", "한맥정밀(주)", 5.0, "직접 보유"),
        ],
        holdings_after=[
            Holding("자녀(승계인)", "한맥홀딩스(주)", 100.0, "가업승계 증여"),
            Holding("한맥홀딩스(주)", "한맥정밀(주)", 95.0, "유상감자 후 주식수 감소"),
        ],
        balance_sheet=bs, income_statement=is_, issues=issues, scenarios=scenarios,
        recommended_note="권고안: 시나리오 ②(유상감자)를 중심으로, 가지급금 회수와 비업무용 토지 정리"
        "(시나리오 ③의 일부)를 결합한다. (지분율·보유기간·과세된 재원 등 익금불산입 요건 충족 시) 법인 단계 "
        "무과세에 가깝게 잉여금을 환원하면서 주식수 감소와 업무무관자산 제거로 승계가치를 최대한 낮춘다. "
        "불균등감자의 부당행위·증여의제, 채권자 보호 절차, 의제배당 익금불산입 제외요건(법인세법 제18조의2 "
        "제2항)은 실행 전 사전 검토한다.",
        timeline=timeline,
        gift_tax_before_eok=50.0, gift_tax_after_eok=22.0,
        gift_tax_waterfall=gift_waterfall,
        gift_tax_note="가업승계 증여세 과세특례(조세특례제한법 제30조의6)는 가업주식 증여 시 과세가액에서 "
        "10억원을 공제하고 과세표준 120억원 이하는 10%, 초과분은 20%의 저율로 과세합니다(한도·사후관리 요건 "
        "별도). 정리 전 평가 약 320억원 기준 증여세는 약 50억원이나, 잉여금 환원·자산정리로 평가액이 약 180억원"
        "으로 낮아지면 증여세는 약 22억원으로 약 28억원 절감됩니다(평가액은 가정).",
        citations=cits,
        review_points=[
            "유상감자 시 불균등감자에 따른 부당행위계산부인·증여의제(특수관계인 간 시가차액) 검토",
            "비상장주식 보충적평가(순손익가치·순자산가치) 산정과 평가 기준일 선택의 적정성",
            "가업승계 증여세 과세특례의 가업영위기간·업종·고용·지분 유지 등 사후관리 요건 충족",
            "비업무용 토지 현물배당 시 시가평가·양도과세와 배당가능이익 한도",
            "수입배당금 익금불산입 적용을 위한 지분율·보유기간 요건 확인",
        ],
        procedure_notes=[
            "유상감자(자본금 감소)는 상법 제439조(자본금 감소의 방법·절차)에 따라 주주총회 특별결의와 "
            "제232조(채권자의 이의) 공고·최고 절차(1개월 이상)를 거쳐야 합니다.",
            "특수관계인 간 불균등 자본거래는 부당행위계산부인(법인세법 제52조)과 상속세및증여세법상 "
            "증여의제(감자·증자에 따른 이익) 기준을 함께 검토합니다.",
        ],
        conclusion="잉여금을 (재원·요건 충족 시) 법인 단계 무과세에 가깝게 환원(유상감자·의제배당 익금불산입)"
        "하고 업무무관자산을 정리해 가업주식 평가액을 낮춘 뒤 가업승계 증여세 과세특례를 적용하면, 증여세 "
        "부담을 약 28억원 절감할 수 있을 것으로 추정됩니다. 다만 평가액·익금불산입 요건(제외요건 포함)·"
        "사후관리·부당행위 검토가 선행되어야 하며, 실행 시점은 10년 증여합산 회피와 감정평가 재활용을 고려해 "
        "정렬합니다. 최종 실행은 회계사 검토·승인 후 진행합니다.",
        data_limits=[
            "주식 평가액(정리 전 약 320억·정리 후 약 180억)과 소멸주식 취득가액 등은 가정치 — 실제 보충적평가로 재계산 필요",
            "유상감자 의제배당의 수입배당금 익금불산입은 지분율·보유기간·배당가능이익 요건과 함께 법인세법 "
            "제18조의2 제2항 각 호의 제외(특히 피출자법인 소득에 법인세가 과세되지 않은 자본감소 의제배당 재원 "
            "등) 확인 후 확정 — 본문의 '법인세 0/무과세'는 이 요건 충족을 전제로 한 표현",
            "근거 법령은 2024.1.1 시행분을 기준으로 조회(오프라인 법령 재현)한 뒤 2026 검토기준일 문서로 표시 "
            "— 2024.1.1 이후 개정분은 실행 전 최신 법령으로 재확인 필요",
            "상법 감자절차·부당행위계산부인은 조문 인용 없이 절차·검토 주(註)로 표기",
            "본 플랜은 가상의 동족기업 사례이며 특정 기업에 대한 실제 자문이 아님",
        ],
        source_objects=source_objects,
    )
    return data, titles, articles
