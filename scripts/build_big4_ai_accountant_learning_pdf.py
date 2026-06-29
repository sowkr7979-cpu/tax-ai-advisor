from pathlib import Path
import textwrap

import fitz
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT_PDF = ROOT / "Big4_면접용_AI활용_회계사_학습정리.pdf"
RENDER_DIR = ROOT / "big4_learning_pdf_render"
ASSET_DIR = ROOT / "big4_learning_assets"

FONT_REG = "C:/Windows/Fonts/malgun.ttf"
FONT_BOLD = "C:/Windows/Fonts/malgunbd.ttf"

PAGE_W, PAGE_H = fitz.paper_size("a4")
M = 40

COLORS = {
    "navy": "17324D",
    "blue": "2E74B5",
    "teal": "0B6B5E",
    "green": "2F6B4F",
    "gold": "7A5A00",
    "red": "9B1C1C",
    "gray": "667085",
    "light_blue": "E8F1FA",
    "light_teal": "EAF5F3",
    "light_green": "EAF5EF",
    "light_gold": "FFF6DB",
    "light_red": "FDEDED",
    "light_gray": "F3F5F7",
    "border": "D9E0E7",
    "black": "111827",
    "white": "FFFFFF",
}


def rgb(hex_color: str):
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))


def add_page(doc):
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_font(fontname="kr", fontfile=FONT_REG)
    page.insert_font(fontname="krb", fontfile=FONT_BOLD)
    return page


def textbox(page, rect, text, size=10, color="000000", bold=False, align=fitz.TEXT_ALIGN_LEFT, lineheight=1.18):
    return page.insert_textbox(
        fitz.Rect(rect),
        text,
        fontsize=size,
        fontname="krb" if bold else "kr",
        color=rgb(color),
        align=align,
        lineheight=lineheight,
    )


def heading(page, y, text, level=1):
    size = 17 if level == 1 else 13
    color = COLORS["blue"] if level == 1 else COLORS["teal"]
    textbox(page, (M, y, PAGE_W - M, y + 30), text, size=size, bold=True, color=color)
    return y + (34 if level == 1 else 28)


