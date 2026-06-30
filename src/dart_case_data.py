"""src/dart_case_data.py — DART 실재무 회사 1곳 → 종합세무검토 + 회사 그라운딩 시나리오.

``dart_fetch.CompanyFinancials`` 의 **실제 공시 수치**를 단서로 (1) 회사 개요, (2) 종합세무검토
(재무제표→잠재 세무쟁점), (3) 회사 그라운딩 **[사실관계]** 시나리오(자기주식·임원보수·가지급금·
연구개발 세액공제)를 구성한다. 시나리오의 분기·결론·근거는 ``scenario_planner`` 의 일반 의사결정
구조를 재사용하고, **[사실관계](facts)·분개 금액만 회사 수치 맥락으로 합성**한다.

원칙: 재무수치는 DART 실값(검증가능), 그 외 분개·증빙·거래 사실관계는 **추론용 가상(dummy)**으로
명시한다. 근거(법령)는 시나리오 모델이 강제한다(날조 금지).
"""
from __future__ import annotations

import dataclasses

from src.scenario_planner import (
    Gate,
    JournalIllustration,
    JournalLine,
    Leaf,
    PlanAlt,
    PlanStep,
    Scenario,
    demo_scenarios,
)


def _eok(v) -> str:
    return f"약 {v / 1e8:,.0f}억원" if v else "—"


def _get(fin, *names, statement=None):
    return fin.find(*names, statement=statement)


def _figs(fin) -> dict:
    asset = _get(fin, "자산총계", statement="BS")
    equity = _get(fin, "자본총계", statement="BS")
    capital = _get(fin, "자본금", statement="BS")
    retained = _get(fin, "이익잉여금", statement="BS")
    sales = _get(fin, "매출액", "수익(매출액)")
    op = _get(fin, "영업이익")
    ni = _get(fin, "당기순이익")
    liab = (asset - equity) if (asset and equity) else None
    ratio = (retained / capital) if (capital and retained) else None
    return dict(asset=asset, equity=equity, capital=capital, retained=retained,
                sales=sales, op=op, ni=ni, liab=liab, ratio=ratio)


def company_overview(fin) -> tuple[list[tuple[str, str]], str, str]:
    f = _figs(fin)
    fs_label = "연결" if fin.fs_div == "CFS" else "별도"
    rows = [
        ("회사명 / 종목코드", f"{fin.corp_name} / {fin.stock_code}"),
        ("기준 재무제표", f"{fin.year} 사업연도 · {fs_label} (DART 전자공시)"),
        ("자산총계", _eok(f["asset"])),
        ("부채총계", _eok(f["liab"])),
        ("자본총계", _eok(f["equity"])),
        ("자본금", _eok(f["capital"])),
        ("이익잉여금", _eok(f["retained"])),
        ("매출액", _eok(f["sales"])),
        ("영업이익", _eok(f["op"])),
        ("당기순이익", _eok(f["ni"])),
    ]
    ratio_txt = f"약 {f['ratio']:,.0f}배" if f["ratio"] else "상당 규모"
    note = (
        f"{fic(fin)}는 반도체 후공정 장비를 제조하는 상장 제조기업으로, 높은 영업이익률과 "
        f"꾸준한 이익 누적으로 자본금 대비 이익잉여금이 {ratio_txt} 쌓여 있습니다(DART 공시). "
        "이는 ① 잉여금 환원(자기주식·배당)·승계 자본거래, ② 오너 임원 보수·퇴직금, "
        "③ 특수관계 자금거래(가지급금), ④ 연구개발 세액공제 등에서 세무 설계·리스크 관리의 "
        "여지가 크다는 의미입니다. 아래 종합세무검토에서 쟁점을 도출하고, 3장 이하에서 각 거래를 "
        "‘경우의 수’로 분기하여 절세전략과 세무리스크를 제시합니다."
    )
    src_note = (
        f"※ 회사명·재무수치는 {fin.corp_name}의 DART 전자공시({fin.year} 사업연도, {fs_label}) "
        "실제값입니다. 분개·원장·증빙·구체적 거래 사실관계(주식수·보수액·대여금 등)는 추론을 위해 "
        "가상 생성(dummy)한 예시이며 실제와 무관합니다."
    )
    return rows, note, src_note


