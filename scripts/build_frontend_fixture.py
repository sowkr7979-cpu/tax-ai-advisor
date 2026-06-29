"""scripts/build_frontend_fixture.py — 프론트 3화면 fixture(JSON) 생성(결정적).

백엔드 산출(slice ①~④ 분석결과/선택지 + slice⑤ 검토항목 + Intake)을 대표하는
fixture 를 ``frontend/fixtures/draft_package.json`` 에 기록한다. 화면이 이 JSON 을
직접 렌더한다(더미/빈 화면 금지). 오프라인(법령 fixture replay) — 네트워크 0.

    python scripts/build_frontend_fixture.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.draft_demo import build_frontend_fixture  # noqa: E402

OUT = _REPO / "frontend" / "fixtures" / "draft_package.json"


def main() -> None:
    fixture = build_frontend_fixture()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
