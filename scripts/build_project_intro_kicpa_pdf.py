#!/usr/bin/env python3
"""scripts/build_project_intro_kicpa_pdf.py — Big4 tax KICPA용 '프로젝트 소개' PDF 생성.

세무사·회계사(특히 Big4 Business Tax) 검토자가 본 프로젝트를 **5분 안에** 이해하도록,
현재 산출물(경우의 수 의사결정 보고서·DART 실재무 그라운딩·내부 RAG·환각방지)을 도식·표
중심으로 정리한다. 실제 생성된 산출물 차트(``산출물/_charts_case``)를 그대로 임베드한다.

원칙: 코드/개발 용어를 회계사 언어로 번역, 과장 없이 '무엇을·어떻게·왜 신뢰 가능한가'를 제시.
출력:  레포 루트에서  PYTHONUTF8=1 python scripts/build_project_intro_kicpa_pdf.py
"""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT_PDF = Path(os.environ.get("KICPA_PDF_OUT") or (ROOT / "세무AI_프로젝트소개_KICPA용.pdf"))
ASSET_DIR = ROOT / "project_intro_assets"
CHARTS = ROOT / "산출물" / "_charts_case"

def _find_font(env_key: str, *candidates: str) -> str:
    """폰트 경로 — 환경변수 우선, 없으면 후보(Windows 기본) 중 존재하는 첫 경로. 모두 없으면 명확히 실패."""
    paths = [os.environ.get(env_key)] + list(candidates)
    for p in paths:
        if p and Path(p).exists():
            return p
    raise FileNotFoundError(
        f"한글 폰트를 찾지 못했습니다({env_key}). 환경변수 {env_key}로 .ttf 경로를 지정하세요. 후보: {candidates}")


FONT_REG = _find_font("KICPA_FONT_REG", "C:/Windows/Fonts/malgun.ttf",
                      "/usr/share/fonts/truetype/nanum/NanumGothic.ttf")
FONT_BOLD = _find_font("KICPA_FONT_BOLD", "C:/Windows/Fonts/malgunbd.ttf",
                       "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", FONT_REG)

PAGE_W, PAGE_H = fitz.paper_size("a4")
M = 42
# 한글은 전각(글자폭 ≈ font_size). ASCII·공백 혼합을 감안해 보수적으로 0.92*size 로 줄당 폭 추정.
# (과소추정하면 insert_textbox 가 텍스트를 잘라 무음 누락 — codex MEDIUM 적발 케이스.)
CHAR_W = 0.92

COLORS = {
    "navy": "17324D", "blue": "2E74B5", "teal": "0B6B5E", "green": "2F6B4F",
    "gold": "7A5A00", "red": "9B1C1C", "gray": "667085",
    "light_blue": "E8F1FA", "light_teal": "EAF5F3", "light_green": "EAF5EF",
    "light_gold": "FFF6DB", "light_red": "FDEDED", "light_gray": "F3F5F7",
    "border": "D9E0E7", "black": "111827", "white": "FFFFFF",
}


def rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def add_page(doc):
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    p.insert_font(fontname="kr", fontfile=FONT_REG)
    p.insert_font(fontname="krb", fontfile=FONT_BOLD)
    return p


def tb(page, rect, text, size=9.8, color="111827", bold=False,
       align=fitz.TEXT_ALIGN_LEFT, lineheight=1.22):
    rem = page.insert_textbox(
        fitz.Rect(rect), text, fontsize=size,
        fontname="krb" if bold else "kr", color=rgb(color),
        align=align, lineheight=lineheight,
    )
    # 음수 = 박스에 다 못 담김(overflow). 빌드를 막진 않되 잘림을 stderr로 고지(codex MEDIUM).
    if rem is not None and rem < 0:
        import sys
        print(f"  ⚠ 텍스트 오버플로우(잘림 가능): {str(text)[:60]!r}", file=sys.stderr)
    return rem


def heading(page, y, text, level=1):
    size = 16.5 if level == 1 else 12.5
    color = COLORS["blue"] if level == 1 else COLORS["teal"]
    tb(page, (M, y, PAGE_W - M, y + 30), text, size=size, bold=True, color=color)
    # underline for level 1
    if level == 1:
        page.draw_line(fitz.Point(M, y + 25), fitz.Point(PAGE_W - M, y + 25),
                       color=rgb(COLORS["border"]), width=1.0)
    return y + (38 if level == 1 else 26)


