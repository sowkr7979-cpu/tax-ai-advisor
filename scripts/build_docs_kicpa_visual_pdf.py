from pathlib import Path
import textwrap

import fitz
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT_PDF = ROOT / "docs_KICPA_비개발자_도식화_해설서_별도.pdf"
ASSET_DIR = ROOT / "docs_kicpa_visual_assets"

FONT_REG = "C:/Windows/Fonts/malgun.ttf"
FONT_BOLD = "C:/Windows/Fonts/malgunbd.ttf"
PAGE_W, PAGE_H = fitz.paper_size("a4")
M = 40

COLORS = {
    "navy": "17324D",
    "teal": "0B6B5E",
    "blue": "2E74B5",
    "green": "2F6B4F",
    "gold": "7A5A00",
    "red": "9B1C1C",
    "gray": "667085",
    "light_teal": "EAF5F3",
    "light_blue": "E8F1FA",
    "light_green": "EAF5EF",
    "light_gold": "FFF6DB",
    "light_red": "FDEDED",
    "light_gray": "F3F5F7",
    "border": "D9E0E7",
    "white": "FFFFFF",
}


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4))


def add_page(doc):
    p = doc.new_page(width=PAGE_W, height=PAGE_H)
    p.insert_font(fontname="kr", fontfile=FONT_REG)
    p.insert_font(fontname="krb", fontfile=FONT_BOLD)
    return p


def textbox(page, rect, text, size=9.5, color="111827", bold=False, align=fitz.TEXT_ALIGN_LEFT, lineheight=1.18):
    page.insert_textbox(
        fitz.Rect(rect),
        text,
        fontsize=size,
        fontname="krb" if bold else "kr",
        color=rgb(color),
        align=align,
        lineheight=lineheight,
    )


def heading(page, y, text, level=1):
    textbox(page, (M, y, PAGE_W - M, y + 30), text, size=17 if level == 1 else 13, bold=True, color=COLORS["blue"] if level == 1 else COLORS["teal"])
    return y + (34 if level == 1 else 28)


