#!/usr/bin/env python3
"""scripts/build_scenario_dummy.py — '경우의 수' 절세전략·세무리스크 의사결정 보고서(dummy) 생성.

데모 시나리오 3종(비상장 자기주식 취득·임원 보수/퇴직금·가지급금)을 분기 추론 → 플로우차트
→ 경우별 결론 매트릭스 → 사후관리/필요조치/실행계획 → 분개 예시 → 분개장·원장 dummy 로
DOCX 한 부로 렌더한다.

사용:  레포 루트에서  PYTHONUTF8=1 python scripts/build_scenario_dummy.py [--out ...] [--no-rag] [--no-charts]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.scenario_planner import demo_scenarios
from src.scenario_report import build_scenario_docx

_DEFAULT_OUT = Path("산출물") / "가나다정밀_경우의수_절세전략_세무리스크_의사결정보고서.docx"


def main() -> int:
    ap = argparse.ArgumentParser(description="경우의 수 의사결정 보고서(dummy) 생성")
    ap.add_argument("--out", default=str(_DEFAULT_OUT))
    ap.add_argument("--no-rag", action="store_true", help="내부 RAG DB 근거 회수 생략")
    ap.add_argument("--no-charts", action="store_true", help="플로우차트/매트릭스 그림 생략")
    args = ap.parse_args()

    scns = demo_scenarios()
    out = build_scenario_docx(
        scns, args.out,
        with_rag=not args.no_rag, with_charts=not args.no_charts,
    )
    print(f"생성 완료: {out}")
    print(f"  시나리오 {len(scns)}종: " + " / ".join(f"{s.key}({len(s.leaves)}경우)" for s in scns))
    return 0


if __name__ == "__main__":
    sys.exit(main())