def para(page, y, text, size=9.6, color="222B36", width=None, lineheight=1.3):
    width = width or PAGE_W - 2 * M
    chars_per_line = max(20, int(width / (size * CHAR_W)))
    lines = 0
    for seg in text.split("\n"):
        lines += max(1, -(-len(seg) // chars_per_line))
    h = lines * size * lineheight + 6
    tb(page, (M, y, M + width, y + h), text, size=size, color=color, lineheight=lineheight)
    return y + h + 4


def callout(page, y, title, body, fill, border, height=82, icon="●"):
    # 본문 길이로 필요한 최소 높이를 계산해 height 를 하한으로만 사용(고정 height 부족 시 자동 확장).
    body_w = PAGE_W - 2 * M - 26
    cpl = max(20, int(body_w / (9.1 * CHAR_W)))
    blines = sum(max(1, -(-len(seg) // cpl)) for seg in body.split("\n"))
    needed = 30 + blines * 9.1 * 1.26 + 12
    height = max(height, needed)
    rect = fitz.Rect(M, y, PAGE_W - M, y + height)
    page.draw_rect(rect, color=rgb(border), fill=rgb(fill), width=1.1, radius=0.02)
    tb(page, (M + 13, y + 9, PAGE_W - M - 12, y + 28),
       f"{icon} {title}", size=10.2, bold=True, color=border)
    tb(page, (M + 13, y + 30, PAGE_W - M - 13, y + height - 8),
       body, size=9.1, lineheight=1.26)
    return y + height + 11


# malgun 미지원 글리프(✓ 등) 회피: 안전한 기하 아이콘만 사용


def table(page, y, headers, rows, widths, row_h=30, font_size=8.4,
          header_fill="teal", first_bold=True, zebra=True):
    x = M
    for j, h in enumerate(headers):
        rect = fitz.Rect(x, y, x + widths[j], y + row_h)
        page.draw_rect(rect, color=rgb(COLORS["border"]), fill=rgb(COLORS[header_fill]), width=0.8)
        tb(page, (x + 6, y + (row_h - font_size) / 2 - 1, x + widths[j] - 5, y + row_h - 2),
           h, size=font_size, bold=True, color=COLORS["white"])
        x += widths[j]
    y += row_h
    for ri, row in enumerate(rows):
        cpl = [max(8, int(widths[j] / (font_size * CHAR_W))) for j in range(len(row))]
        max_lines = max(max(1, -(-len(str(c)) // cpl[j])) for j, c in enumerate(row))
        h = max(row_h, font_size * 1.32 * max_lines + 12)
        x = M
        for j, c in enumerate(row):
            base = COLORS["light_gray"] if (zebra and ri % 2) else "FFFFFF"
            fill = COLORS["light_blue"] if j == 0 and first_bold else base
            rect = fitz.Rect(x, y, x + widths[j], y + h)
            page.draw_rect(rect, color=rgb(COLORS["border"]), fill=rgb(fill), width=0.55)
            tb(page, (x + 6, y + 6, x + widths[j] - 5, y + h - 4), str(c),
               size=font_size, bold=(j == 0 and first_bold), lineheight=1.24)
            x += widths[j]
        y += h
    return y + 12


def bullets(page, y, items, size=9.4, gap=3):
    for it in items:
        text = "•  " + it
        cpl = max(20, int((PAGE_W - 2 * M - 8) / (size * CHAR_W)))
        lines = max(1, -(-len(text) // cpl))
        h = lines * size * 1.3 + 4
        tb(page, (M + 6, y, PAGE_W - M, y + h), text, size=size, lineheight=1.3)
        y += h + gap
    return y + 6


def footer(page, n, total):
    page.draw_line(fitz.Point(M, PAGE_H - 30), fitz.Point(PAGE_W - M, PAGE_H - 30),
                   color=rgb(COLORS["border"]), width=0.7)
    tb(page, (M, PAGE_H - 26, PAGE_W - M, PAGE_H - 12),
       "AI 세무자문 의사결정 보고서 생성 시스템  ·  프로젝트 소개(KICPA용)",
       size=7.6, color=COLORS["gray"])
    tb(page, (M, PAGE_H - 26, PAGE_W - M, PAGE_H - 12),
       f"{n} / {total}", size=7.6, color=COLORS["gray"], align=fitz.TEXT_ALIGN_RIGHT)


def _fit_image(path, target_w_pt, dpi=200):
    """표시 폭(pt)에 맞춰 임베드용으로 다운샘플(과대 해상도→PDF 비대 방지). 캐시 경로 반환."""
    ASSET_DIR.mkdir(exist_ok=True)
    with Image.open(path) as src:
        im = src.convert("RGB")
    target_px = int(target_w_pt / 72 * dpi)
    if im.width > target_px:
        im = im.resize((target_px, round(im.height * target_px / im.width)), Image.LANCZOS)
    out = ASSET_DIR / f"emb_{Path(path).stem}_{target_px}.png"
    im.save(out, optimize=True)
    return out, im.width, im.height


def insert_image(page, y, path, width=None, center=True, max_h=None):
    width = width or PAGE_W - 2 * M
    emb, pw, ph = _fit_image(path, width)
    h = width * ph / pw
    if max_h and h > max_h:
        width = max_h * pw / ph
        h = max_h
    x0 = (PAGE_W - width) / 2 if center else M
    page.insert_image(fitz.Rect(x0, y, x0 + width, y + h), filename=str(emb))
    return y + h + 10


def caption(page, y, text):
    tb(page, (M, y, PAGE_W - M, y + 16), text, size=8.0, color=COLORS["gray"],
       align=fitz.TEXT_ALIGN_CENTER, lineheight=1.2)
    return y + 16


# --------------------------------------------------------------------------- #
# PIL 도식 2종(3소스 교차검증 · 파이프라인)
# --------------------------------------------------------------------------- #
def _round_box(d, xy, text, fill, outline, font, tcolor="#111827", wrap=14, width=3):
    d.rounded_rectangle(xy, radius=20, fill=fill, outline=outline, width=width)
    lines = []
    for ln in text.split("\n"):
        lines += textwrap.wrap(ln, width=wrap) or [""]
    th = len(lines) * 38
    yy = xy[1] + ((xy[3] - xy[1]) - th) / 2
    for ln in lines:
        bb = d.textbbox((0, 0), ln, font=font)
        xx = xy[0] + ((xy[2] - xy[0]) - (bb[2] - bb[0])) / 2
        d.text((xx, yy), ln, font=font, fill=tcolor)
        yy += 40


def _arrow(d, s, e, color="#5A6B7B", width=6):
    d.line([s, e], fill=color, width=width)
    sx, sy = s
    ex, ey = e
    if abs(ex - sx) >= abs(ey - sy):  # horizontal-ish
        sign = 1 if ex >= sx else -1
        d.polygon([(ex, ey), (ex - sign * 20, ey - 11), (ex - sign * 20, ey + 11)], fill=color)
    else:
        sign = 1 if ey >= sy else -1
        d.polygon([(ex, ey), (ex - 11, ey - sign * 20), (ex + 11, ey - sign * 20)], fill=color)


def make_diagrams():
    ASSET_DIR.mkdir(exist_ok=True)
    f_title = ImageFont.truetype(FONT_BOLD, 46)
    f_box = ImageFont.truetype(FONT_BOLD, 30)
    f_sm = ImageFont.truetype(FONT_REG, 26)

    # 1) 파이프라인: 거래/사건 → 분기 게이트 → 경우의 수 → 권고·실행계획 → 근거 3중검증
    img = Image.new("RGB", (1640, 760), "white")
    d = ImageDraw.Draw(img)
    d.text((50, 34), "한 거래를 '경우의 수'로 분해해 결론·근거까지 자동 작성", font=f_title, fill="#17324D")
    d.line([(50, 102), (1590, 102)], fill="#D9E0E7", width=3)
    steps = [
        ("① 거래·사건", "자기주식·임원보수\n가지급금·R&D 등", "#E8F1FA", "#2E74B5"),
        ("② 판단 게이트", "재원·시가·균등 등\n순차 분기 추론", "#FFF6DB", "#7A5A00"),
        ("③ 경우의 수", "안전 / 주의 / 위험\n경우별 세무리스크", "#FDEDED", "#9B1C1C"),
        ("④ 권고·실행계획", "권고 경로·시점\n분개·증빙 예시", "#EAF5EF", "#2F6B4F"),
        ("⑤ 근거 3중검증", "법령·내부자료·판례\n인용 강제(날조 0)", "#EAF5F3", "#0B6B5E"),
    ]
    bw, gap = 280, 35
    x0 = 50
    for i, (t, b, fill, oc) in enumerate(steps):
        x = x0 + i * (bw + gap)
        d.text((x + 6, 168), t, font=f_box, fill="#17324D")
        _round_box(d, (x, 215, x + bw, 430), b, fill, oc, f_sm, wrap=13)
        if i < len(steps) - 1:
            _arrow(d, (x + bw + 2, 322), (x + bw + gap - 2, 322))
    _round_box(
        d, (270, 560, 1370, 700),
        "결과: '안전/위험' 단답이 아니라, 조건을 어떻게 충족하느냐에 따라 갈리는 경우의 수를 회계사 검토용 보고서로 산출",
        "#FFFFFF", "#0B6B5E", f_sm, wrap=46, width=3)
    p1 = ASSET_DIR / "pipeline.png"
    img.save(p1, quality=95)

    # 2) 근거 3중 교차검증
    img = Image.new("RGB", (1640, 760), "white")
    d = ImageDraw.Draw(img)
    d.text((50, 34), "근거의 3중 교차검증 — '검색'이 아니라 '대조·종합'", font=f_title, fill="#17324D")
    d.line([(50, 102), (1590, 102)], fill="#D9E0E7", width=3)
    srcs = [
        ("① 법령", "국가법령정보\n조문 하이퍼링크", "#E8F1FA", "#2E74B5"),
        ("② 내부자료(RAG)", "실무 PDF 31종·1만+\n청크 의미검색(OCR)", "#FFF6DB", "#7A5A00"),
        ("③ 판례·해석례", "법제처 실시간 조회\n(예규·판례)", "#EAF5F3", "#0B6B5E"),
    ]
    for i, (t, b, fill, oc) in enumerate(srcs):
        x = 80 + i * 510
        d.text((x + 10, 168), t, font=f_box, fill="#17324D")
        _round_box(d, (x, 215, x + 440, 410), b, fill, oc, f_sm, wrap=15)
        _arrow(d, (x + 220, 412), (x + 220 if i == 1 else 820, 505),
               color="#5A6B7B", width=5) if False else None
    # converge arrows
    for i in range(3):
        x = 80 + i * 510 + 220
        _arrow(d, (x, 415), (820, 505))
    _round_box(d, (470, 510, 1170, 645),
               "교차검증 + 종합의견\n(서로 충돌·공백을 표시)", "#EAF5EF", "#2F6B4F", f_box, wrap=24, width=4)
    _round_box(d, (470, 668, 1170, 740),
               "근거 없는 단정 차단 · 회계사 최종검토(HITL)", "#FFFFFF", "#9B1C1C", f_sm, wrap=44, width=2)
    p2 = ASSET_DIR / "tri_source.png"
    img.save(p2, quality=95)
    return {"pipeline": p1, "tri": p2}


# --------------------------------------------------------------------------- #
def build_pdf():
    dg = make_diagrams()
    doc = fitz.open()
    TOTAL = 10
    n = 0

    def newp():
        nonlocal n
        n += 1
        return add_page(doc)

    # ---- p1 Cover --------------------------------------------------------- #
    page = newp()
    page.draw_rect(fitz.Rect(0, 0, PAGE_W, 150), fill=rgb(COLORS["navy"]))
    tb(page, (M, 44, PAGE_W - M, 96),
       "AI 세무자문 의사결정 보고서 생성 시스템", size=23, bold=True, color="FFFFFF")
    tb(page, (M, 104, PAGE_W - M, 138),
       "법인세를 넘어 전(全) 세목 — 회계사 검토용 '경우의 수' 의사결정 보고서 자동 생성",
       size=11.5, color="DCE6F2")
    y = 182
    y = callout(
        page, y, "한 문장 요약",
        "이 시스템은 답을 '대신 내주는' 도구가 아니라, 하나의 거래를 판단 게이트로 분해해 "
        "'경우의 수(안전·주의·위험)'와 경우별 세무리스크·절세전략을, 법령·내부자료·판례 근거와 함께 "
        "회계사 검토용 보고서(DOCX)로 자동 작성하는 검토 보조 시스템입니다. 최종 판단·서명은 회계사가 합니다.",
        COLORS["light_blue"], COLORS["blue"], height=104, icon="▶")
    y = table(
        page, y, ["구분", "내용"],
        [
            ("무엇을", "거래별 '경우의 수' 절세전략·세무리스크 의사결정 보고서(DOCX) 자동 생성"),
            ("누구를 위해", "Business Tax 자문 회계사·세무사(검토 초안 보조)"),
            ("어떤 거래", "자기주식 취득·임원 보수/퇴직금·가지급금·연구개발 세액공제 등 (확장 가능)"),
            ("왜 신뢰 가능", "근거 인용 강제(날조 차단)·DART 실재무 그라운딩·3중 교차검증·fail-closed·HITL"),
            ("대표 산출물", "가나다정밀(데모 3쟁점) · 한미반도체(DART 실재무 4쟁점) 보고서 2종"),
        ],
        [110, PAGE_W - 2 * M - 110], row_h=30, font_size=9.0)
    y = callout(
        page, y, "회계사가 5분 안에 확인할 것",
        "① 결론이 '단답'이 아니라 플로우차트로 분기된 경우의 수인가  ② 모든 결론에 클릭 가능한 법령 근거가 붙는가  "
        "③ 회사 실재무(DART)와 가상 예시(dummy)가 명확히 구분되는가  ④ 근거가 부족하면 '모른다'로 비우는가(정직성).",
        COLORS["light_teal"], COLORS["teal"], height=78, icon="●")
    tb(page, (M, PAGE_H - 70, PAGE_W - M, PAGE_H - 36),
       "본 문서는 시스템이 실제 생성한 산출물 차트를 그대로 임베드했습니다. "
       "수치·사실관계 중 회사 재무수치(DART)를 제외한 분개·증빙은 검토용 가상 예시입니다.",
       size=8.2, color=COLORS["gray"], lineheight=1.3)
    footer(page, n, TOTAL)

    # ---- p2 무엇을 만드나: 대표 산출물 2종 -------------------------------- #
    page = newp()
    y = heading(page, 46, "1. 무엇을 만드나 — 대표 산출물 2종")
    y = para(page, y,
             "시스템의 출력물은 회계사가 그대로 검토·수정할 수 있는 한글 DOCX 보고서입니다. "
             "동일한 렌더링 엔진으로 (A) 일반 데모 케이스와 (B) DART 실재무 그라운딩 케이스를 만듭니다. "
             "두 산출물은 시나리오 표현 형식이 완전히 동일하며, 실재무 케이스는 회사개요·종합세무검토·증빙 부록이 더해집니다.")
    y = table(
        page, y, ["산출물", "근거 데이터", "다루는 쟁점", "분량(실측)"],
        [
            ("가나다정밀(데모)", "가상 회사", "자기주식·임원보수·가지급금 (3)", "표 14 · 시나리오 3"),
            ("한미반도체(실재무)", "DART 전자공시 실값", "위 3 + 연구개발 세액공제 (4)", "표 21 · 시나리오 4"),
        ],
        [108, 105, PAGE_W - 2 * M - 213 - 78, 78], row_h=30, font_size=8.6)
    y = heading(page, y + 2, "보고서 1건의 구성 (시나리오마다 반복)", 2)
    y = table(
        page, y, ["목차", "내용", "회계사 관점의 의미"],
        [
            ("0. 방법론", "보고서 읽는 법·색상 규칙", "검토 기준 합의"),
            ("n-1 플로우차트", "판단 게이트 분기 도식", "결론에 이른 논리 추적"),
            ("n-2 경우의 수 매트릭스", "안전/주의/위험·세무리스크·절세전략", "리스크 한눈 비교"),
            ("n-3 권고안", "가장 안전한 경로", "실행 의사결정"),
            ("n-4 절세 대안 비교", "대안별 추가세부담·장단점", "대안 평가"),
            ("n-5 사후관리·실행계획", "타임라인·필요조치", "시점 최적화"),
            ("n-6 분개 예시", "권고 경로 회계처리", "장부 반영"),
            ("n-7 내부자료 근거", "실무 가이드 회수·일치 검토", "근거의 출처"),
            ("n-8 판례·해석례", "법제처 실시간 조회", "최신 해석 확인"),
            ("n-9 근거 법령", "조문 하이퍼링크", "원문 확인"),
            ("부록 A·B·C", "분개장·총계정원장·증빙 목록", "검토 패키지화"),
        ],
        [115, 205, PAGE_W - 2 * M - 320], row_h=26, font_size=8.1)
    footer(page, n, TOTAL)

    # ---- p3 핵심 개념: 경우의 수 엔진(파이프라인 도식) -------------------- #
    page = newp()
    y = heading(page, 46, "2. 핵심 개념 — '경우의 수' 의사결정 엔진")
    y = para(page, y,
             "실무 세무 판단은 '이 거래는 안전한가/위험한가'라는 단답이 아니라, 몇 개의 핵심 조건을 "
             "어떻게 충족하느냐에 따라 결과가 갈리는 '경우의 수' 문제입니다. 시스템은 각 거래를 순차 분기(판단 "
             "게이트)로 분해하고, 분기마다 ① 빗나갔을 때의 세무리스크와 ② 통과시키기 위한 절세전략을 함께 제시합니다.")
    y = insert_image(page, y, dg["pipeline"], width=PAGE_W - 2 * M)
    y = callout(
        page, y, "왜 이 구조가 회계사에게 유용한가",
        "단일 답변은 '왜 그런가'를 검증하기 어렵습니다. 게이트 분기 구조는 결론에 이른 논리를 그대로 노출하므로, "
        "회계사가 각 분기의 사실관계 가정만 점검하면 결론의 타당성을 빠르게 확인하고 수정할 수 있습니다.",
        COLORS["light_gold"], COLORS["gold"], height=72, icon="◆")
    footer(page, n, TOTAL)

    # ---- p4 실제 플로우차트(임베드) -------------------------------------- #
    page = newp()
    y = heading(page, 46, "3. 실제 출력 ① — 의사결정 플로우차트")
    y = para(page, y,
             "아래는 '비상장법인 자기주식 취득'에 대해 시스템이 실제 생성한 플로우차트입니다(한미반도체 보고서). "
             "주황 마름모=판단(분기), 빨강=세무리스크(빗나간 경우), 초록=정상 종결(요건 충족). 세로 화살표를 따라 "
             "모든 게이트를 통과하면 가장 안전한 경우(권고안)에 도달합니다.")
    y = insert_image(page, y, CHARTS / "flow_TREASURY.png", width=380, max_h=PAGE_H - y - 120)
    y = caption(page, y, "▲ 시스템이 생성한 자기주식 취득 의사결정 플로우차트 (재원→시가→균등 3 게이트)")
    y = callout(
        page, y, "근거 강제 — 날조 차단",
        "모든 분기 결론과 경우의 수에는 근거(법령) 필드가 필수입니다(미입력 시 검증 실패). 즉 모델이 결론만 내고 "
        "근거를 비우는 것을 구조적으로 막습니다. 법령 링크는 국가법령정보센터 검색으로 연결됩니다.",
        COLORS["light_red"], COLORS["red"], height=66, icon="■")
    footer(page, n, TOTAL)

    # ---- p5 매트릭스(임베드) --------------------------------------------- #
    page = newp()
    y = heading(page, 46, "4. 실제 출력 ② — 경우의 수별 결론 매트릭스")
    y = para(page, y,
             "같은 거래를 표로 펼치면, 경우마다 위험등급(안전/주의/위험)·세무리스크·절세전략·근거가 한눈에 비교됩니다. "
             "위험등급은 색으로 음영 처리되어, 어떤 경로가 안전하고 어떤 경로가 추징 위험인지 즉시 식별됩니다.")
    y = insert_image(page, y, CHARTS / "matrix_TREASURY.png", width=PAGE_W - 2 * M)
    y = caption(page, y, "▲ 동일 거래의 경우의 수별 결론 매트릭스 — 위험등급 음영 + 절세전략·리스크관리")
    y = table(
        page, y, ["위험등급", "의미", "보고서에서의 처리"],
        [
            ("안전(초록)", "요건 충족·예측 가능", "권고 경로 후보"),
            ("주의(주황)", "재구성·실익 축소 여지", "보완 증빙·대안 검토"),
            ("위험(빨강)", "과세·손금부인·추징 위험", "회피 전략·사전 신고"),
        ],
        [95, 205, PAGE_W - 2 * M - 300], row_h=27, font_size=8.6)
    footer(page, n, TOTAL)

    # ---- p6 DART 실재무 그라운딩 ----------------------------------------- #
    page = newp()
    y = heading(page, 46, "5. 신뢰성 ① — DART 실재무 그라운딩")
    y = para(page, y,
             "한미반도체 보고서는 가공의 회사가 아니라, 금융감독원 전자공시(DART) OpenAPI에서 회수한 "
             "실제 재무수치를 단서로 작성됩니다. 시스템은 '검증 가능한 실값'과 '추론용 가상 예시(dummy)'를 "
             "명확히 구분해 표기합니다 — 회계사가 무엇을 믿고 무엇을 검증해야 하는지 즉시 알 수 있습니다.")
    y = table(
        page, y, ["구분", "데이터", "출처·성격"],
        [
            ("실값(검증 가능)", "자산·자본·이익잉여금·매출·당기순이익 등", "DART 전자공시 실제 공시값"),
            ("가상 예시(dummy)", "주식수·보수액·대여금·분개·증빙·거래 사실관계", "추론용 가상 — '검토 예시'로 명시"),
        ],
        [120, PAGE_W - 2 * M - 120 - 175, 175], row_h=30, font_size=8.6)
    y = para(page, y,
             "재무수치(예: 자본금 대비 이익잉여금 누적 배율)에서 잠재 세무쟁점을 도출해 '종합세무검토' 표로 "
             "정리하고, 각 쟁점을 3장 이하의 '경우의 수' 시나리오로 연결합니다. 즉 회사의 실제 재무 상태가 "
             "쟁점 선정의 출발점이 됩니다.")
    y = callout(
        page, y, "정직성 설계",
        "재무수치 외의 사실관계는 모두 dummy임을 보고서 표지·방법론·부록에 반복 고지합니다. 실제와 무관한 예시를 "
        "사실인 것처럼 제시하지 않습니다(회계사 사실관계 확인 전제).",
        COLORS["light_gold"], COLORS["gold"], height=64, icon="◆")
    footer(page, n, TOTAL)

    # ---- p7 근거 3중 교차검증 -------------------------------------------- #
    page = newp()
    y = heading(page, 46, "6. 신뢰성 ② — 근거의 3중 교차검증")
    y = para(page, y,
             "단일 출처에 의존하지 않습니다. ① 법령(국가법령정보), ② 내부 실무자료(RAG 의미검색), "
             "③ 판례·해석례(법제처 실시간 조회)를 각각 회수해 교차검증하고, 서로 충돌하거나 비어 있는 부분을 "
             "그대로 표시합니다.")
    y = insert_image(page, y, dg["tri"], width=PAGE_W - 2 * M)
    y = table(
        page, y, ["근거 채널", "어떻게 회수하나", "회계사 관점"],
        [
            ("① 법령", "쟁점→조문 매핑 + 조문 하이퍼링크", "원문 즉시 확인"),
            ("② 내부자료(RAG)", "실무 PDF 31종을 OCR·임베딩, 의미 유사도 검색", "사내 가이드 근거"),
            ("③ 판례·해석례", "법제처 국가법령정보 실시간 조회(예규·판례)", "최신 해석 반영"),
        ],
        [95, PAGE_W - 2 * M - 95 - 150, 150], row_h=28, font_size=8.4)
    footer(page, n, TOTAL)

    # ---- p8 내부 RAG 상세 ------------------------------------------------ #
    page = newp()
    y = heading(page, 46, "7. 신뢰성 ③ — 내부자료 검색(RAG)과 '일치 검토'")
    y = para(page, y,
             "내부 실무자료는 단순 키워드 검색이 아니라, 문장의 의미를 벡터로 바꿔 유사도로 회수합니다. "
             "스캔 PDF는 온프렘 OCR(한국어)로 텍스트화해 색인에 포함했습니다. 중요한 것은, 회수 후 "
             "'왜 회수됐는지(질의어 매칭·유사도)'와 '본 쟁점과 일치하는 부분'을 함께 검토해 과대평가를 막는다는 점입니다.")
    y = table(
        page, y, ["항목", "값", "의미"],
        [
            ("색인 자료", "실무 PDF 31종(스캔본 포함)", "OCR로 누락 없이 색인"),
            ("색인 단위", "10,000+ 페이지 청크", "조문/문단 단위 검색"),
            ("검색 방식", "임베딩 코사인 유사도(numpy 인덱스)", "의미 기반 회수"),
            ("일치 검토", "핵심어 2개+ 겹침=직접관련 / 1개=부분 / 0=참고만", "단일 키워드 과신 차단"),
            ("실패 처리", "색인 미가용 시 근거 생략·정직 고지(fail-closed)", "없는 근거를 지어내지 않음"),
        ],
        [110, 200, PAGE_W - 2 * M - 310], row_h=27, font_size=8.3)
    y = callout(
        page, y, "회계사 언어로",
        "RAG는 '근거자료를 의미로 검색해 무근거 단정을 줄이는 절차'이고, '일치 검토'는 회수된 자료가 정말 "
        "이 쟁점을 지지하는지 1차 점검하는 '직업적 회의(professional skepticism)'의 자동화입니다. "
        "최종 의미 일치는 회계사가 확인합니다.",
        COLORS["light_teal"], COLORS["teal"], height=72, icon="●")
    footer(page, n, TOTAL)

    # ---- p9 환각방지·정직성 + 기술스택 ----------------------------------- #
    page = newp()
    y = heading(page, 46, "8. 환각방지·정직성 설계 + 기술 스택")
    y = table(
        page, y, ["통제", "구현", "막아내는 위험"],
        [
            ("근거 인용 강제", "결론·경우의 수에 근거(법령) 필수, 미입력 검증 실패", "무근거 단정·날조"),
            ("실값/가상 분리", "DART 실값 vs dummy를 표지·방법론에 명시", "가짜 사실관계 혼입"),
            ("fail-closed", "RAG·판례 조회 불가 시 생략+정직 고지", "없는 근거 조작"),
            ("1차 판정 한계 고지", "키워드 일치는 '회계사 확인 필요'로 표기", "기계 판정 과신"),
            ("HITL(사람 검토)", "전 산출물 '인공지능 추론 초안' 명시·서명 전제", "검토 없는 자동 적용"),
        ],
        [105, PAGE_W - 2 * M - 105 - 120, 120], row_h=28, font_size=8.3)
    y = heading(page, y + 2, "기술 스택 (회계사용 한 줄 설명 포함)", 2)
    y = table(
        page, y, ["요소", "기술", "쉬운 뜻"],
        [
            ("문서 생성", "python-docx", "한글 검토 보고서(DOCX) 자동 작성"),
            ("도식", "matplotlib", "플로우차트·매트릭스·타임라인 그림"),
            ("내부검색", "임베딩 + numpy 코사인", "자료를 의미로 찾는 검색"),
            ("OCR", "Tesseract(kor)", "스캔 문서를 글자로 변환"),
            ("실재무", "DART OpenAPI", "공시 재무수치 회수"),
            ("법령·판례", "국가법령정보/법제처 API", "조문·예규·판례 조회"),
            ("품질", "pytest 회귀 + 단계별 코드리뷰", "회귀·오류 방지"),
        ],
        [95, 175, PAGE_W - 2 * M - 270], row_h=25, font_size=8.1)
    footer(page, n, TOTAL)

    # ---- p10 가치·한계 --------------------------------------------------- #
    page = newp()
    y = heading(page, 46, "9. 회계사가 얻는 가치 · 한계")
    y = table(
        page, y, ["전통적 방식", "이 시스템", "효과"],
        [
            ("쟁점 누락 위험", "재무→쟁점 자동 도출 + 4대 거래 시나리오", "검토 누락 감소"),
            ("결론 근거 수기 정리", "법령·내부자료·판례 자동 회수·인용", "근거 작업시간 단축"),
            ("리스크 구두 설명", "경우의 수 매트릭스·플로우차트 시각화", "고객 설명력 향상"),
            ("초안 백지 작성", "검토 패키지(보고서+분개+증빙) 초안 제공", "초안 작성시간 단축"),
        ],
        [150, PAGE_W - 2 * M - 150 - 105, 105], row_h=30, font_size=8.5)
    y = callout(
        page, y, "정직한 한계",
        "본 시스템은 '검토 보조'이지 '판단 대체'가 아닙니다. 분기·결론은 일반적 사실관계 가정에 따른 인공지능 추론이며, "
        "개별 사안의 구체적 사실관계·최신 예규·판례에 따라 결론이 달라질 수 있습니다. 분개·증빙·거래 사실관계는 가상 "
        "예시이고, 실제 회계처리·신고 전 담당 회계사의 검토와 서명이 필요합니다.",
        COLORS["light_red"], COLORS["red"], height=86, icon="■")
    y = callout(
        page, y, "한 줄 포지셔닝",
        "저는 AI를 세무전문가의 대체재가 아니라, 자료정리·근거검색·계산검산·검토초안을 담당하는 보조 시스템으로 "
        "설계했습니다. 최종 판단과 서명은 반드시 회계사가 하는 구조입니다.",
        COLORS["light_teal"], COLORS["teal"], height=64, icon="●")
    y = bullets(page, y, [
        "검증 가능성: 회사 재무수치는 DART 실값, 결론은 클릭 가능한 법령 근거로 추적 가능.",
        "확장성: 세목·거래 유형을 데이터(규칙)로 추가 — 코드 변경 없이 시나리오 확장.",
        "재현성: 동일 입력→동일 산출(오프라인 fixture), 품질은 pytest 회귀로 보증.",
    ], size=8.8)
    footer(page, n, TOTAL)

    # save 실패(파일 잠금 등) 시에도 doc 핸들을 반드시 닫아 누수·재잠금 방지(codex HIGH).
    try:
        try:
            doc.subset_fonts()  # 사용 글리프만 남겨 malgun 전체 임베드(≈15MB) 방지
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ subset_fonts 생략({type(exc).__name__})")
        doc.save(OUT_PDF, garbage=4, deflate=True, deflate_images=True, clean=True)
        size_mb = OUT_PDF.stat().st_size / 1e6
        print(f"생성 완료: {OUT_PDF}  ({n} pages, {size_mb:.2f} MB)")
    finally:
        doc.close()


if __name__ == "__main__":
    build_pdf()
