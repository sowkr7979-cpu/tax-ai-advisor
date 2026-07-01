"""web/backend/llm.py — Claude 호출 래퍼 + .env 로더.

라이브 인테이크/분석용으로 Anthropic SDK를 직접 호출한다(오프라인 fixture가 아닌 실제 LLM).
키가 없으면 ``llm_available()`` 이 False → 프런트가 '오프라인' 배지를 표시한다.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_ENV_LOADED = False

# 인테이크(잦은 호출)=빠른 모델, 분석(복잡)=상위 모델. 필요시 env로 override.
INTAKE_MODEL = os.environ.get("LIVE_INTAKE_MODEL", "claude-haiku-4-5-20251001")
ANALYZE_MODEL = os.environ.get("LIVE_ANALYZE_MODEL", "claude-sonnet-4-6")


def load_env() -> None:
    """레포 루트 .env 를 os.environ 에 로드(이미 있으면 유지). python-dotenv 없이 간단 파서."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    env = _ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)
    _ENV_LOADED = True


def llm_available() -> bool:
    load_env()
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _client():
    load_env()
    import anthropic

    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def call_claude(system: str, messages: list[dict], *, model: str | None = None,
                max_tokens: int = 1200) -> str:
    """messages = [{"role":"user"/"assistant","content":str}, ...] → 응답 텍스트.

    최신 Claude 4.x 계열은 sampling 파라미터(temperature 등)를 거부할 수 있어 전송하지 않는다.
    """
    resp = _client().messages.create(
        model=model or INTAKE_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": m["role"], "content": m["content"]} for m in messages],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


def call_claude_tool(system: str, messages: list[dict], *, tool_name: str, tool_desc: str,
                     input_schema: dict, model: str | None = None, max_tokens: int = 3000) -> dict:
    """tool-use로 구조화 출력을 강제 → 항상 유효한 dict 반환(JSON 파싱 오류 제거)."""
    resp = _client().messages.create(
        model=model or ANALYZE_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": m["role"], "content": m["content"]} for m in messages],
        tools=[{"name": tool_name, "description": tool_desc, "input_schema": input_schema}],
        tool_choice={"type": "tool", "name": tool_name},
    )
    for b in resp.content:
        if getattr(b, "type", "") == "tool_use":
            return dict(b.input)
    raise RuntimeError("tool_use 응답을 받지 못했습니다.")


def _extract_json(text: str) -> dict:
    """응답에서 첫 JSON 객체를 관대하게 파싱(코드펜스·서술 혼입 대비)."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    else:
        a, b = text.find("{"), text.rfind("}")
        if a != -1 and b != -1 and b > a:
            text = text[a:b + 1]
    return json.loads(text)


def call_claude_json(system: str, messages: list[dict], *, model: str | None = None,
                     max_tokens: int = 1500) -> dict:
    """JSON 강제 프롬프트용 — 파싱 실패 시 1회 교정 재시도."""
    sys2 = system + "\n\n반드시 유효한 JSON 객체 하나만 출력하라(코드펜스·설명 금지)."
    raw = call_claude(sys2, messages, model=model, max_tokens=max_tokens)
    try:
        return _extract_json(raw)
    except Exception:  # noqa: BLE001
        fix = call_claude(
            "직전 출력이 유효한 JSON이 아니었다. 동일 내용을 유효한 JSON 객체 하나로만 다시 출력하라.",
            messages + [{"role": "assistant", "content": raw},
                        {"role": "user", "content": "JSON만 다시 출력."}],
            model=model, max_tokens=max_tokens)
        return _extract_json(fix)
