"""src/cpa_report.py — 회계사(KICPA) 친화 자연어 검토보고서 DOCX 렌더러.

기존 시스템 렌더러(``src.draft._render_package_docx``)는 내부 검토·디버깅용이라 영어 제목
(Executive Summary)·열거형 코드(FISCAL_YEAR·ANSWERED)·내부 식별자(client_id·H1~H5)·평문 URL을
그대로 노출한다. 이 모듈은 **최종 리뷰어가 회계사**라는 점에 맞춰 같은 ``DraftPackageData`` 를

  1. 영어·개발어 0 (모든 열거형/코드/식별자를 자연스러운 한국어로 치환·은닉),
  2. 근거를 **클릭 가능한 하이퍼링크**(국가법령정보센터)로,
  3. **Noto Sans KR(Google 폰트)** + 가독성 서식(제목 강조색·표 음영·줄간격)

으로 다시 렌더한다. 데이터/검증 불변식은 그대로 재사용한다(``validate_draft_package``).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from src.draft import (
    DraftPackageData,
    _law_permalink,
    validate_draft_package,
)

# Google 폰트(가독성) — 한글·라틴 모두 Noto Sans KR 로 통일.
_FONT = "Noto Sans KR"
_HEADING_RGB = (0x1A, 0x73, 0xE8)   # Google 블루(제목 강조)
_LINK_RGB = (0x15, 0x58, 0xD6)      # Google 링크 블루
_HEADER_FILL = "E8F0FE"             # 표 머리행 음영(연한 구글 블루)
_HYPERLINK_RELTYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
)

# --------------------------------------------------------------------------- #
# 자연어 매핑 — 열거형/코드 → 회계사가 읽는 한국어
# --------------------------------------------------------------------------- #
_BASIS_KO = {
    "TRANSACTION_DATE": "거래일 기준", "ACCRUAL_YEAR": "귀속연도 기준",
    "FISCAL_YEAR": "사업연도 기준", "FILING_DATE": "신고일 기준",
    "ASSESSMENT_DATE": "부과일 기준", "AMENDED_RETURN_DATE": "수정신고일 기준",
    "ADVISORY_DATE": "자문일 기준",
}
_STATUS_KO = {
    "ANSWERED": "답변 완료", "SILENT": "해당 자료 없음", "ERROR": "조회 오류",
    "BLOCKED": "접근 제한",
}
_STAGE_KO = {
    "INTAKE": "자료 수집", "ISSUE_SPOTTING": "쟁점 도출",
    "RESEARCH_CH1_LAW": "법령 조사", "RESEARCH_CH2_RAG": "내부 자료 검토",
    "RESEARCH_CH3_WEB": "공개자료 확인", "SYNTHESIS": "종합 판단",
    "STRATEGY": "처리 방향 도출", "DRAFT": "보고서 작성",
}
_SEVERITY_KO = {"HIGH": "높음", "MEDIUM": "중간", "LOW": "낮음"}
_CONF_KO = {"L1": "일반", "L2": "대외비", "L3": "기밀", "L3_CLIENT": "기밀"}
_CATEGORY_KO = {
    "UNCERTAIN": "불확실", "INTERPRETATION": "해석 필요",
    "UNRESOLVED_CONFLICT": "미해소 충돌", "HIGH_RISK_AGGRESSIVE": "고위험(적극처리)",
    "DATA_LIMIT": "자료 한계", "WEAK_BASIS": "근거 보강 필요",
    "TEMPORAL_ASSUMPTION": "적용시점 가정",
}
_GATE_KO = {
    "H1": "자료 확인", "H2": "계산 검산", "H3": "충돌 검토",
    "H4": "고위험 승인", "H5": "최종 승인",
}

# 자유 텍스트에 박힌 개발어/약어 — 회계사 가독성 위해 정화(영어 0 목표).
#
# 한글은 정규식에서 단어문자(\w)라, "CPA검토"·"H1승인"처럼 **한글에 결합된** 개발어는
# \b(단어경계)가 잡지 못한다(codex 적발). 따라서 구조적 개발어/식별자는 **경계 비의존**으로
# 치환한다. 순서 중요: 식별자·번호결합 코드 → 열거형 → 약어 → 게이트 순(긴 패턴 먼저).
_JARGON_SUBS: list[tuple[re.Pattern, str]] = [
    # 내부 식별자(snake_case: client_inc·matter_x·source_answer_id 등) 제거(한글 결합 무관)
    (re.compile(r"[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+"), ""),
    # 요건/게이트 번호결합 코드(OUT-003·HALU-008·WEB-011 …) 제거
    (re.compile(r"(OUT|HALU|INTK|EVAL|AGT|SEC|PROV|ORCH|WEB|RAG)-\d+"), ""),
    # 괄호로 감싼 약어
    (re.compile(r"\(\s*HITL\s*\)"), ""),
    (re.compile(r"\(\s*CPA\s*\)"), ""),
    # 적용시점 열거형
    (re.compile(r"FISCAL_YEAR"), "사업연도"),
    (re.compile(r"ACCRUAL_YEAR"), "귀속연도"),
    (re.compile(r"TRANSACTION_DATE"), "거래일"),
    (re.compile(r"FILING_DATE"), "신고일"),
    # 채널 응답 상태 열거형(한글 결합 포함 — 경계 비의존)
    (re.compile(r"ANSWERED"), "답변 완료"),
    (re.compile(r"SILENT"), "해당 자료 없음"),
    (re.compile(r"BLOCKED"), "접근 제한"),
    (re.compile(r"ERROR"), "오류"),
    (re.compile(r"AGREE"), "합의"),
    # 출처/도구 약어
    (re.compile(r"korean-law-mcp", re.IGNORECASE), "국가법령정보"),
    (re.compile(r"법령\s*MCP"), "법령"),
    (re.compile(r"MCP"), ""),
    (re.compile(r"내부\s*RAG"), "내부 자료"),
    (re.compile(r"RAG"), "내부 자료"),
    (re.compile(r"DRF"), ""),
    (re.compile(r"DOCX"), "보고서"),
    (re.compile(r"HITL"), "회계사 검토"),
    (re.compile(r"Reviewer"), "검토 회계사"),
    (re.compile(r"KICPA"), "한국공인회계사"),   # 'CPA' 부분치환 전에(→'KI회계사' 방지)
    (re.compile(r"CPA"), "회계사"),
    (re.compile(r"계산엔진/생성기"), "자동화 도구"),
    # 회계사 검토 게이트 코드 H1~H5(한글 결합 "H1승인" 포함; CH1 등 라틴결합은 제외)
    (re.compile(r"(?<![A-Za-z0-9])H[1-5](?![0-9])"), ""),
    # 기밀등급 라벨
    (re.compile(r"L3_CLIENT"), "기밀"),
    (re.compile(r"(?<![A-Za-z0-9])L[123](?![0-9])"), ""),
    # 비교 표기
    (re.compile(r"vs\.?", re.IGNORECASE), "대"),
    # 빈 괄호/중복 공백 정리
    (re.compile(r"\(\s*[·,;\s]*\)"), ""),
    (re.compile(r"\s{2,}"), " "),
]


def _ko(text: str) -> str:
    """자유 텍스트의 잔여 개발어·약어를 자연어로 정화(영어 토큰 제거)."""
    if not text:
        return text
    out = text
    for pat, repl in _JARGON_SUBS:
        out = pat.sub(repl, out)
    # 괄호 안이 비어버린 경우 정리: "(  )" / "( )" → 제거
    out = re.sub(r"\(\s*[·,;\s]*\)", "", out)
    return out.strip()


def _basis_ko(value: str) -> str:
    return _BASIS_KO.get(value, value if value not in _BASIS_KO else value)


# --------------------------------------------------------------------------- #
# DOCX 저수준 헬퍼 (하이퍼링크 · 폰트 · 표 음영)
# --------------------------------------------------------------------------- #
def _qn(tag: str):
    from docx.oxml.ns import qn
    return qn(tag)


def _set_run_font(run, *, size: Optional[float] = None, bold: bool = False,
                  rgb: Optional[tuple] = None) -> None:
    from docx.shared import Pt, RGBColor
    run.font.name = _FONT
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(_qn(attr), _FONT)
    if size is not None:
        run.font.size = Pt(size)
    run.bold = bold
    if rgb is not None:
        run.font.color.rgb = RGBColor(*rgb)


def _add_hyperlink(paragraph, url: str, text: str, *, size: float = 10.0) -> None:
    """문단에 **클릭 가능한** 하이퍼링크 run 을 추가(밑줄·링크색·Noto Sans KR)."""
    from docx.oxml import OxmlElement

    part = paragraph.part
    r_id = part.relate_to(url, _HYPERLINK_RELTYPE, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(_qn("r:id"), r_id)

    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    rfonts = OxmlElement("w:rFonts")
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(_qn(attr), _FONT)
    rpr.append(rfonts)
    color = OxmlElement("w:color")
    color.set(_qn("w:val"), "%02X%02X%02X" % _LINK_RGB)
    rpr.append(color)
    u = OxmlElement("w:u")
    u.set(_qn("w:val"), "single")
    rpr.append(u)
    sz = OxmlElement("w:sz")
    sz.set(_qn("w:val"), str(int(size * 2)))  # half-points
    rpr.append(sz)
    run.append(rpr)
    t = OxmlElement("w:t")
    t.set(_qn("xml:space"), "preserve")
    t.text = text
    run.append(t)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def _shade(cell, fill: str = _HEADER_FILL) -> None:
    from docx.oxml import OxmlElement
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(_qn("w:val"), "clear")
    shd.set(_qn("w:fill"), fill)
    tc_pr.append(shd)


def _cell(cell, text: str, *, bold: bool = False, size: float = 9.5,
          header: bool = False) -> None:
    """표 셀에 Noto Sans KR 텍스트 기입(머리행은 음영+굵게)."""
    cell.text = ""
    p = cell.paragraphs[0]
    run = p.add_run(text)
    _set_run_font(run, size=size, bold=bold or header,
                  rgb=_HEADING_RGB if header else None)
    if header:
        _shade(cell)


def _cell_link(cell, url: str, text: str, *, size: float = 9.0) -> None:
    """표 셀에 하이퍼링크(근거 바로가기)."""
    cell.text = ""
    _add_hyperlink(cell.paragraphs[0], url, text, size=size)


def _apply_document_style(doc) -> None:
    """문서 전체 Noto Sans KR + 가독성 서식(제목 강조색·줄간격)."""
    from docx.shared import Pt, RGBColor

    base = {
        "Normal": (10.5, False, None),
        "List Bullet": (10.5, False, None),
        "List Number": (10.5, False, None),
        "Title": (22, True, _HEADING_RGB),
        "Heading 1": (14, True, _HEADING_RGB),
        "Heading 2": (11.5, True, (0x20, 0x20, 0x20)),
    }
    for sname, (size, bold, rgb) in base.items():
        try:
            st = doc.styles[sname]
        except KeyError:
            continue
        st.font.name = _FONT
        st.font.size = Pt(size)
        st.font.bold = bold
        if rgb is not None:
            st.font.color.rgb = RGBColor(*rgb)
        rpr = st.element.get_or_add_rPr()
        rfonts = rpr.get_or_add_rFonts()
        for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
            rfonts.set(_qn(attr), _FONT)
    normal = doc.styles["Normal"]
    normal.paragraph_format.line_spacing = 1.3
    normal.paragraph_format.space_after = Pt(4)


# --------------------------------------------------------------------------- #
# 보고서 13개 장(章) — 자연어 제목
# --------------------------------------------------------------------------- #
_SECTIONS_KO = [
    "1. 핵심 요약",
    "2. 회사 개요 및 검토 범위",
    "3. 검토 대상 자료",
    "4. 주요 세무 리스크",
    "5. 절세 기회",
    "6. 처리 방향별 비교 (보수·중립·적극)",
    "7. 쟁점별 검토 의견",
    "8. 근거 출처별 검토 결과",
    "9. 관련 법령 및 근거 (클릭하면 원문으로 이동)",
    "10. 검토 과정 및 법령 추적",
    "11. 추가 요청 자료",
    "12. 회계사 검토 필요사항",
    "13. 결론 및 권고 검토 순서",
]


def build_cpa_review_docx(
    data: DraftPackageData,
    out_path: str | Path,
    *,
    titles: Optional[dict[str, str]] = None,
    articles: Optional[dict[str, str]] = None,
) -> Path:
    """회계사 친화 자연어 검토보고서 DOCX 생성(하이퍼링크·Noto Sans KR·영어 0).

    데이터 불변식은 시스템 검증기로 그대로 강제(무인용 단정·필수섹션·날조 인용 차단)."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    validate_draft_package(data)
    cviews = {cv.citation_id: cv for cv in data.citation_views(titles, articles)}

    def label_of(cid: str) -> str:
        cv = cviews.get(cid)
        return cv.label if cv else ""

    def href_of(cid: str) -> str:
        cv = cviews.get(cid)
        return cv.href if cv else _law_permalink("법령", "")

    doc = Document()
    from datetime import datetime
    doc.core_properties.created = datetime(2024, 1, 1)
    doc.core_properties.modified = datetime(2024, 1, 1)
    _apply_document_style(doc)

    # 표지
    title = doc.add_heading(f"{data.company_name} {data.fiscal_year} 세무 검토 보고서", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    srun = sub.add_run(
        f"검토기준일 {data.as_of_date:%Y년 %m월 %d일}　·　내부 검토용　·　"
        f"{'고위험 안건' if data.high_risk else '표준 안건'}"
    )
    _set_run_font(srun, size=10, rgb=(0x5F, 0x63, 0x68))
    note = doc.add_paragraph()
    nrun = note.add_run(
        "본 보고서의 모든 법적 판단에는 근거 법령이 함께 표기되며, 파란색 밑줄 글씨를 "
        "누르면 국가법령정보센터 원문으로 바로 이동합니다. 최종 판단·서명은 담당 회계사가 합니다."
    )
    _set_run_font(nrun, size=9.5, rgb=(0x5F, 0x63, 0x68))
    if data.data_limits:
        lim = doc.add_paragraph()
        lr = lim.add_run("자료 한계: " + " / ".join(_ko(x) for x in data.data_limits))
        _set_run_font(lr, size=9, rgb=(0xB0, 0x60, 0x00))

    def heading(idx: int) -> None:
        doc.add_heading(_SECTIONS_KO[idx], level=1)

    def body(text: str, *, size: float = 10.5) -> None:
        p = doc.add_paragraph()
        _set_run_font(p.add_run(_ko(text)), size=size)

    def bullet_with_basis(prefix: str, text: str, cids: list[str]) -> None:
        """리스크/절세기회 한 줄 + 근거 하이퍼링크(여러 건 가능)."""
        p = doc.add_paragraph(style="List Bullet")
        _set_run_font(p.add_run(_ko(prefix + text)), size=10.5)
        labels = [(label_of(c), href_of(c)) for c in cids if c in cviews]
        if labels:
            _set_run_font(p.add_run("　(근거: "), size=9.5, rgb=(0x5F, 0x63, 0x68))
            for i, (lab, href) in enumerate(labels):
                if i:
                    _set_run_font(p.add_run(", "), size=9.5)
                _add_hyperlink(p, href, lab, size=9.5)
            _set_run_font(p.add_run(")"), size=9.5, rgb=(0x5F, 0x63, 0x68))

    # 1. 핵심 요약
    heading(0)
    body(data.executive_summary)

    # 2. 회사 개요 및 검토 범위 (내부 식별자 비노출)
    heading(1)
    body(f"회사: {data.company_name}")
    body(f"대상 사업연도: {data.fiscal_year}")
    body(f"검토 범위: {_ko(data.review_scope)}")

    # 3. 검토 대상 자료
    heading(2)
    t3 = doc.add_table(rows=1, cols=3)
    t3.style = "Table Grid"
    for i, h in enumerate(["자료", "상태", "기밀 등급"]):
        _cell(t3.rows[0].cells[i], h, header=True)
    for m in data.input_materials:
        r = t3.add_row().cells
        _cell(r[0], _ko(m.name)); _cell(r[1], m.status)
        _cell(r[2], _CONF_KO.get(m.confidentiality, "일반"))

    # 4. 주요 세무 리스크
    heading(3)
    for risk in data.risks:
        sev = _SEVERITY_KO.get(risk.severity, "중간")
        bullet_with_basis(f"[위험도 {sev}] {risk.title} — ", risk.description, risk.citation_ids)

    # 5. 절세 기회
    heading(4)
    for op in data.opportunities:
        bullet_with_basis(f"{op.title} — ", op.description, op.citation_ids)

    # 6. 처리 방향별 비교 (보수·중립·적극)
    heading(5)
    t6 = doc.add_table(rows=1, cols=7)
    t6.style = "Table Grid"
    for i, h in enumerate(
        ["처리 방향", "예상 세부담", "세무 리스크(과세 측 논리)", "방어 가능성(납세자 논리)",
         "필요 증빙", "회계사 확인 포인트", "근거"]
    ):
        _cell(t6.rows[0].cells[i], h, header=True)
    order = {"보수": 0, "중립": 1, "적극": 2}
    for o in sorted(data.strategy_options, key=lambda x: order.get(x.option_key, 9)):
        c = t6.add_row().cells
        _cell(c[0], _ko(o.label)); _cell(c[1], _ko(o.expected_tax_burden))
        _cell(c[2], _ko(o.tax_risk)); _cell(c[3], _ko(o.defensibility))
        _cell(c[4], _ko(o.required_evidence)); _cell(c[5], _ko(o.cpa_review_point))
        cid = next((x for x in o.citation_ids if x in cviews), None)
        if cid:
            _cell_link(c[6], href_of(cid), label_of(cid))
        else:
            _cell(c[6], "—")

    # 7. 쟁점별 검토 의견
    heading(6)
    for memo in data.issue_memos:
        doc.add_heading(_ko(memo.topic), level=2)
        p = doc.add_paragraph()
        _set_run_font(p.add_run(_ko(memo.analysis)), size=10.5)
        labels = [(label_of(c), href_of(c)) for c in memo.citation_ids if c in cviews]
        if labels:
            _set_run_font(p.add_run("　(근거: "), size=9.5, rgb=(0x5F, 0x63, 0x68))
            for i, (lab, href) in enumerate(labels):
                if i:
                    _set_run_font(p.add_run(", "), size=9.5)
                _add_hyperlink(p, href, lab, size=9.5)
            _set_run_font(p.add_run(")"), size=9.5, rgb=(0x5F, 0x63, 0x68))
        if memo.escalation:
            note = _ko(memo.escalation)
            if note:
                ep = doc.add_paragraph()
                _set_run_font(ep.add_run("검토 포인트: " + note), size=9.5,
                              rgb=(0x5F, 0x63, 0x68))

    # 8. 근거 출처별 검토 결과
    heading(7)
    body("각 근거 출처가 종합 판단 전에 독립적으로 낸 결과입니다. 확인하지 못한 출처는 "
         "‘해당 자료 없음’으로 솔직히 표기합니다.", size=9.5)
    t8 = doc.add_table(rows=1, cols=4)
    t8.style = "Table Grid"
    for i, h in enumerate(["출처", "검토 상태", "요지", "관련 조문"]):
        _cell(t8.rows[0].cells[i], h, header=True)
    for cr in data.channel_results:
        r = t8.add_row().cells
        _cell(r[0], _ko(cr.source_label))
        _cell(r[1], _STATUS_KO.get(cr.status, "확인") if cr.answered
              else f"{_STATUS_KO.get(cr.status, '해당 자료 없음')}")
        _cell(r[2], _ko(cr.answer_excerpt) or ("—" if cr.answered else "(근거 없음)"))
        if cr.citation_locators:
            # 첫 조문을 대표 링크로(법령명/조문에서 permalink 합성)
            loc = cr.citation_locators[0]
            toks = loc.split()
            url = _law_permalink(" ".join(toks[:-1]) if len(toks) >= 2 else loc,
                                 toks[-1] if len(toks) >= 2 else "")
            _cell_link(r[3], url, "；".join(cr.citation_locators))
        else:
            _cell(r[3], "—")

    # 9. 관련 법령 및 근거 (클릭 → 원문)
    heading(8)
    for cv in cviews.values():
        p = doc.add_paragraph(style="List Bullet")
        _add_hyperlink(p, cv.href, cv.label, size=10.5)
        meta = f"　— 적용시점 {cv.as_of}({_basis_ko(cv.basis_kind)})"
        _set_run_font(p.add_run(meta), size=9.5, rgb=(0x5F, 0x63, 0x68))
        if cv.quote:
            qp = doc.add_paragraph()
            qr = qp.add_run("　“" + cv.quote[:160].strip() + "”")
            _set_run_font(qr, size=9, rgb=(0x40, 0x40, 0x40))

    # 10. 검토 과정 및 법령 추적
    heading(9)
    rt = data.reasoning_trace
    doc.add_heading("10-1. 검토 과정(단계별)", level=2)
    if rt and rt.steps:
        flow = " → ".join(_STAGE_KO.get(s.stage, s.stage) for s in rt.steps)
        fp = doc.add_paragraph()
        _set_run_font(fp.add_run(flow), size=10, bold=True, rgb=_HEADING_RGB)
        t10 = doc.add_table(rows=1, cols=3)
        t10.style = "Table Grid"
        for i, h in enumerate(["순서", "단계", "판단 내용"]):
            _cell(t10.rows[0].cells[i], h, header=True)
        for s in rt.steps:
            r = t10.add_row().cells
            _cell(r[0], str(s.seq)); _cell(r[1], _STAGE_KO.get(s.stage, s.stage))
            _cell(r[2], _ko(s.decision))
    doc.add_heading("10-2. 법령 추적 (쟁점이 어떤 조문을 따라갔는지)", level=2)
    t10b = doc.add_table(rows=1, cols=4)
    t10b.style = "Table Grid"
    for i, h in enumerate(["쟁점", "관련 법령·조문", "적용시점", "근거 발췌"]):
        _cell(t10b.rows[0].cells[i], h, header=True)
    for e in (rt.law_trace if rt else []):
        r = t10b.add_row().cells
        _cell(r[0], _ko(e.issue))
        url = _law_permalink(e.law_name, e.article)
        _cell_link(r[1], url, f"{e.law_name} {e.article}")
        _cell(r[2], f"{e.as_of}({_basis_ko(e.basis_kind)})" if e.as_of else _basis_ko(e.basis_kind))
        _cell(r[3], _ko(e.quote_excerpt))

    # 11. 추가 요청 자료
    heading(10)
    for req in data.additional_requests:
        p = doc.add_paragraph(style="List Bullet")
        _set_run_font(p.add_run(_ko(req)), size=10.5)

    # 12. 회계사 검토 필요사항
    heading(11)
    for it in data.review_items:
        cat = _CATEGORY_KO.get(it.category.value, "검토")
        gate = _GATE_KO.get(it.gate or "", "")
        sev = _SEVERITY_KO.get(it.severity, "중간")
        mark = "　[필독]" if it.requires_warning else ""
        head = f"[{cat}·위험도 {sev}{('·' + gate) if gate else ''}]{mark} "
        p = doc.add_paragraph(style="List Bullet")
        _set_run_font(p.add_run(head + _ko(it.description)), size=10.5,
                      bold=bool(it.requires_warning))

    # 13. 결론 및 권고 검토 순서
    heading(12)
    body(data.conclusion)
    cp = doc.add_paragraph()
    _set_run_font(cp.add_run("권고 검토 순서"), size=10.5, bold=True)
    for i, step in enumerate(data.recommended_order, start=1):
        p = doc.add_paragraph(style="List Number")
        _set_run_font(p.add_run(_ko(step)), size=10.5)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    return out_path
