"""scripts/build_comprehensive_review.py — 리노공업㈜ 종합검토 DOCX 최종 산출.

대표 데모(리노공업㈜)에 대해 **①법령·②내부자료(실제 임베딩 RAG DB)·③공식웹 3소스 +
종합의견** 을 §2 에 싣고, 그 아래로 재무제표·계정별원장·분개장·절세전략 스크리닝·적용
전략(사후관리·필요 조치·자료 포함)·실행 로드맵(미래 plan)까지 한 문서로 렌더한다.

② 내부자료 채널은 ``src.rag_db_index`` 의 영속 임베딩 인덱스에서 질문 관련 실무 가이드
페이지를 실제로 회수해 출처(파일·페이지)와 함께 싣는다. 인덱스가 없으면 ②채널은
보류(침묵)로 표시되고 나머지는 정상 산출된다(날조 0·fail-closed).

    python scripts/build_comprehensive_review.py [--no-rag] [--out PATH]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.strategy_plan import attach_rag_db_research, build_demo_strategy_plan  # noqa: E402
from src.strategy_plan_report import build_strategy_plan_docx  # noqa: E402

_DEFAULT_OUT = _REPO / "산출물" / "리노공업_법인절세전략_종합검토.docx"


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="리노공업㈜ 3소스 종합검토 DOCX 산출")
    ap.add_argument("--out", default=str(_DEFAULT_OUT), help="출력 DOCX 경로")
    ap.add_argument("--no-rag", action="store_true",
                    help="내부 RAG DB 회수를 건너뛴다(②채널 보류 표시)")
    ap.add_argument("--top-k", type=int, default=4, help="② RAG 회수 passage 수")
    args = ap.parse_args(argv)

    data, titles, articles = build_demo_strategy_plan()
    if not args.no_rag:
        print("▶ 내부 실무자료(RAG DB) 회수 — 영속 임베딩 인덱스 조회…")
        data = attach_rag_db_research(data, top_k=args.top_k)
        rag_ch = next((c for c in data.research.channels if c.authority == "실무서"), None)
        n = len(getattr(rag_ch, "rag_evidence", [])) if rag_ch else 0
        if n:
            print(f"  회수 {n}건:")
            for ev in rag_ch.rag_evidence:
                print(f"   · [{ev.score}] {ev.source}")
        else:
            print("  회수 0건 또는 인덱스 미빌드 → ②채널 보류(침묵)로 표기")

    out = Path(args.out)
    build_strategy_plan_docx(data, out, titles=titles, articles=articles)
    print(f"\n✔ 산출 완료: {out}")
    print("  §2 법령·내부자료·공식웹 3소스 + 종합의견 / §6 계정별원장 / §7 분개장 / "
          "§9 사후관리·필요조치 / §10 실행 로드맵 포함")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
