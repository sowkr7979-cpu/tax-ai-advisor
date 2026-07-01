#!/usr/bin/env python3
"""scripts/export_scenarios_json.py — 시나리오 의사결정 데이터를 웹 데모용 JSON으로 export.

``scenario_planner.demo_scenarios()`` + 연구개발 시나리오(RND)의 gates/leaves/근거를 그대로
직렬화해, 정적 HTML 데모(web/demo.html)가 **실제 엔진 데이터**로 '경우의 수' 추론을 클라이언트에서
재생할 수 있게 한다. 근거·결론은 Python 모델이 강제한 값 그대로(날조 0).

사용:  레포 루트에서  PYTHONUTF8=1 python scripts/export_scenarios_json.py
"""
from __future__ import annotations

import base64
import dataclasses
import json
from pathlib import Path

from src.scenario_planner import demo_scenarios

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "data" / "scenarios.json"
CHARTS = ROOT / "산출물" / "_charts_scn"


def _chart_data_uri(kind: str, key: str) -> str | None:
    """차트 PNG → data URI(base64). file:// 로컬에서도 도식이 보고서에 임베드되도록 데이터에 내장."""
    p = CHARTS / f"{kind}_{key}.png"
    if not p.exists():
        return None
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _charts(key: str) -> dict:
    out = {}
    for js_name, kind in (("flow", "flow"), ("mx", "matrix"), ("burden", "burden"), ("tl", "tl")):
        uri = _chart_data_uri(kind, key)
        if uri:
            out[js_name] = uri
    return out


def _scenario_to_dict(s) -> dict:
    return {
        "charts": _charts(s.key),
        "key": s.key,
        "title": s.title,
        "trigger": s.trigger,
        "summary": s.summary,
        "facts": s.facts or s.trigger,
        "safe_title": s.safe_title,
        "safe_detail": s.safe_detail,
        "recommended_case": s.recommended_case,
        "gates": [dataclasses.asdict(g) for g in s.gates],
        "leaves": [dataclasses.asdict(lf) for lf in s.leaves],
        "citations": list(s.citations),
        "aftercare": list(s.aftercare),
        "actions": list(s.actions),
        "plan": [dataclasses.asdict(p) for p in s.plan],
        "alternatives": [dataclasses.asdict(a) for a in s.alternatives],
        "journal": (
            {
                "title": s.journal.title,
                "note": s.journal.note,
                "lines": [dataclasses.asdict(ln) for ln in s.journal.lines],
            }
            if s.journal
            else None
        ),
    }


def main() -> int:
    scns = demo_scenarios()
    for s in scns:
        s.validate()
    payload = {
        "generated_for": "web demo (rule-based decision engine replay)",
        "disclaimer": (
            "본 데모는 실제 시나리오 엔진 데이터를 규칙 기반으로 재생합니다. "
            "결론·근거는 인공지능 추론 초안이며 회계사 검토(HITL)가 필요합니다. "
            "금액·사실관계는 가상 예시(dummy)입니다."
        ),
        "scenarios": [_scenario_to_dict(s) for s in scns],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    js_text = json.dumps(payload, ensure_ascii=False, indent=2)
    OUT.write_text(js_text, encoding="utf-8")
    # file:// 로컬에서도 동작하도록 JS 전역 형태로도 내보낸다(<script src>로 로드).
    OUT.with_suffix(".js").write_text(
        "// 자동 생성(scripts/export_scenarios_json.py) — 수정 금지\n"
        f"window.SCENARIOS = {js_text};\n",
        encoding="utf-8",
    )
    print(f"생성 완료: {OUT} (+.js)  (시나리오 {len(scns)}종)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