def para(page, y, text, size=9.8, color="000000", width=None, lineheight=1.23):
    width = width or PAGE_W - 2 * M
    h = max(26, (len(text) // 48 + 2) * size * 1.35)
    textbox(page, (M, y, M + width, y + h), text, size=size, color=color, lineheight=lineheight)
    return y + h + 3


def callout(page, y, title, body, fill, border, height=84):
    rect = fitz.Rect(M, y, PAGE_W - M, y + height)
    page.draw_rect(rect, color=rgb(border), fill=rgb(fill), width=1.1)
    textbox(page, (M + 12, y + 9, PAGE_W - M - 12, y + 29), title, size=10.3, bold=True, color=border)
    textbox(page, (M + 12, y + 31, PAGE_W - M - 12, y + height - 8), body, size=9.2, lineheight=1.18)
    return y + height + 10


def simple_table(page, y, headers, rows, widths, row_h=32, font_size=8.2, first_col_fill=True):
    x = M
    for j, h in enumerate(headers):
        rect = fitz.Rect(x, y, x + widths[j], y + row_h)
        page.draw_rect(rect, color=rgb(COLORS["border"]), fill=rgb(COLORS["teal"]), width=0.8)
        textbox(page, (x + 5, y + 7, x + widths[j] - 5, y + row_h - 3), h, size=font_size, bold=True, color=COLORS["white"])
        x += widths[j]
    y += row_h
    for row in rows:
        max_lines = max(max(1, len(str(c)) // 18 + 1) for c in row)
        h = max(row_h, 16 * max_lines)
        x = M
        for j, c in enumerate(row):
            fill = COLORS["light_blue"] if j == 0 and first_col_fill else "FFFFFF"
            rect = fitz.Rect(x, y, x + widths[j], y + h)
            page.draw_rect(rect, color=rgb(COLORS["border"]), fill=rgb(fill), width=0.55)
            textbox(page, (x + 5, y + 6, x + widths[j] - 5, y + h - 4), str(c), size=font_size, bold=(j == 0))
            x += widths[j]
        y += h
    return y + 12


def bullets(page, y, items, size=9.4, indent=8):
    for item in items:
        text = "- " + item
        h = max(21, (len(text) // 56 + 1) * 15)
        textbox(page, (M + indent, y, PAGE_W - M, y + h), text, size=size)
        y += h + 1
    return y + 8


def footer(page, n):
    textbox(page, (M, PAGE_H - 31, PAGE_W - M, PAGE_H - 14), f"Big4 면접용 AI 활용 회계사 학습정리 | {n}", size=7.8, color=COLORS["gray"], align=fitz.TEXT_ALIGN_CENTER)


def draw_box(draw, xy, text, fill, outline, font, text_fill="#111827", wrap=13):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=18, fill=fill, outline=outline, width=3)
    lines = []
    for line in text.split("\n"):
        lines += textwrap.wrap(line, width=wrap) or [""]
    total_h = len(lines) * 31 + (len(lines) - 1) * 3
    y = y1 + ((y2 - y1) - total_h) / 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = x1 + ((x2 - x1) - (bbox[2] - bbox[0])) / 2
        draw.text((x, y), line, font=font, fill=text_fill)
        y += 34


def arrow(draw, start, end, color="#5A6B7B", width=5):
    sx, sy = start
    ex, ey = end
    draw.line([start, end], fill=color, width=width)
    if ex >= sx:
        pts = [(ex, ey), (ex - 17, ey - 9), (ex - 17, ey + 9)]
    else:
        pts = [(ex, ey), (ex + 17, ey - 9), (ex + 17, ey + 9)]
    draw.polygon(pts, fill=color)


def make_diagrams():
    ASSET_DIR.mkdir(exist_ok=True)
    font_title = ImageFont.truetype(FONT_BOLD, 42)
    font_box = ImageFont.truetype(FONT_BOLD, 28)

    img = Image.new("RGB", (1500, 830), "white")
    d = ImageDraw.Draw(img)
    d.text((55, 35), "내가 배워야 할 5개 역량: 회계사 언어로 번역", font=font_title, fill="#17324D")
    d.line([(55, 96), (1445, 96)], fill="#D9E0E7", width=3)
    boxes = [
        ((70, 160, 320, 305), "보안·기밀\n고객자료 통제", "#EAF5EF", "#2F6B4F"),
        ((360, 160, 610, 305), "출처·시점\n근거의 유효성", "#E8F1FA", "#2E74B5"),
        ((650, 160, 900, 305), "RAG·검색\n자료에서 근거 찾기", "#FFF6DB", "#7A5A00"),
        ((940, 160, 1190, 305), "환각방지\n답변 검증", "#FDEDED", "#9B1C1C"),
        ((1230, 160, 1480, 305), "평가·채점\n품질관리", "#F3F5F7", "#667085"),
    ]
    for xy, text, fill, outline in boxes:
        draw_box(d, xy, text, fill, outline, font_box, wrap=12)
    d.text((150, 395), "Big4 면접 언어", font=font_title, fill="#0B6B5E")
    for idx, text in enumerate(["비밀유지", "감사추적성", "직업적 회의", "품질관리", "전문가 검토"]):
        x = 105 + idx * 275
        draw_box(d, (x, 500, x + 210, 635), text, "#FFFFFF", "#0B6B5E", font_box, wrap=8)
        arrow(d, (195 + idx * 290, 305), (210 + idx * 275, 500))
    p1 = ASSET_DIR / "big4_competency_map.png"
    img.save(p1, quality=95)

    img = Image.new("RGB", (1500, 830), "white")
    d = ImageDraw.Draw(img)
    d.text((55, 35), "면접 답변 구조: 기술 설명이 아니라 통제 설계로 말하기", font=font_title, fill="#17324D")
    d.line([(55, 96), (1445, 96)], fill="#D9E0E7", width=3)
    steps = [
        ("문제", "세무 AI는\n틀리면 위험"),
        ("통제", "근거·시점·보안\n먼저 설계"),
        ("구현", "RAG·API·Agent는\n그 다음"),
        ("검증", "계산·인용·충돌\n게이트"),
        ("사람", "최종 판단은\nCPA/Reviewer"),
    ]
    for i, (_, text) in enumerate(steps):
        x = 75 + i * 285
        draw_box(d, (x, 250, x + 220, 410), text, ["#FDEDED", "#EAF5EF", "#E8F1FA", "#FFF6DB", "#F3F5F7"][i], ["#9B1C1C", "#2F6B4F", "#2E74B5", "#7A5A00", "#667085"][i], font_box, wrap=12)
        d.text((x + 75, 185), steps[i][0], font=font_box, fill="#17324D")
        if i < 4:
            arrow(d, (x + 220, 330), (x + 285, 330))
    draw_box(d, (225, 565, 1275, 700), "한 줄: 저는 AI를 '답변기'가 아니라, 세무자문 품질관리 체계 안에 들어가는 검토 보조 시스템으로 설계했습니다.", "#FFFFFF", "#0B6B5E", font_box, wrap=35)
    p2 = ASSET_DIR / "interview_answer_flow.png"
    img.save(p2, quality=95)
    return {"competency": p1, "answer": p2}


def insert_image(page, y, path, width=None):
    width = width or PAGE_W - 2 * M
    pix = fitz.Pixmap(str(path))
    h = width * pix.height / pix.width
    page.insert_image(fitz.Rect(M, y, M + width, y + h), filename=str(path))
    return y + h + 10


def build_pdf():
    diagrams = make_diagrams()
    doc = fitz.open()

    page = add_page(doc)
    y = 75
    textbox(page, (M, y, PAGE_W - M, y + 70), "AI를 쓸 줄 아는 회계사로서\n무엇을 배워야 하나", size=24, bold=True, color=COLORS["navy"])
    y += 88
    textbox(page, (M, y, PAGE_W - M, y + 35), "Big4 Business Tax 면접용 학습정리", size=13, color=COLORS["gray"])
    y += 52
    y = callout(
        page,
        y,
        "핵심 결론",
        "지금 문서에서 배워야 할 것은 코딩 문법이 아니라, AI를 세무자문 업무에 넣을 때 필요한 통제 언어입니다. Big4 면접에서는 'AI로 답을 만들었다'보다 '고객자료·근거·시점·검증·사람승인 구조를 설계했다'고 말해야 합니다.",
        COLORS["light_blue"],
        COLORS["blue"],
        height=112,
    )
    y = simple_table(
        page,
        y,
        ["현재 문서", "면접에서의 의미"],
        [
            ("Claude 통합본", "제품 컨셉, 포지셔닝, 60초 설명, 왜 나인가"),
            ("docs 01~09", "보안·출처·RAG·API·환각방지·평가까지 내려간 실행 명세"),
            ("당신의 위치", "아이디어가 아니라, AI 세무자문 시스템의 통제 설계까지 온 상태"),
        ],
        [120, PAGE_W - 2 * M - 120],
        row_h=36,
    )
    footer(page, 1)

    page = add_page(doc)
    y = heading(page, 48, "1. 지금 내가 어디까지 왔는가")
    y = para(page, y, "현재 단계는 'AI에 관심 있는 회계사'가 아니라, Tax Intelligence Workspace라는 제품 개념을 업무흐름·데이터·통제·평가 기준으로 쪼개본 단계입니다.")
    y = simple_table(
        page,
        y,
        ["단계", "상태", "면접 표현"],
        [
            ("아이디어", "완료", "Business Tax 업무의 병목과 더존 위 전략층을 정의했습니다."),
            ("설계", "상당히 진행", "보안, 출처, RAG, 환각방지, 평가를 요구사항으로 나눴습니다."),
            ("구현", "초기 전", "다음은 리서치+검토메모 MVP로 좁혀 구현해야 합니다."),
            ("검증", "기준 설계 완료", "하드게이트와 채점표로 품질관리 기준을 만들었습니다."),
        ],
        [70, 95, PAGE_W - 2 * M - 165],
        row_h=35,
        font_size=8.3,
    )
    y = callout(
        page,
        y,
        "면접에서 이렇게 말하기",
        "아직 완성 제품을 만들었다고 말하기보다, 세무 AI를 안전하게 구현하기 위한 제품 설계와 통제 명세를 만들었고, 이를 리서치 MVP와 검토패키지 자동화로 구현하려 한다고 말하는 것이 정확합니다.",
        COLORS["light_gold"],
        COLORS["gold"],
        height=96,
    )
    footer(page, 2)

    page = add_page(doc)
    y = heading(page, 48, "2. 내가 배워야 할 5개 역량")
    y = insert_image(page, y, diagrams["competency"])
    y = simple_table(
        page,
        y,
        ["역량", "배워야 할 내용", "회계사식 번역"],
        [
            ("보안·기밀", "client_id, ACL, 테넌트 격리, 비학습", "고객자료 비밀유지와 접근권한 통제"),
            ("출처·시점", "ProvisionVersion, Citation, applicable_basis", "근거자료와 적용연도 확인"),
            ("RAG·검색", "Chunk, Embedding, Vector DB, rerank", "자료에서 필요한 근거를 정확히 찾는 절차"),
            ("환각방지", "계산검산, 인용검증, 충돌표시, abstain", "근거 없으면 결론 내지 않는 검토 태도"),
            ("평가·채점", "하드게이트, recall@k, entailment, regression", "품질관리와 사후검증 기준"),
        ],
        [76, 205, PAGE_W - 2 * M - 281],
        row_h=31,
        font_size=7.9,
    )
    footer(page, 3)

    page = add_page(doc)
    y = heading(page, 48, "3. Big4가 좋아할 메시지")
    y = para(page, y, "Big4 면접에서는 기술을 많이 안다고 보이는 것보다, 세무 리스크와 품질관리 관점에서 AI를 이해한다고 보이는 것이 중요합니다.")
    y = insert_image(page, y, diagrams["answer"])
    y = callout(
        page,
        y,
        "핵심 포지셔닝",
        "저는 AI를 세무전문가의 대체재가 아니라, 자료정리·근거검색·계산검산·검토초안을 담당하는 보조 시스템으로 봅니다. 최종 판단과 서명은 반드시 회계사가 해야 한다는 구조로 설계했습니다.",
        COLORS["light_teal"],
        COLORS["teal"],
        height=92,
    )
    footer(page, 4)

    page = add_page(doc)
    y = heading(page, 48, "4. 문서별로 배워야 할 말")
    rows = [
        ("01 보안", "고객자료를 AI에 넣는 순간 접근권한·격리·보존·파기까지 설계해야 합니다.", "비밀유지"),
        ("02 출처", "세무는 언제 기준인지가 결론을 바꾸므로 법령 버전과 적용시점을 묶어야 합니다.", "근거검토"),
        ("03 RFP", "AI 기능을 에이전트 수가 아니라 세무 업무흐름과 리스크 경계에서 정의했습니다.", "업무이해"),
        ("04 ERD", "답변·근거·로그가 연결되어 사후 재현 가능해야 합니다.", "감사추적성"),
        ("05 RAG", "법령은 조문 단위, 예규는 사실관계·질의·회신요지 단위로 다르게 잘라야 합니다.", "근거검색"),
        ("06 웹", "웹은 답변기가 아니라 공식근거 수집기입니다. 블로그는 결론 근거가 아닙니다.", "출처신뢰성"),
        ("07 API", "외부 AI와 검색서비스는 벤더 교체·장애·비용·비학습 조건을 통제해야 합니다.", "운영통제"),
        ("08 환각방지", "답변 전 계산·인용·충돌·시점·사람승인 게이트를 통과시킵니다.", "품질검사"),
        ("09 채점표", "구현됐다고 100점이 아니라 누수·날조·시점오류는 하드게이트로 막습니다.", "품질관리"),
    ]
    simple_table(page, y, ["문서", "내가 배워야 할 한 문장", "면접 키워드"], rows, [58, PAGE_W - 2 * M - 142, 84], row_h=29, font_size=7.4)
    footer(page, 5)

    page = add_page(doc)
    y = heading(page, 48, "5. 면접 답변 스크립트")
    scripts = [
        ("60초 소개", "제가 구상한 것은 법인세 신고서를 자동 제출하는 도구가 아니라, Business Tax 업무를 보조하는 Tax Intelligence Workspace입니다. 고객자료를 기반으로 리스크와 절세 기회를 찾고, 법령·예규 근거와 자료한계를 붙여 회계사가 검토할 수 있는 패키지 초안을 만드는 구조입니다."),
        ("왜 회계사인 내가 하는가", "감사 실무를 하며 자료의 신뢰성, 증빙, 추적성, 검토 이력의 중요성을 배웠습니다. 그래서 저는 AI를 단순 생성도구가 아니라 계산검산·근거검증·HITL이 들어간 검토 시스템으로 설계했습니다."),
        ("더존과 차이", "더존은 신고와 컴플라이언스 자동화에 강합니다. 제가 보는 영역은 그 위의 자문 판단입니다. 선택지별 세부담, 과세 리스크, 방어논리, 필요증빙을 비교해 회계사 판단을 돕는 구조입니다."),
        ("세무 깊이 질문 대응", "세무 전문성은 계속 쌓아야 한다고 생각합니다. 그래서 더더욱 AI가 단정하지 않고, 적용시점과 근거가 부족하면 되묻고, 고위험 판단은 Reviewer 승인을 받는 구조를 설계했습니다."),
    ]
    for title, body in scripts:
        y = callout(page, y, title, body, COLORS["light_blue"], COLORS["blue"], height=88)
    footer(page, 6)

    page = add_page(doc)
    y = heading(page, 48, "6. 기술 용어를 회계사 언어로 바꾸기")
    rows = [
        ("RAG", "내부자료와 법령을 검색해 근거 기반 답변을 만드는 방식", "근거자료 조회 절차"),
        ("Chunk", "문서를 검색 가능한 조각으로 자른 것", "조문/문단 단위 색인"),
        ("Embedding", "문장의 의미를 숫자로 바꾼 것", "의미 기반 검색용 색인"),
        ("Vector DB", "Embedding을 저장하고 유사한 근거를 찾는 DB", "검색용 자료철"),
        ("Citation", "답변 문장과 근거 객체의 연결", "검토메모 각주"),
        ("ProvisionVersion", "특정 시행일의 조문 버전", "해당 귀속연도 적용 법령"),
        ("HITL", "사람이 중간에 승인하는 구조", "Reviewer 승인"),
        ("Abstain", "정보 부족 시 결론 보류", "자료한계 고지·추가질문"),
        ("Entailment", "근거가 주장을 실제로 지지하는지 검증", "인용 적합성 검토"),
    ]
    simple_table(page, y, ["기술 용어", "쉬운 뜻", "회계사식 표현"], rows, [92, 225, PAGE_W - 2 * M - 317], row_h=30, font_size=7.9)
    y = callout(
        page,
        PAGE_H - 160,
        "외워야 할 관점",
        "용어를 그대로 말하기보다, 이것이 어떤 세무 리스크를 줄이는 통제인지 함께 말해야 합니다. 예: RAG를 안다고 말하지 말고, '근거자료를 검색해 무근거 단정을 줄이는 구조'라고 설명합니다.",
        COLORS["light_gold"],
        COLORS["gold"],
        height=88,
    )
    footer(page, 7)

    page = add_page(doc)
    y = heading(page, 48, "7. 내가 더 공부해야 할 부분")
    y = simple_table(
        page,
        y,
        ["우선순위", "공부할 것", "왜 필요한가", "다음 액션"],
        [
            ("1", "법인세 핵심 쟁점", "AI가 찾아도 회계사가 판단해야 함", "접대비·지급이자·가지급금·R&D부터"),
            ("2", "법령/예규 공식 데이터", "근거 없는 리서치를 막기 위해", "법제처·국세청 소스 확인"),
            ("3", "RAG 기본 구조", "내부자료 검색 품질을 통제하기 위해", "chunk/embedding/retrieval 이해"),
            ("4", "보안·비학습·권한", "고객자료를 다루는 전제", "client_id, ACL, zero-retention 정리"),
            ("5", "검증/평가", "AI 결과를 믿을 수 있게 하기 위해", "하드게이트와 평가셋 만들기"),
        ],
        [50, 120, 175, PAGE_W - 2 * M - 345],
        row_h=34,
        font_size=7.6,
    )
    y = heading(page, y + 4, "8. 다음 구현은 무엇인가", 2)
    y = para(page, y, "전체 Workspace를 한 번에 구현하는 것이 아니라, Big4 면접에서 보여주기 좋은 작은 MVP부터 구현하는 것이 맞습니다.")
    y = bullets(
        page,
        y,
        [
            "MVP 1: 법인세 리서치 + 검토메모 초안 생성기",
            "입력: 쟁점, 귀속연도, 사실관계",
            "처리: 법령/예규 근거 검색, 시점 확인, 인용 검증, 자료한계 표시",
            "출력: 회계사 검토용 메모와 DOCX 초안",
        ],
    )
    footer(page, 8)

    page = add_page(doc)
    y = heading(page, 48, "9. 최종 암기 카드")
    cards = [
        ("정체성", "감사로 검증을 배운 회계사가, 신뢰할 수 있는 세무 전략 AI를 설계했습니다."),
        ("제품", "Tax Intelligence Workspace는 법인세 자문 검토패키지 초안을 만드는 AI 작업공간입니다."),
        ("차별점", "더존이 신고·컴플라이언스라면, 저는 전략 판단 보조와 근거 검증에 초점을 뒀습니다."),
        ("안전장치", "고객자료 격리, 법령 시점 유효성, 인용검증, 계산검산, HITL을 설계했습니다."),
        ("정직한 한계", "아직 완성 제품은 아니며, 다음 단계는 리서치+검토메모 MVP 구현입니다."),
    ]
    for title, body in cards:
        y = callout(page, y, title, body, COLORS["light_teal"], COLORS["teal"], height=72)
    footer(page, 9)

    doc.save(OUT_PDF)
    doc.close()
    print(OUT_PDF)


if __name__ == "__main__":
    build_pdf()