def fic(fin) -> str:
    return fin.corp_name


def comprehensive_review(fin) -> list[tuple[str, str, str, str]]:
    """재무제표 단서 → 잠재 세무쟁점·검토방향·근거. (종합세무검토 표)"""
    f = _figs(fin)
    return [
        (f"이익잉여금 {_eok(f['retained'])}\n(자본금 {_eok(f['capital'])})",
         "잉여금 과다 누적 — 자기주식 취득·배당·승계 시 의제배당·부당행위·증여 쟁점",
         "환원 방식별 세부담 비교, 자기주식 취득 요건(재원·시가·균등) 점검 → 시나리오 1",
         "법인세법 제52조(부당행위계산의 부인)"),
        (f"당기순이익 {_eok(f['ni'])}\n(지배주주 임원)",
         "오너 임원 보수·상여·퇴직금 과다지급 시 손금불산입",
         "지급규정·주총 한도·동일직위 비교 검토 → 시나리오 2",
         "법인세법 시행령 제43조(상여금 등의 손금불산입)"),
        ("특수관계자 자금거래\n(가지급금 가정)",
         "업무무관 가지급금 — 인정이자 익금산입·지급이자 손금불산입·상여처분",
         "약정이자·차입금·회수계획 점검 → 시나리오 3",
         "법인세법 제28조(지급이자의 손금불산입)"),
        ("연구개발비\n(R&D 집약 제조)",
         "연구·인력개발비 세액공제 — 적격성·신성장 구분·방식 선택에 따라 공제액 변동",
         "활동 적격성·구분경리·당기분/증가분 비교 → 시나리오 4",
         "조세특례제한법 제10조(연구·인력개발비에 대한 세액공제)"),
        (f"매출액 {_eok(f['sales'])}\n(접대·광고선전)",
         "기업업무추진비(접대비) 한도초과 손금불산입·적격증빙 미수취 가산",
         "수입금액별 한도 계산·적격증빙·문화접대비 구분 점검",
         "법인세법 제25조(기업업무추진비의 손금불산입)"),
        ("유형자산·업무용 차량",
         "업무용 승용차 관련비용·감가상각 한도, 업무무관 부동산 보유 시 손금 제한",
         "운행기록부·업무사용비율·처분손익 점검",
         "법인세법 제27조의2(업무용승용차 관련비용의 손금불산입 특례)"),
    ]


def evidence_list() -> list[str]:
    """권고 경로 입증을 위한 가상 증빙 목록('증빙명|용도·보관')."""
    return [
        "주식 평가보고서(상증법 보충적 평가)|자기주식 시가 입증 — 부과제척기간 보관",
        "주주총회·이사회 의사록(자기주식 취득)|취득 목적·수량·가액·균등취득 결의 입증",
        "배당가능이익 산정내역서|상법 제341조 취득한도 입증",
        "의제배당 원천징수영수증·지급명세서|배당소득 과세 이행 증빙",
        "임원 보수·퇴직금 지급규정 및 위임 정관|보수·퇴직금 손금 근거",
        "동일직위 임원 보수 비교표|과다보수 시비 대비(정당사유)",
        "금전소비대차계약서(특수관계 대여)|약정이자·상환조건 입증",
        "인정이자 계산내역·미수이자 계상 증빙|익금산입·지급이자 부인 계산 근거",
        "가지급금 상환계획서·담보설정 서류|상여처분 회피 입증",
        "연구개발 활동 연구노트·과제계획서|R&D 적격성·세액공제 사후관리 증빙",
        "연구개발비 명세서·구분경리 내역|신성장·원천기술 구분 공제 입증",
        "최저한세·농어촌특별세 계산내역|세액공제 실익·이월공제 관리",
    ]


