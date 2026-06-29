"""scripts/record_law_fixtures.py — ONE-TIME live recording of slice-① fixtures.

# API-004 재현성: 라이브 법제처 DRF 응답을 tests/fixtures/law/ 에 raw + content_hash 로 박제.
# PROMPT.md: "라이브 법제처 호출은 fixture 녹화용 1회만, 테스트는 fixture 재생."

Run once (network + LAW_OC in .env required):

    ./.venv/Scripts/python.exe scripts/record_law_fixtures.py

After this, the slice-① harness/tests REPLAY from the recorded fixtures with NO
network. Secrets (OC) are NEVER written — only OC-redacted URLs go to the manifest.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.ai.law_data_source import (  # noqa: E402
    DEFAULT_FIXTURES_DIR,
    LawSourceUnavailable,
    MOLEGLawDataSource,
    RecordingTransport,
)

# The (법령명, 조문, as_of_date) the gold set needs. as_of_date == efYd, so the
# fixture key (efYd) matches each gold query's applicable_basis.as_of_date.
RECORD_TARGETS = [
    ("법인세법", "제25조", date(2024, 1, 1)),   # 기업업무추진비 (public main)
    ("법인세법", "제25조", date(2020, 1, 1)),   # 접대비 (public temporal contrast)
    ("법인세법", "제24조", date(2024, 1, 1)),   # 기부금 (hidden; reuses ef2024 body)
]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    try:
        transport = RecordingTransport(DEFAULT_FIXTURES_DIR)
    except LawSourceUnavailable as exc:
        print(f"녹화 불가: {exc}", file=sys.stderr)
        return 2

    source = MOLEGLawDataSource(transport=transport)
    print(f"recording fixtures → {DEFAULT_FIXTURES_DIR}")
    for law_name, article, as_of in RECORD_TARGETS:
        result = source.lookup_provision(law_name, article, as_of)
        pv = result.provision_version
        print(
            f"  ✓ {law_name} {article} as_of={as_of} → 시행 {pv.effective_from} "
            f"'{result.article_title}' hash={pv.snapshot_id} "
            f"snap_hash={result.snapshot.content_hash[:12]}"
        )
    print("done. fixtures + manifest written (raw response bytes, OC redacted).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