def para(page, y, text, size=9.6, width=None):
    width = width or PAGE_W - 2 * M
    h = max(25, (len(text) // 50 + 2) * size * 1.35)
    textbox(page, (M, y, M + width, y + h), text, size=size, lineheight=1.22)
    return y + h + 4


def callout(page, y, title, body, fill, border, height=86):
    r = fitz.Rect(M, y, PAGE_W - M, y + height)
    page.draw_rect(r, color=rgb(border), fill=rgb(fill), width=1.1)
    textbox(page, (M + 12, y + 9, PAGE_W - M - 12, y + 29), title, size=10.2, bold=True, color=border)
    textbox(page, (M + 12, y + 31, PAGE_W - M - 12, y + height - 7), body, size=9.1)
    return y + height + 10


def table(page, y, headers, rows, widths, row_h=31, fs=7.8):
    x = M
    for j, h in enumerate(headers):
        r = fitz.Rect(x, y, x + widths[j], y + row_h)
        page.draw_rect(r, color=rgb(COLORS["border"]), fill=rgb(COLORS["teal"]), width=.8)
        textbox(page, (x + 5, y + 7, x + widths[j] - 5, y + row_h - 3), h, size=fs, bold=True, color=COLORS["white"])
        x += widths[j]
    y += row_h
    for row in rows:
        max_lines = max(max(1, len(str(c)) // 18 + 1) for c in row)
        h = max(row_h, 15 * max_lines)
        x = M
        for j, c in enumerate(row):
            fill = COLORS["light_blue"] if j == 0 else "FFFFFF"
            r = fitz.Rect(x, y, x + widths[j], y + h)
            page.draw_rect(r, color=rgb(COLORS["border"]), fill=rgb(fill), width=.55)
            textbox(page, (x + 5, y + 6, x + widths[j] - 5, y + h - 4), str(c), size=fs, bold=(j == 0))
            x += widths[j]
        y += h
    return y + 12


def bullets(page, y, items, size=9.2):
    for item in items:
        h = max(21, (len(item) // 56 + 1) * 15)
        textbox(page, (M + 8, y, PAGE_W - M, y + h), "- " + item, size=size)
        y += h + 2
    return y + 8


def footer(page, n):
    textbox(page, (M, PAGE_H - 31, PAGE_W - M, PAGE_H - 14), f"docs KICPA 비개발자 도식화 해설서 | {n}", size=7.6, color=COLORS["gray"], align=fitz.TEXT_ALIGN_CENTER)


def draw_box(draw, xy, text, fill, outline, font, wrap=12):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=18, fill=fill, outline=outline, width=3)
    lines = []
    for line in text.split("\n"):
        lines += textwrap.wrap(line, width=wrap) or [""]
    total_h = len(lines) * 30
    y = y1 + ((y2 - y1) - total_h) / 2
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=font)
        draw.text((x1 + ((x2 - x1) - (bb[2] - bb[0])) / 2, y), line, font=font, fill="#111827")
        y += 32


def arrow(draw, start, end, color="#5A6B7B", width=5):
    sx, sy = start
    ex, ey = end
    draw.line([start, end], fill=color, width=width)
    pts = [(ex, ey), (ex - 16, ey - 9), (ex - 16, ey + 9)] if ex >= sx else [(ex, ey), (ex + 16, ey - 9), (ex + 16, ey + 9)]
    draw.polygon(pts, fill=color)


def make_diagrams():
    ASSET_DIR.mkdir(exist_ok=True)
    font_title = ImageFont.truetype(FONT_BOLD, 40)
    font_box = ImageFont.truetype(FONT_BOLD, 27)
    paths = {}

    img = Image.new("RGB", (1500, 830), "white")
    d = ImageDraw.Draw(img)
    d.text((55, 35), "docs 전체 지도: 회계사가 보는 순서", font=font_title, fill="#17324D")
    d.line([(55, 96), (1445, 96)], fill="#D9E0E7", width=3)
    specs = [
        ("01 보안\n고객자료 보호", "#EAF5EF", "#2F6B4F"),
        ("02 출처\n법령 시점", "#E8F1FA", "#2E74B5"),
        ("04 ERD\n꼬리표 구조", "#F3F5F7", "#667085"),
        ("03 RFP\n요구사항", "#FFF6DB", "#7A5A00"),
        ("09 평가\n채점 기준", "#FDEDED", "#9B1C1C"),
    ]
    coords = [(55, 210, 295, 350), (345, 210, 585, 350), (635, 210, 875, 350), (925, 210, 1165, 350), (1215, 210, 1455, 350)]
    for i, (text, fill, outline) in enumerate(specs):
        draw_box(d, coords[i], text, fill, outline, font_box)
        if i < 4:
            arrow(d, (coords[i][2], 280), (coords[i + 1][0], 280))
    draw_box(d, (220, 520, 1280, 670), "05 RAG · 06 웹 · 07 API · 08 환각방지\n= 실제로 근거를 찾고, 외부서비스를 쓰고, 답변을 검증하는 실행 계층", "#FFFFFF", "#2E74B5", font_box, wrap=38)
    paths["map"] = ASSET_DIR / "docs_map.png"
    img.save(paths["map"], quality=95)

    img = Image.new("RGB", (1500, 830), "white")
    d = ImageDraw.Draw(img)
    d.text((55, 35), "세무 AI 답변이 만들어지는 흐름", font=font_title, fill="#17324D")
    d.line([(55, 96), (1445, 96)], fill="#D9E0E7", width=3)
    specs = [
        ("질문·자료\n입력", "#E8F1FA", "#2E74B5"),
        ("고객자료\n격리 확인", "#EAF5EF", "#2F6B4F"),
        ("법령·예규\n근거 검색", "#FFF6DB", "#7A5A00"),
        ("답변 초안\n생성", "#F3F5F7", "#667085"),
        ("검증 게이트\n통과", "#FDEDED", "#9B1C1C"),
        ("CPA 검토\nDOCX 초안", "#EAF5F3", "#0B6B5E"),
    ]
    coords = [(55, 300, 255, 430), (300, 300, 500, 430), (545, 300, 745, 430), (790, 300, 990, 430), (1035, 300, 1235, 430), (1280, 300, 1480, 430)]
    for i, (text, fill, outline) in enumerate(specs):
        draw_box(d, coords[i], text, fill, outline, font_box)
        if i < 5:
            arrow(d, (coords[i][2], 365), (coords[i + 1][0], 365))
    paths["flow"] = ASSET_DIR / "answer_flow.png"
    img.save(paths["flow"], quality=95)

    img = Image.new("RGB", (1500, 830), "white")
    d = ImageDraw.Draw(img)
    d.text((55, 35), "5개 검문소: 환각을 막는 구조", font=font_title, fill="#17324D")
    d.line([(55, 96), (1445, 96)], fill="#D9E0E7", width=3)
    specs = [
        ("G1\n계산검산", "#E8F1FA", "#2E74B5"),
        ("G2\n인용검증", "#E8F1FA", "#2E74B5"),
        ("G3\n충돌검사", "#FFF6DB", "#7A5A00"),
        ("G4\n시점확인", "#FFF6DB", "#7A5A00"),
        ("G5\n사람승인", "#EAF5EF", "#2F6B4F"),
    ]
    coords = [(150, 300, 350, 440), (410, 300, 610, 440), (670, 300, 870, 440), (930, 300, 1130, 440), (1190, 300, 1390, 440)]
    for i, (text, fill, outline) in enumerate(specs):
        draw_box(d, coords[i], text, fill, outline, font_box)
        if i < 4:
            arrow(d, (coords[i][2], 370), (coords[i + 1][0], 370))
    draw_box(d, (240, 575, 1260, 700), "모르면 단정하지 않고 되묻는다: 어느 사업연도? 어떤 거래일? 어떤 자료 기준?", "#FFFFFF", "#9B1C1C", font_box, wrap=40)
    paths["gates"] = ASSET_DIR / "gates.png"
    img.save(paths["gates"], quality=95)
    return paths


def image(page, y, path):
    pix = fitz.Pixmap(str(path))
    w = PAGE_W - 2 * M
    h = w * pix.height / pix.width
    page.insert_image(fitz.Rect(M, y, M + w, y + h), filename=str(path))
    return y + h + 10


def build_pdf():
    diagrams = make_diagrams()
    doc = fitz.open()

    page = add_page(doc)
    y = 72
    textbox(page, (M, y, PAGE_W - M, y + 80), "docs 문서 세트\nKICPA 비개발자 도식화 해설서", size=23, bold=True, color=COLORS["navy"])
    y += 100
    textbox(page, (M, y, PAGE_W - M, y + 30), "Tax Intelligence Workspace 설계 문서를 회계사 관점으로 읽는 법", size=12.5, color=COLORS["gray"])
    y += 52
    y = callout(page, y, "이 PDF의 목적", "docs는 개발자용 단어가 많지만, 본질은 고객자료를 안전하게 다루고 근거 있는 세무 검토 초안을 만들기 위한 내부통제 설계입니다. 이 문서는 각 장을 KICPA가 이해하기 쉬운 업무 언어로 바꿔 설명합니다.", COLORS["light_blue"], COLORS["blue"], 112)
    y = table(page, y, ["읽는 관점", "내용"], [
        ("기술보다 통제", "RAG, API, ERD보다 '무슨 위험을 막는가'를 먼저 봅니다."),
        ("세무 판단", "법령 시점, 근거 인용, 자료한계, Reviewer 승인 구조를 봅니다."),
        ("구현 방향", "전체 Workspace보다 리서치+검토메모 MVP부터 구현합니다."),
    ], [110, PAGE_W - 2*M - 110], 34)
    footer(page, 1)

    page = add_page(doc)
    y = heading(page, 48, "1. 전체 지도")
    y = image(page, y, diagrams["map"])
    y = callout(page, y, "핵심", "01 보안과 02 출처가 먼저입니다. 고객자료 격리와 법령 시점 유효성이 정해져야 ERD, RFP, RAG, 평가가 흔들리지 않습니다.", COLORS["light_green"], COLORS["green"], 80)
    footer(page, 2)

    page = add_page(doc)
    y = heading(page, 48, "2. 각 문서를 한 문장으로")
    rows = [
        ("README", "전체 목차와 공통 용어", "지금 설계가 어디에 있는지 보는 지도"),
        ("01 보안", "고객자료 비밀유지", "A사 자료가 B사 답변에 섞이지 않게 하는 장"),
        ("02 출처", "법령·예규의 시점 유효성", "언제 기준으로 유효한 근거인지 확인하는 장"),
        ("03 RFP", "기능 요구사항", "개발자에게 무엇을 만들라고 할지 정하는 장"),
        ("04 ERD", "데이터 관계도", "답변·근거·로그가 추적되게 하는 꼬리표 구조"),
        ("05 RAG", "내부자료 검색", "문서를 어떻게 잘라 근거로 찾을지 정하는 장"),
        ("06 웹", "공식근거 수집", "웹을 답변기가 아니라 공식자료 발견 도구로 쓰는 장"),
        ("07 API", "외부서비스 연결", "AI·검색·OCR·법령 API를 안전하게 쓰는 장"),
        ("08 환각방지", "답변 검증 게이트", "계산·인용·충돌·시점·사람승인을 확인하는 장"),
        ("09 채점표", "품질 평가", "누수·날조·시점오류를 점수로 막는 장"),
    ]
    table(page, y, ["문서", "쉬운 의미", "회계사식 해석"], rows, [58, 138, PAGE_W - 2*M - 196], 28, 7.2)
    footer(page, 3)

    page = add_page(doc)
    y = heading(page, 48, "3. 세무 AI 답변 흐름")
    y = image(page, y, diagrams["flow"])
    y = bullets(page, y, [
        "질문을 받으면 먼저 적용연도·거래일·자료 범위를 확인합니다.",
        "고객자료는 client_id, matter_id로 격리합니다.",
        "법령·예규·판례·내부자료·공식 웹 근거를 독립적으로 찾습니다.",
        "답변은 검증 게이트를 통과해야 하며, 고위험 판단은 CPA/Reviewer가 승인합니다.",
        "최종 산출은 고객에게 바로 내보내는 의견서가 아니라 회계사 검토용 DOCX 초안입니다.",
    ])
    footer(page, 4)

    page = add_page(doc)
    y = heading(page, 48, "4. 보안 문서 이해하기")
    y = para(page, y, "01 문서는 개발 보안 문서처럼 보이지만, KICPA 관점에서는 고객자료 비밀유지와 접근권한 통제 문서입니다.")
    y = table(page, y, ["개념", "쉬운 설명", "회계사 비유"], [
        ("client_id", "자료가 어느 고객 것인지 붙이는 꼬리표", "조서철의 고객명"),
        ("matter_id", "어느 업무 건인지 붙이는 꼬리표", "A사 법인세 검토 건"),
        ("ACL/RBAC", "누가 어느 자료를 볼 수 있는지 정하는 권한", "Engagement team 접근권한"),
        ("비학습", "외부 AI가 고객자료를 학습하지 못하게 하는 조건", "비밀유지 약정"),
        ("AuditLog", "누가 무엇을 봤는지 남기는 기록", "검토·승인 이력"),
    ], [82, 230, PAGE_W - 2*M - 312], 31)
    y = callout(page, y, "면접식 한 줄", "고객 재무정보를 다루는 AI는 기능보다 먼저 격리, 접근권한, 감사로그, 보존·파기 정책이 설계되어야 합니다.", COLORS["light_green"], COLORS["green"], 78)
    footer(page, 5)

    page = add_page(doc)
    y = heading(page, 48, "5. 출처·시점 문서 이해하기")
    y = para(page, y, "02 문서의 핵심은 '법령을 인용했다'가 아니라 '해당 거래일·귀속연도에 유효한 법령 버전을 인용했다'입니다.")
    y = table(page, y, ["개념", "쉬운 설명", "왜 중요한가"], [
        ("ProvisionVersion", "시행일이 박힌 조문 버전", "구법/신법 혼동 방지"),
        ("Citation", "답변 문장과 근거의 연결", "근거 없는 단정 방지"),
        ("applicable_basis", "거래일·귀속연도 등 판단 기준일", "시점에 따라 결론이 달라짐"),
        ("TransitionRule", "부칙·경과규정", "개정 전 사업연도 적용 여부 판단"),
        ("Abstain", "정보 부족 시 결론 보류", "모르면 되묻는 안전장치"),
    ], [95, 210, PAGE_W - 2*M - 305], 31)
    y = callout(page, y, "면접식 한 줄", "세무는 '언제 기준이냐'가 답을 바꿉니다. 그래서 AI 인용은 URL이 아니라 시행일 버전이 있는 조문 객체에 묶어야 합니다.", COLORS["light_blue"], COLORS["blue"], 82)
    footer(page, 6)

    page = add_page(doc)
    y = heading(page, 48, "6. RAG·웹·API 문서 이해하기")
    y = para(page, y, "05~07은 구현 계층입니다. 비개발자라면 '문서를 어떻게 근거로 만들고, 외부 서비스를 어떻게 안전하게 쓰는가'로 이해하면 됩니다.")
    y = table(page, y, ["문서", "하는 일", "회계사식 이해"], [
        ("05 RAG", "문서를 chunk로 나누고 검색", "법령은 조문 단위, 예규는 회신요지 단위로 색인"),
        ("06 웹", "최신 공식근거 수집", "블로그가 아니라 국세청·법제처 원문 확인"),
        ("07 API", "외부 AI·검색·OCR 연결", "비학습·비용·장애·벤더교체 통제"),
    ], [70, 190, PAGE_W - 2*M - 260], 38)
    y = bullets(page, y, [
        "RAG는 실무서를 통째로 AI에 넣는 것이 아니라 관련 조각만 찾아 넣는 구조입니다.",
        "웹 검색은 답변 근거가 아니라 공식근거를 발견하는 도구입니다.",
        "외부 API는 고객자료 전송정책, 비용, 장애 대응, 로그가 함께 설계되어야 합니다.",
    ])
    footer(page, 7)

    page = add_page(doc)
    y = heading(page, 48, "7. 환각방지와 채점표 이해하기")
    y = image(page, y, diagrams["gates"])
    y = table(page, y, ["위험", "막는 장치"], [
        ("계산 오류", "Ground Truth 계산검산"),
        ("가짜 인용", "Citation 존재·버전·pinpoint·entailment 검증"),
        ("출처 충돌", "ConflictFlag로 표시하고 검토항목 승격"),
        ("시점 불명", "결론 금지, 어느 사업연도인지 되물음"),
        ("고위험 조언", "HITL, Reviewer 승인"),
    ], [120, PAGE_W - 2*M - 120], 28)
    footer(page, 8)

    page = add_page(doc)
    y = heading(page, 48, "8. KICPA가 외워야 할 개발 용어")
    rows = [
        ("Tenant", "분리된 고객/조직 공간", "고객별 자료실"),
        ("RAG", "자료를 검색해 근거로 쓰는 AI 방식", "근거조회"),
        ("Chunk", "문서를 잘라놓은 조각", "조문/문단 단위"),
        ("Embedding", "문장의 의미를 숫자로 바꾼 것", "의미 기반 색인"),
        ("Vector DB", "의미 기반 검색 저장소", "검색용 자료철"),
        ("Rerank", "검색 후보를 다시 정렬", "관련성 높은 근거 선별"),
        ("HITL", "사람 승인 절차", "Reviewer 검토"),
        ("Trace", "실행 이력", "감사추적성"),
        ("Eval", "평가 테스트", "품질관리 체크리스트"),
    ]
    table(page, y, ["용어", "쉬운 뜻", "회계사식 표현"], rows, [80, 220, PAGE_W - 2*M - 300], 29, 7.7)
    y = callout(page, PAGE_H - 158, "읽는 요령", "개발 용어를 외우는 것이 목표가 아닙니다. 각 용어가 어떤 세무 리스크를 줄이는 통제인지 설명할 수 있으면 됩니다.", COLORS["light_gold"], COLORS["gold"], 86)
    footer(page, 9)

    page = add_page(doc)
    y = heading(page, 48, "9. 이 문서 세트를 한 문장으로 설명하면")
    y = callout(page, y, "최종 요약", "docs는 Tax Intelligence Workspace를 만들기 위한 실행 명세입니다. 핵심은 고객자료 격리, 법령 시점 유효성, 근거 검색, 외부 API 통제, 환각방지, 평가 기준을 하나의 세무 AI 내부통제 체계로 묶은 것입니다.", COLORS["light_teal"], COLORS["teal"], 112)
    y = heading(page, y + 8, "10. 다음에 구현할 MVP", 2)
    y = bullets(page, y, [
        "전체 Workspace를 한 번에 만들지 않습니다.",
        "첫 MVP는 법인세 리서치 + 검토메모 초안 생성기가 적절합니다.",
        "입력: 쟁점, 귀속연도, 사실관계",
        "처리: 공식근거 검색, 시점 확인, 인용 검증, 자료한계 표시",
        "출력: 회계사 검토용 메모와 DOCX 초안",
    ])
    y = callout(page, y, "Big4식 설명", "AI가 답을 대신 내는 것이 아니라, 회계사가 판단하기 전 단계의 자료정리·근거검색·검산·초안작성을 보조하고, 최종 판단은 사람이 하는 구조입니다.", COLORS["light_blue"], COLORS["blue"], 90)
    footer(page, 10)

    doc.save(OUT_PDF)
    doc.close()
    print(OUT_PDF)


if __name__ == "__main__":
    build_pdf()