# --------------------------------------------------------------------------- #
# 회사 그라운딩 [사실관계](facts) — 합성. 분개 금액도 사실관계 맥락으로 스케일.
# --------------------------------------------------------------------------- #
def _company_scenarios(fin) -> list[Scenario]:
    f = _figs(fin)
    name = fin.corp_name
    ret = _eok(f["retained"]); cap = _eok(f["capital"]); ni = _eok(f["ni"])
    base = {s.key: s for s in demo_scenarios()}

    treasury = dataclasses.replace(
        base["TREASURY"],
        trigger=f"{name}의 잉여금 환원·최대주주 지분 정리를 위한 자기주식 취득 검토",
        facts=(
            f"{name}는 자본금 {cap} 대비 이익잉여금 {ret}으로 잉여금이 크게 누적되어 있다(DART 공시). "
            "최대주주 일가의 지분 정리·유동성 확보를 위해, 회사가 최대주주 보유주식 일부(가정: 보통주 "
            "30만주)를 1주당 가정 시가 8만원(합계 약 240억원)에 취득하여 소각하는 방안을 검토한다. "
            "배당가능이익은 충분한 것으로 가정한다. ※ 주식수·취득가는 추론용 가상 수치."),
        journal=JournalIllustration(
            title="자기주식 취득 회계처리(권고 경우 ① — 소각목적, 취득가 가정 240억)",
            note="자기주식은 자본의 차감항목(자본조정). 소각 시 액면 초과액은 감자차손·이익잉여금과 상계.",
            lines=(JournalLine("자기주식(자본조정)", 24_000_000_000, 0),
                   JournalLine("보통예금", 0, 24_000_000_000))),
    )
    execpay = dataclasses.replace(
        base["EXECPAY"],
        trigger=f"{name} 대표이사(지배주주) 보수 인상·성과상여·퇴직금 지급 검토",
        facts=(
            f"{name}의 {fin.year} 당기순이익은 {ni}이다(DART). 이를 배경으로 대표이사(지배주주)의 "
            "보수를 연 25억원→40억원으로 인상하고, 별도 성과상여 20억원 지급을 검토한다(가정). "
            "임원 보수·퇴직금 지급규정 존부, 주주총회 승인 한도, 동일 직위 비지배주주 임원 보수와의 "
            "비교가 손금 인정의 관건이다. ※ 보수·상여 금액은 추론용 가상 수치."),
        journal=JournalIllustration(
            title="임원 상여·보수 지급 회계처리(권고 경우 ① — 규정 내, 가정 월보수 3.3억)",
            note="규정·주총 한도 내 보수는 손금산입. 원천징수 예수금 분리.",
            lines=(JournalLine("급여(임원보수)", 330_000_000, 0),
                   JournalLine("보통예금", 0, 300_000_000),
                   JournalLine("예수금(소득세 등)", 0, 30_000_000))),
    )
    loan = dataclasses.replace(
        base["LOAN"],
        trigger=f"{name}의 특수관계자 대여금(업무무관 가지급금) 정리 검토",
        facts=(
            f"{name}가 특수관계자(가정: 최대주주가 지배하는 부동산임대법인)에 운영자금 50억원을 "
            "대여한 사실이 있다고 가정한다. 약정이자율(인정이자율)·회사 차입금 현황·회수계획에 따라 "
            "인정이자 익금산입·지급이자 손금불산입·상여처분 리스크가 갈린다. ※ 대여 사실·금액은 가상."),
        journal=JournalIllustration(
            title="가지급금 인정이자·상환 회계처리(권고 경우 ① — 잔액 가정 50억, 이자 2.3억)",
            note="인정이자는 미수수익으로 익금 계상, 상환 시 가지급금 감소.",
            lines=(JournalLine("미수수익(인정이자)", 230_000_000, 0),
                   JournalLine("이자수익", 0, 230_000_000),
                   JournalLine("보통예금(상환)", 5_000_000_000, 0),
                   JournalLine("가지급금", 0, 5_000_000_000))),
    )
    return [treasury, execpay, loan, _rnd_scenario(fin)]


