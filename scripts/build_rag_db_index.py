#!/usr/bin/env python3
"""scripts/build_rag_db_index.py — 내부 RAG DB(공개 세무 실무 가이드 PDF) 임베딩 인덱스 빌드.

``RAG DB/*.pdf`` 를 페이지 청크로 추출(텍스트 레이어가 없는 스캔본은 온프렘 OCR =
Ghostscript+Tesseract(kor)) → model2vec 로 임베딩 → ``RAG DB/_index/`` 에 numpy 코사인
인덱스(벡터행렬 .npy + 사이드카 .jsonl + manifest.json)로 영속한다(외부 전송 0).

사용:  레포 루트에서  PYTHONUTF8=1 python scripts/build_rag_db_index.py
옵션:  --no-ocr  (스캔본 OCR 비활성 — 텍스트 PDF만 색인)
"""
from __future__ import annotations

import argparse
import sys

import src.rag_db_index as ragdb


def main() -> int:
    ap = argparse.ArgumentParser(description="내부 RAG DB 임베딩 인덱스 빌드")
    ap.add_argument("--no-ocr", action="store_true", help="스캔본 OCR 비활성")
    ap.add_argument("--dpi", type=int, default=300, help="OCR 렌더 DPI(기본 300)")
    args = ap.parse_args()

    print(f"RAG DB 디렉터리: {ragdb.RAG_DB_DIR}")
    if not args.no_ocr:
        print(f"OCR 가용: {ragdb.ocr_available()} "
              f"(gs={bool(ragdb._find_ghostscript())}, "
              f"tesseract={bool(ragdb._find_tesseract())}, "
              f"kor데이터={bool(ragdb._find_tessdata())})")

    # extract_chunks 의 OCR 토글은 build_index 가 항상 켠 채로 호출하므로, --no-ocr 시엔
    # 임시로 ocr_available 를 비활성화한다(가장 단순한 주입점).
    if args.no_ocr:
        ragdb.ocr_available = lambda: False  # type: ignore[assignment]

    stats = ragdb.build_index(progress=True, ocr_dpi=args.dpi)
    print("\n=== 빌드 완료 ===")
    for k in ("model", "dimension", "files", "pages_with_text", "chunks",
              "ocr_files", "skipped_files"):
        print(f"  {k}: {stats.get(k)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
