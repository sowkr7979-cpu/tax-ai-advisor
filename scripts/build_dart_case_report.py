#!/usr/bin/env python3
"""scripts/build_dart_case_report.py — DART 실재무 회사 종합세무검토+의사결정 보고서 생성.

DART OpenAPI 로 임의의 상장사 1곳의 재무제표를 회수하여, 종합세무검토 + 회사 그라운딩
[사실관계] 기반 '경우의 수' 절세전략·세무리스크 의사결정 보고서(분개장·원장·증빙 dummy 포함)를
DOCX 한 부로 생성한다.

사용:  레포 루트에서  PYTHONUTF8=1 python scripts/build_dart_case_report.py [--company 한미반도체] [--year 2024] [--no-rag]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.dart_case_data import build_dart_company_report


def main() -> int:
    ap = argparse.ArgumentParser(description="DART 회사 종합세무검토·의사결정 보고서 생성")
    ap.add_argument("--company", default="한미반도체", help="회사명 또는 6자리 종목코드")
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--fs", default="CFS", choices=["CFS", "OFS"], help="연결(CFS)/별도(OFS)")
    ap.add_argument("--out", default="")
    ap.add_argument("--no-rag", action="store_true")
    ap.add_argument("--no-charts", action="store_true")
    args = ap.parse_args()

    out = args.out or str(Path("산출물") / f"{args.company}_종합세무검토_경우의수_의사결정보고서.docx")
    path, fin, scns = build_dart_company_report(
        args.company, args.year, out, fs_div=args.fs,
        with_rag=not args.no_rag, with_charts=not args.no_charts,
    )
    print(f"생성 완료: {path}")
    print(f"  회사: {fin.corp_name}({fin.stock_code}) · {fin.year} {fin.fs_div} · 재무라인 {len(fin.lines)}")
    print(f"  시나리오 {len(scns)}종: " + " / ".join(f"{s.key}({len(s.leaves)}경우)" for s in scns))
    return 0


if __name__ == "__main__":
    sys.exit(main())
