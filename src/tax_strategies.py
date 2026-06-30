"""src/tax_strategies.py — 법인 절세전략 라이브러리 + 재무제표 기반 스크리닝.

가업승계 한 가지에 고정하지 않고, **다수의 법인 절세전략을 카탈로그**로 두고 회사 재무제표·
프로필에 대해 **적용 여부를 스크리닝**한다(미해당도 사유를 표기). 각 전략은 작동원리·적용요건·
트리거 재무항목·기대효과(정성/추정)·리스크·**필요 조치(actions)**·**필요 자료(required_data)**·
**사후관리(post_management)**·회계사 검토포인트·근거 조문을 담는다.

근거 조문은 **오프라인 법령 재현의 실제 시행일 버전객체**만 인용한다(날조 0). 오프라인 파싱이
불가한 조문(조특법 제24조 통합투자세액공제·법인세법 제13조 이월결손금 등)은 **링크 없이 검토
주(註)** 로 두고 실행 전 원문 확인을 요구한다.

정직성: 회사별 정확한 절세액은 상세자료 없이 단정하지 않는다(정성 등급). 사후관리 기간 등 시점에
따라 개정된 요건은 '시행시점 확인' 단서를 단다.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional


@dataclass(frozen=True)
class StrategyCard:
    key: str
    category: str
    title: str
    mechanism: str                        # 작동 원리(절세 메커니즘)
    requirement: str                      # 적용 요건
    trigger: str                          # 어떤 재무항목/상황이 촉발하나
    effect: str                           # 기대 효과(자연어, 추정/정성)
    risk: str                             # 리스크·유의
    actions: list[str] = field(default_factory=list)        # 필요 조치(실행 액션)
    required_data: list[str] = field(default_factory=list)  # 필요 자료
    post_management: str = ""             # 사후관리 요건(정확)
    review_points: list[str] = field(default_factory=list)  # 회계사 검토포인트
    citation_articles: list[tuple[str, str]] = field(default_factory=list)
    note_only_basis: str = ""
    # 스크리닝 결과(런타임 set)
    applies: bool = True
    applicability_note: str = ""
    effect_tier: str = "중간"             # 높음|중간|낮음|정성 — 비교 도표용(계량 아님)
    priority: int = 50


@dataclass(frozen=True)
class CompanyProfile:
    """스크리닝 입력 — 재무제표·정성 프로필(원 단위 raw 값)."""

    name: str
    retained_earnings: float
    tangible_assets: float
    revenue: float
    borrowings: float
    is_sme: bool
    rnd_active: bool
    family_controlled: bool
    has_idle_land: bool = False
    has_company_cars: bool = True
    expects_new_investment: bool = False
    expects_headcount_growth: bool = False


# --------------------------------------------------------------------------- #
# 카탈로그
# --------------------------------------------------------------------------- #
def corporate_strategy_catalog() -> list[StrategyCard]:
    return [
        # ── 잉여금 환원·자본거래 ─────────────────────────────────────────── #
        StrategyCard(
            key="recv_div", category="잉여금 환원·자본거래",
            title="지주구조 활용 수입배당금 익금불산입",
            mechanism="사업회사의 이익잉여금을 배당으로 지주회사에 올릴 때, 일정 지분율 이상이면 받은 "
            "배당금을 익금에 넣지 않아(익금불산입) 법인 단계 추가 과세 없이 자금을 모읍니다.",
            requirement="지분율·보유기간 요건 충족, 배당가능이익·과세된 재원 확인(법인세법 제18조의2 "
            "제2항 제외요건 점검).",
            trigger="누적 이익잉여금이 크고 지주-사업회사 구조가 있을 때.",
            effect="배당 수령 법인 단계의 추가 법인세 부담을 사실상 제거(요건 충족 시). 절감액은 배당 "
            "규모·지분율에 따름(추정).",
            risk="제18조의2 제2항 제외(미과세 재원 등) 해당 시 익금불산입 배제. 지분율·보유기간 미충족 위험.",
            actions=["지주회사의 사업회사 지분율이 익금불산입 구간을 충족하는지 점검",
                     "배당기준일·보유기간 요건에 맞춰 배당 의사결정",
                     "수입배당금 익금불산입 명세서 작성·신고 반영"],
            required_data=["주주명부·지분율 내역", "배당결의서·배당기준일 자료",
                           "피출자법인의 배당가능이익·과세된 잉여금 명세"],
            post_management="별도의 처분·유지 사후관리(추징) 규정은 없으나, 배당기준일 현재 지분율·보유기간"
            " 요건과 제18조의2 제2항 각 호의 제외(피출자법인 미과세 재원 등) 해당 여부로 판정되므로 관련 "
            "자료를 보관한다.",
            review_points=["지분율·보유기간 요건", "배당가능이익·과세된 재원 확인", "제2항 제외요건 해당 여부"],
            citation_articles=[("법인세법", "제18조의2")], effect_tier="높음", priority=20),
        StrategyCard(
            key="deemed_div", category="잉여금 환원·자본거래",
            title="유상감자·이익소각을 통한 잉여금 환원(의제배당)",
            mechanism="주식을 유상소각하면 감자대가에서 취득가액을 뺀 금액이 의제배당이 되며, 법인 "
            "주주는 수입배당금 익금불산입과 결합해 낮은 부담으로 잉여금을 환원하고 주식수를 줄입니다.",
            requirement="상법상 감자절차(주주총회 특별결의·채권자 보호)와 불균등감자 시 부당행위·증여의제 검토.",
            trigger="이익잉여금이 크고 주식가치 인하(승계 등)가 필요할 때.",
            effect="법인 단계 저(무)과세 환원 + 주식수 감소로 승계가치 인하(요건·재원 충족 시, 추정).",
            risk="불균등감자 부당행위계산부인·증여의제, 상법 절차 비용. 익금불산입 제외요건 동일.",
            actions=["감자 규모·대상 주식·소멸주식 취득가액 산정",
                     "주주총회 특별결의·채권자 보호절차(공고·최고) 진행",
                     "의제배당·수입배당금 익금불산입 세무조정"],
            required_data=["소멸주식 취득가액 증빙", "감자 결의서·자본금 변경등기",
                           "채권자 보호절차 증빙", "불균등감자 시 보충적평가 자료"],
            post_management="자본거래 완료 후 불균등감자에 따른 부당행위계산부인·증여의제 해당 여부를 사후 "
            "점검하고, 익금불산입 요건·재원 자료를 보관한다.",
            review_points=["감자절차 적법성", "불균등감자 시 시가차액 증여의제", "취득가액 산정"],
            citation_articles=[("법인세법", "제16조"), ("법인세법", "제18조의2")],
            effect_tier="높음", priority=25),
        # ── 세액공제·감면 ──────────────────────────────────────────────── #
        StrategyCard(
            key="rnd_credit", category="세액공제·감면",
            title="연구·인력개발비 세액공제",
            mechanism="연구개발·인력개발에 쓴 비용의 일정 비율을 산출세액에서 직접 공제합니다"
            "(당기분·증가분 방식 중 선택).",
            requirement="연구개발 활동·전담부서·비용의 적격성 입증(연구노트·과제 증빙).",
            trigger="제조·기술기업의 상시적 연구개발 지출.",
            effect="연구개발 지출 규모에 비례한 세액 직접 공제(공제율은 기업규모·증감에 따라 상이 — 별도 산정).",
            risk="비용 적격성·구분경리 미흡 시 공제 부인. 사후 검증 리스크.",
            actions=["연구개발 과제·전담조직 정의",
                     "당기분 방식과 증가분 방식의 공제액을 비교해 유리한 방식 선택",
                     "연구·인력개발비 명세서 작성·세액공제 신청"],
            required_data=["연구개발계획서·연구노트·연구보고서",
                           "과제별 인건비·재료비·위탁연구비 명세", "연구전담부서 인정서·조직도·인력명단"],
            post_management="공제 자체에는 자산 처분·유지 같은 사후관리가 없으나, 적격 연구개발비 입증서류"
            "(연구노트 등)를 보관해 사후 검증·경정에 대비한다. 신성장·원천기술 공제는 별도 요건·구분경리가 필요하다.",
            review_points=["적격 연구개발비 범위", "당기분 대 증가분 유리한 방식 선택", "전담조직·증빙"],
            citation_articles=[("조세특례제한법", "제10조")], effect_tier="높음", priority=15),
        StrategyCard(
            key="invest_credit", category="세액공제·감면",
            title="통합투자세액공제(신규 설비·시설 투자)",
            mechanism="사업용 유형자산 등에 신규 투자하면 투자금액의 일정률(기본+추가)을 세액공제합니다.",
            requirement="적격 투자자산·투자완료·사후 처분제한 요건 충족.",
            trigger="설비·시설 신규 투자 계획이 있을 때.",
            effect="신규 투자액에 비례한 세액공제(투자 규모·업종·증가분에 따라 상이 — 별도 산정).",
            risk="조기 처분 시 공제 추징, 적격자산 범위 판정.",
            actions=["적격 투자자산 여부·투자완료 시점 확인",
                     "기본공제와 추가공제(직전 3년 평균 초과분) 요건 검토",
                     "투자세액공제 신청·최저한세 검토"],
            required_data=["투자계약서·세금계산서·자산 취득 증빙", "투자자산 사용개시·설치 증빙",
                           "직전 3년 투자내역(추가공제 산정용)"],
            post_management="공제 대상 자산을 투자완료일부터 일정 기간(통상 2년 등 — 시행시점·자산별 기준 "
            "확인) 내에 처분·임대·다른 목적으로 전용하면 공제세액에 이자상당액을 더해 추징하므로, 자산 사용·"
            "보유현황을 관리한다.",
            review_points=["적격 투자자산 여부", "기본공제·추가공제 요건", "사후 처분제한"],
            note_only_basis="조세특례제한법 제24조(통합투자세액공제) — 본 도구의 오프라인 법령 재현에서 "
            "조문 파싱이 불가해 링크를 생략합니다. 실행 전 원문·당해연도 개정 확인 필요.",
            effect_tier="중간", priority=30),
        StrategyCard(
            key="emp_credit", category="세액공제·감면",
            title="고용을 증대시킨 기업에 대한 세액공제",
            mechanism="상시근로자 수가 늘면 증가 인원에 대해 일정액을 세액공제합니다(청년·일반 구분).",
            requirement="상시근로자 수 증가, 고용 유지(미달 시 추징).",
            trigger="고용 증가 계획이 있을 때.",
            effect="증가 고용 인원에 비례한 세액공제(연도·인원 구분에 따라 상이 — 별도 산정).",
            risk="이후 고용 감소 시 공제액 추징. 상시근로자 계산 기준.",
            actions=["상시근로자 수 증가 여부 산정(청년·일반 구분)",
                     "세액공제 신청 및 향후 고용 유지 계획 수립"],
            required_data=["월별 상시근로자 명부·4대보험 자료", "청년·장애인 등 구분 자료", "근로계약서"],
            post_management="공제받은 과세연도의 종료일부터 일정 기간(통상 2년 — 시행시점 확인) 내에 상시"
            "근로자 수가 감소하면 공제받은 세액을 추징하므로 고용 규모를 유지·관리한다. 현재는 통합고용세액"
            "공제로 개편되었으므로 적용 연도의 제도를 확인한다.",
            review_points=["상시근로자 수 계산", "청년·일반 구분", "사후 고용 유지요건"],
            citation_articles=[("조세특례제한법", "제29조의7")], effect_tier="중간", priority=35),
        StrategyCard(
            key="sme_relief", category="세액공제·감면",
            title="중소기업에 대한 특별세액감면",
            mechanism="중소기업이 영위하는 감면대상 업종 소득에 대해 산출세액의 일정률을 감면합니다.",
            requirement="조특법상 중소기업 요건(매출·자산·독립성)과 감면대상 업종 충족.",
            trigger="중소기업 해당 시.",
            effect="감면율(업종·지역·규모별)에 따른 산출세액 직접 감면.",
            risk="중소기업 졸업·업종 비해당 시 적용 불가. 최저한세 적용.",
            actions=["중소기업 요건·감면대상 업종 해당 여부 판정", "감면율 적용·최저한세 비교"],
            required_data=["매출·자산·상시근로자 등 중소기업 판정 자료", "업종 분류 자료"],
            post_management="별도의 처분·유지 사후관리는 없으며, 각 사업연도마다 중소기업·업종 요건 충족 "
            "여부로 새로 판정한다(중소기업 졸업 시 유예 규정 확인).",
            review_points=["중소기업 요건 충족", "감면대상 업종", "최저한세"],
            citation_articles=[("조세특례제한법", "제7조")], effect_tier="중간", priority=40),
        # ── 손금·익금 최적화 ───────────────────────────────────────────── #
        StrategyCard(
            key="depreciation", category="손금·익금 최적화",
            title="감가상각 방법·내용연수 최적화",
            mechanism="자산별 상각방법(정액·정률)과 내용연수 범위를 적정 선택해 손금 귀속시기를 조정하고, "
            "즉시상각의제·특례를 활용합니다.",
            requirement="신고 내용연수 범위 내 선택, 일관 적용. 자본적지출과 수익적지출 구분.",
            trigger="유형자산 규모가 클 때.",
            effect="손금 인식 시기 조정으로 과세 평탄화(영구 절감보다 시기 효과 중심, 정성).",
            risk="자본적지출의 수익적지출 처리 시 부인. 방법 변경 제한.",
            actions=["자산별 상각방법·내용연수(범위 내) 선택·신고",
                     "자본적지출과 수익적지출 구분", "즉시상각의제·특례 적용 검토"],
            required_data=["유형자산 대장·취득명세", "내용연수 신고서", "수선비 내역"],
            post_management="선택한 상각방법·내용연수는 임의 변경이 제한되므로 일관 적용하고, 변경 시 사유·"
            "승인 요건을 확인한다.",
            review_points=["내용연수·상각방법 적정성", "자본적·수익적 지출 구분", "즉시상각의제 한도"],
            citation_articles=[("법인세법", "제23조")], effect_tier="중간", priority=45),
        StrategyCard(
            key="entertain", category="손금·익금 최적화",
            title="기업업무추진비(접대비) 한도 관리",
            mechanism="기업업무추진비는 기본한도 + 수입금액별 한도까지만 손금 인정되므로, 한도 내 집행·"
            "적격증빙 관리로 손금부인을 예방합니다.",
            requirement="건당 기준금액 초과 시 적격증빙(신용카드 등), 한도 내 집행.",
            trigger="매출(수입금액) 규모가 클 때 — 한도 산정의 기준.",
            effect="한도 초과·증빙 미비로 인한 손금부인을 예방(절감이 아니라 손실 방지 성격).",
            risk="한도 초과분·증빙 누락분 손금불산입. 업무무관 지출 혼입.",
            actions=["수입금액 기준 한도 재계산",
                     "건당 기준금액 초과분 적격증빙(신용카드 등) 확인",
                     "한도 초과·업무무관 지출 손금부인 조정"],
            required_data=["기업업무추진비 계정별원장·증빙", "수입금액(매출) 명세", "경조사비 등 한도 항목 내역"],
            post_management="별도 사후관리는 없으나 적격증빙을 보관하고, 한도 초과분·증빙 미비분의 손금불산입"
            " 조정을 신고에 반영한다.",
            review_points=["수입금액별 한도 재계산", "적격증빙 구비", "업무관련성"],
            citation_articles=[("법인세법", "제25조")], effect_tier="중간", priority=50),
        StrategyCard(
            key="company_car", category="손금·익금 최적화",
            title="업무용승용차 관련비용 손금관리",
            mechanism="업무용승용차는 운행기록부·전용보험 등 요건과 한도(감가상각·처분손실 포함) 내에서만 "
            "손금 인정되므로 요건 구비로 손금부인을 예방합니다.",
            requirement="업무전용 자동차보험 가입, 운행기록부 작성, 한도 관리.",
            trigger="법인 명의 승용차 보유 시.",
            effect="요건 미비로 인한 손금부인 예방(손실 방지 성격).",
            risk="운행기록 미작성 시 비용 한도 축소, 사적사용 부인.",
            actions=["업무전용 자동차보험 가입 확인", "운행기록부 작성·업무사용비율 산정",
                     "감가상각·처분손실 한도 적용"],
            required_data=["차량 보유·보험 가입 내역", "운행기록부", "차량 관련비용 명세"],
            post_management="운행기록부·보험 자료를 보관하고, 한도를 초과한 감가상각비·처분손실은 다음 "
            "사업연도로 이월해 손금산입한다.",
            review_points=["전용보험·운행기록부", "감가상각·임차료 한도", "처분손실 한도"],
            citation_articles=[("법인세법", "제27조의2")], effect_tier="낮음", priority=60),
        StrategyCard(
            key="bad_debt_reserve", category="손금·익금 최적화",
            title="대손충당금 손금산입",
            mechanism="채권 잔액에 대해 한도 내 대손충당금을 설정해 손금에 산입하면 과세소득을 이연·"
            "평탄화할 수 있습니다.",
            requirement="설정대상 채권·한도율(법정률과 대손실적률 중 큰 값) 적용.",
            trigger="매출채권·기타채권 잔액이 있을 때.",
            effect="한도 내 충당금 손금산입으로 과세 이연(시기 효과, 정성).",
            risk="한도 초과 설정 부인, 환입 누락.",
            actions=["설정대상 채권·한도(법정률 1% 대 대손실적률) 산정", "전기 충당금 환입 처리"],
            required_data=["채권 잔액 명세(매출채권·기타채권)", "대손 실적 자료", "전기 충당금 내역"],
            post_management="전기에 손금산입한 대손충당금은 당기에 전액 환입(익금)하고 당기 한도로 재설정하는"
            " 총액법 기준을 유지한다.",
            review_points=["설정대상 채권 범위", "대손실적률 산정", "전기 충당금 환입"],
            citation_articles=[("법인세법", "제34조")], effect_tier="낮음", priority=55),
        StrategyCard(
            key="retire_reserve", category="손금·익금 최적화",
            title="퇴직급여충당금·퇴직연금 손금산입",
            mechanism="확정급여형 퇴직연금 등 사외적립을 활용하면 한도 내에서 손금산입이 가능합니다.",
            requirement="사외적립(확정급여형) 납입, 한도 관리.",
            trigger="종업원 퇴직급여 부채가 있을 때.",
            effect="사외적립분 한도 내 손금산입으로 과세 이연(시기 효과, 정성).",
            risk="충당금 한도 축소 추세, 적립방식 요건.",
            actions=["확정급여형 퇴직연금 사외적립 규모 결정", "퇴직급여 추계액·손금한도 산정"],
            required_data=["퇴직급여 추계액 자료", "퇴직연금 적립·운용 내역", "임원 퇴직급여 규정"],
            post_management="사외적립 수준을 유지하고, 임원 퇴직급여는 정관·규정 한도 내에서 지급해야 손금"
            "으로 인정된다.",
            review_points=["퇴직연금 적립방식", "손금산입 한도", "추계액 산정"],
            citation_articles=[("법인세법", "제33조")], effect_tier="낮음", priority=58),
        StrategyCard(
            key="bad_debt", category="손금·익금 최적화",
            title="대손금 손금산입 시기 관리",
            mechanism="회수불능이 확정된 채권을 대손요건 충족 시점에 손금산입해 과세소득을 줄입니다.",
            requirement="법정 대손사유·확정시점·증빙 충족.",
            trigger="회수의문 채권이 있을 때.",
            effect="적격 대손금의 손금산입(요건 충족분에 한함).",
            risk="대손요건 미충족 시 부인, 시기 오인.",
            actions=["법정 대손사유·확정시점 확인", "대손금 손금산입 세무조정"],
            required_data=["채권별 회수노력·부도·소멸시효 증빙", "특수관계인 채권 여부 자료"],
            post_management="대손처리 후 회수되는 금액은 회수한 사업연도의 익금으로 산입한다. 특수관계인 "
            "채권 등 손금 제한 항목을 점검한다.",
            review_points=["법정 대손사유 해당", "확정시점·증빙", "특수관계인 채권 제한"],
            citation_articles=[("법인세법", "제19조의2")], effect_tier="낮음", priority=62),
        # ── 자산·부채 정리 ─────────────────────────────────────────────── #
        StrategyCard(
            key="interest_loan", category="자산·부채 정리",
            title="가지급금·업무무관자산 정리(지급이자 손금불산입 해소)",
            mechanism="대표이사 가지급금·업무무관자산이 있으면 대응 지급이자가 손금불산입되고 인정이자가 "
            "익금산입되므로, 회수·정리로 손금부인과 부당행위 쟁점을 해소합니다.",
            requirement="가지급금 회수, 업무무관자산 처분.",
            trigger="가지급금·업무무관자산과 차입금이 함께 있을 때.",
            effect="지급이자 손금불산입·인정이자 익금산입 쟁점 해소(차입 규모에 비례, 정성).",
            risk="회수 과정의 자금출처·부당행위 검토.",
            actions=["가지급금 잔액·인정이자 산정", "가지급금 회수·업무무관자산 처분 계획 수립",
                     "지급이자 손금불산입 세무조정"],
            required_data=["가지급금·가수금 계정별원장", "차입금·지급이자 명세", "업무무관자산 내역"],
            post_management="가지급금이 남아 있는 동안 매년 인정이자 익금산입·지급이자 손금불산입이 반복되"
            "므로, 회수 전까지 관리하고 회수계획 이행 여부를 점검한다.",
            review_points=["가지급금 잔액·인정이자", "업무무관자산 판정", "차입금 대응 비율"],
            citation_articles=[("법인세법", "제28조")], effect_tier="중간", priority=33),
        StrategyCard(
            key="idle_land", category="자산·부채 정리",
            title="비사업용(업무무관) 토지 정리",
            mechanism="비사업용 토지는 양도 시 추가과세되고 주식평가 순자산에 가산되므로, 사업용 전환·"
            "처분으로 과세·평가 부담을 낮춥니다.",
            requirement="비사업용 판정 기준 검토, 사업용 전환 요건.",
            trigger="업무무관 토지를 보유할 때.",
            effect="양도 추가과세·주식평가 가산 부담 완화(보유·처분 계획에 따름, 정성).",
            risk="비사업용 판정·기간 요건, 처분 시 양도과세.",
            actions=["비사업용 토지 판정(보유기간·사용현황)", "사업용 전환 또는 처분 계획 수립"],
            required_data=["토지 등기·이용현황 자료", "보유기간·사용내역"],
            post_management="사업용으로 전환한 뒤에도 일정 기간 사업 사용 요건을 충족해야 비사업용 판정을 "
            "벗어나므로 이용현황을 관리한다.",
            review_points=["비사업용 토지 판정", "사업용 전환 가능성", "주식평가 영향"],
            citation_articles=[("법인세법", "제55조의2")], effect_tier="낮음", priority=48),
        # ── 가업승계 ──────────────────────────────────────────────────── #
        StrategyCard(
            key="succession", category="가업승계",
            title="가업승계 증여세 과세특례",
            mechanism="가업주식을 자녀에게 증여할 때 과세가액에서 공제하고 저율 과세하는 특례를 적용해 "
            "승계 단계의 증여세 부담을 줄입니다(공제·세율구간·사후관리 별도).",
            requirement="가업영위기간·업종·지분·사후관리(고용·지분 유지) 요건 충족.",
            trigger="동족기업의 세대 간 지분 승계가 예정될 때.",
            effect="평가액에서 공제 + 저율 과세로 증여세 절감(평가액·구간에 따름, 추정·가정).",
            risk="사후관리 위반 시 증여세 추징, 평가액 변동.",
            actions=["가업·업종·지분·승계인 요건 충족 여부 사전 검토",
                     "주식 보충적평가·증여 시점 설계", "증여세 신고·특례 신청"],
            required_data=["가업영위기간·업종 자료", "주주명부·지분 변동내역", "재무제표·보충적평가 자료"],
            post_management="증여 후 수증자는 증여세 신고기한까지 가업에 종사하고 일정 기간 내 대표이사에 "
            "취임해야 하며, 사후관리기간(시행시점에 따라 5~7년 — 적용연도 확인) 동안 가업 유지·업종·지분·"
            "고용 요건을 충족해야 한다. 위반 시 증여세와 이자상당액이 추징된다.",
            review_points=["가업·업종·지분 요건", "사후관리 이행", "보충적평가액 산정"],
            citation_articles=[("조세특례제한법", "제30조의6")], effect_tier="높음", priority=70),
    ]


# --------------------------------------------------------------------------- #
# 스크리닝
# --------------------------------------------------------------------------- #
_SME_REVENUE_CEILING = 150_000_000_000  # 중소기업 매출 기준(업종 평균값, 단순 스크리닝용 보수치)


def screen_strategies(profile: CompanyProfile,
                      catalog: Optional[list[StrategyCard]] = None) -> list[StrategyCard]:
    """프로필에 대해 각 전략의 적용 여부·사유를 판정한 카드 목록(미해당도 사유와 함께 노출)."""
    cards = catalog if catalog is not None else corporate_strategy_catalog()
    out: list[StrategyCard] = []
    big = profile.revenue >= _SME_REVENUE_CEILING
    for c in cards:
        applies, note = True, ""
        k = c.key
        if k in ("recv_div", "deemed_div"):
            applies = profile.retained_earnings > 0
            note = ("누적 이익잉여금이 커 잉여금 환원 여지가 큼" if applies
                    else "환원할 이익잉여금이 없음")
        elif k == "succession":
            applies = profile.family_controlled
            note = ("동족기업으로 세대 간 지분 승계 검토 대상" if applies
                    else "동족 승계 구조 아님")
        elif k == "rnd_credit":
            applies = profile.rnd_active
            note = ("상시적 연구개발 지출 추정 — 적격성 입증 시 적용" if applies
                    else "연구개발 활동 미확인")
        elif k == "invest_credit":
            applies = profile.expects_new_investment or profile.tangible_assets > 0
            note = ("유형자산 규모가 크고 신규 설비투자 시 적용 가능(조건부)" if applies
                    else "신규 투자 계획 미확인")
        elif k == "emp_credit":
            applies = profile.expects_headcount_growth
            note = ("고용 증가 계획 시 적용(조건부)" if applies
                    else "고용 증가 계획 미확인 — 해당 연도 고용 증감 확인 필요")
        elif k == "sme_relief":
            applies = profile.is_sme and not big
            note = ("중소기업 요건 충족 시 적용" if applies
                    else f"매출 규모(약 {profile.revenue/1e8:,.0f}억원)가 커 중소기업 기준 초과로 미해당")
        elif k == "depreciation":
            applies = profile.tangible_assets > 0
            note = ("유형자산 규모가 커 상각방법·내용연수 관리 실익 큼" if applies
                    else "유형자산 미미")
        elif k == "entertain":
            applies = profile.revenue > 0
            note = "수입금액 기준으로 한도 재계산·증빙관리 필요"
        elif k == "company_car":
            applies = profile.has_company_cars
            note = ("법인 승용차 보유 — 운행기록·전용보험 요건 관리" if applies
                    else "법인 승용차 미보유")
        elif k in ("bad_debt_reserve", "bad_debt"):
            applies = True
            note = "매출채권·기타채권 잔액 대상 — 충당금 한도·대손요건 관리"
        elif k == "retire_reserve":
            applies = True
            note = "종업원 퇴직급여 부채 대상 — 사외적립 방식·한도 관리"
        elif k == "interest_loan":
            applies = profile.borrowings > 0
            note = ("차입금이 있어 가지급금·업무무관자산 대응 지급이자 점검 필요" if applies
                    else "차입금이 거의 없어 지급이자 손금불산입 쟁점 가능성 낮음")
        elif k == "idle_land":
            applies = profile.has_idle_land
            note = ("업무무관 토지 보유 — 정리 시 과세·평가 부담 완화" if applies
                    else "업무무관 토지 미보유(확인 권장)")
        out.append(replace(c, applies=applies, applicability_note=note))
    return out