def _rnd_scenario(fin) -> Scenario:
    name = fin.corp_name
    return Scenario(
        key="RND",
        title="연구·인력개발비 세액공제 적용",
        trigger=f"{name}의 연구개발비에 대한 세액공제 극대화·사후관리 검토",
        summary="‘활동 적격성 → 신성장·원천기술 구분경리 → 당기분/증가분 방식·최저한세’ 분기를 통과해야 공제를 부인당하지 않고 극대화한다.",
        facts=(
            f"{name}는 반도체 후공정 장비(본더 등) 개발에 매출 대비 상당액을 투입하는 R&D 집약 "
            "기업이다(가정: 당기 연구개발비 600억원). 어떤 비용이 세법상 ‘연구개발’에 해당하는지, "
            "신성장·원천기술 R&D를 구분경리했는지, 당기분·증가분 중 어느 방식이 유리한지에 따라 "
            "세액공제액과 사후 추징 위험이 크게 달라진다. ※ 연구개발비 금액은 추론용 가상 수치."),
        gates=(
            Gate("D1", "지출이 세법상 ‘연구개발’ 정의에 해당하고 연구노트·과제관리 증빙이 있는가?",
                 "예 · 적격", "아니오(단순 생산·품질)",
                 "공제 부인 + 가산세",
                 "단순 생산·품질관리·기존기술 사용은 공제 부인·추징. 연구노트·과제계획으로 적격성 입증."),
            Gate("D2", "신성장·원천기술 연구개발비를 별도 구분경리했는가?",
                 "예 · 구분", "아니오(미구분)",
                 "높은 공제율 적용 불가",
                 "미구분 시 신성장·원천기술 고율 공제 배제(일반 공제율만). 비목별 구분경리·명세서 구비."),
            Gate("D3", "당기분·증가분 방식을 비교하고 최저한세·농특세를 반영해 유리한 방식을 택했는가?",
                 "예 · 최적", "아니오(불리/한도초과)",
                 "공제 실익 축소",
                 "불리한 방식·최저한세 한도 초과로 실익 축소. 두 방식 비교·이월공제 활용."),
        ),
        safe_title="세액공제 적법·극대화",
        safe_detail="적격성·구분경리·방식 최적화를 충족하면 공제 부인 없이 절세효과 극대화.",
        leaves=(
            Leaf("경우 ①", "적격 · 신성장 구분 · 방식 최적", "안전",
                 "공제 부인 위험 없이 신성장·원천기술 고율 공제까지 적용.",
                 "연구노트·과제관리 + 비목별 구분경리 + 당기분/증가분 비교로 공제 극대화.",
                 ("조특법 제10조(연구·인력개발비 세액공제)", "조특법 별표7(신성장·원천기술)")),
            Leaf("경우 ②", "적격이나 신성장 미구분", "주의",
                 "일반 연구개발비 공제율만 적용(중견기업 공제율).",
                 "신성장·원천기술 해당분 사후 구분경리·경정청구 검토.",
                 ("조특법 시행령 제9조", "조특법 제10조")),
            Leaf("경우 ③", "R&D 정의 미충족·증빙 부재", "위험",
                 "연구개발비 자체 부인 + 과소신고 가산세.",
                 "연구노트·인건비 배분·과제 산출물로 적격성 사전 확보, 부적격분 자진 제외.",
                 ("조특법 제10조", "국세기본법 제47조의3(과소신고 가산세)")),
            Leaf("경우 ④", "최저한세 한도 초과", "주의",
                 "당기 공제 일부가 최저한세로 제한(실익 축소).",
                 "이월공제(기간 내) 활용, 당기분/증가분 방식 재선택으로 한도 관리.",
                 ("조특법 제132조(최저한세)", "조특법 제144조(세액공제액의 이월공제)")),
        ),
        citations=(
            "조세특례제한법 제10조(연구·인력개발비에 대한 세액공제)",
            "조세특례제한법 시행령 제9조(연구·인력개발비의 범위)",
            "조세특례제한법 제132조(최저한세)",
            "조세특례제한법 제144조(세액공제액의 이월공제)",
        ),
        recommended_case="경우 ①",
        aftercare=(
            "연구노트·과제 산출물·인건비 배분 근거를 공제 후 사후관리기간 동안 보관.",
            "신성장·원천기술 구분경리 내역과 명세서 정합성 정기 점검.",
            "이월공제 잔액·만료시점 추적, 최저한세 한도 변동 모니터링.",
        ),
        actions=(
            "당기 연구개발비를 비목별로 적격/부적격 구분.",
            "신성장·원천기술 해당 과제 식별·구분경리.",
            "당기분·증가분 방식 세액 비교 시뮬레이션.",
        ),
        plan=(
            PlanStep("결산 전", "연구개발비 적격성 검토·구분경리", "분기 D1·D2 통과"),
            PlanStep("신고 시", "당기분/증가분 비교·최저한세 반영", "분기 D3 통과(공제 극대화)"),
            PlanStep("신고 후", "연구노트·명세서 정합 보관", "사후 추징 예방"),
            PlanStep("차기", "이월공제·신성장 경정청구 검토", "공제 실익 회수"),
        ),
        rag_query="연구 인력개발비 세액공제 신성장 원천기술 조세특례제한법 중견기업",
        law_query="연구개발비 세액공제",
        alternatives=(
            PlanAlt("대안 A", "신성장·원천기술 구분 + 최적 방식",
                    "적격 R&D를 신성장·원천기술로 구분경리하고 당기분/증가분 중 유리한 방식 선택",
                    "최적 공제로 추가 부담 0(기준)", 0.0,
                    "고율 공제 극대화·부인 위험 최소", "구분경리·연구노트 등 증빙 필요", True),
            PlanAlt("대안 B", "일반 공제만(신성장 미구분)",
                    "신성장 구분 없이 일반 연구개발비 공제율만 적용",
                    "고율 공제 미적용분 약 8억 추가 부담(가정)", 8.0,
                    "절차 단순", "신성장 고율 공제 기회 상실"),
            PlanAlt("대안 C", "부적격 포함·증빙 부재",
                    "단순 생산·품질활동을 R&D로 포함하거나 연구노트 미비",
                    "공제 부인·가산세로 약 20억 추가 부담(가정)", 20.0,
                    "—", "세무조사 시 공제 부인·과소신고 가산세"),
        ),
        journal=JournalIllustration(
            title="연구개발비 인식·세액공제(권고 경우 ① — 가정 R&D 600억)",
            note="연구개발비는 비용 처리(자산화 요건 충족분 제외). 세액공제는 산출세액에서 차감(별도 세무조정).",
            lines=(JournalLine("경상연구개발비", 60_000_000_000, 0),
                   JournalLine("보통예금", 0, 60_000_000_000)),
        ),
    )


def build_dart_company_report(name_or_stock: str, year: int, out_path, *,
                              fs_div: str = "CFS", with_rag: bool = True,
                              with_charts: bool = True):
    """DART 회사 1곳 → 종합세무검토 + 경우의 수 의사결정 보고서 DOCX 생성."""
    from datetime import date

    import src.dart_fetch as dart
    from src.scenario_report import build_company_case_docx

    fin = dart.load_company(name_or_stock, year, fs_div=fs_div)
    if not fin.lines:
        raise RuntimeError(f"DART 재무 라인 0건: {name_or_stock} {year}")
    rows, note, src_note = company_overview(fin)
    scns = _company_scenarios(fin)
    out = build_company_case_docx(
        scns, out_path,
        company=f"{fin.corp_name}(주)" if not fin.corp_name.endswith(")") else fin.corp_name,
        as_of=date.today().strftime("%Y년 %m월 %d일"),
        overview_rows=rows, overview_note=note,
        tax_review_rows=comprehensive_review(fin),
        evidence=evidence_list(), data_source_note=src_note,
        with_rag=with_rag, with_charts=with_charts,
    )
    return out, fin, scns
