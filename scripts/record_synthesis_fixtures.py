"""scripts/record_synthesis_fixtures.py — ONE-TIME live recording of slice-④ fixtures.

# PROMPT.md: 신규 종합 케이스는 라이브 1회 녹화 → 테스트/CI는 fixture 재생.
# Drives the slice-④ harness (tiw.eval.slices.slice4_synthesis.run_cases) with a
# RECORDING LLM transport so the EXACT (system,user) keys the harness will later
# REPLAY are recorded: per scenario = 1 primary 생성(generate_research_answer) +
# 1 synthesis judge(SynthesisJudge.score). After this, slice-④ replays with NO
# network and NO API key.

Run once (network + ANTHROPIC_API_KEY in .env required):

    ./.venv/Scripts/python.exe scripts/record_synthesis_fixtures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.ai.llm_client import (  # noqa: E402
    DEFAULT_LLM_FIXTURES_DIR,
    LLMClient,
    LLMConfig,
    LLMUnavailable,
    RecordingLLMTransport,
)
from src.judge import SynthesisJudge  # noqa: E402
from tiw.eval.loader import load_hidden_cases, load_public_cases  # noqa: E402
from tiw.eval.slices.slice4_synthesis import run_case  # noqa: E402


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    config = LLMConfig.from_vendors()
    try:
        transport = RecordingLLMTransport(config, DEFAULT_LLM_FIXTURES_DIR)
    except LLMUnavailable as exc:
        print(f"녹화 불가: {exc}", file=sys.stderr)
        return 2

    client = LLMClient(config=config, transport=transport)
    judge = SynthesisJudge(client)

    cases = load_public_cases(4) + load_hidden_cases(4)
    print(f"recording slice-④ fixtures (model={config.model}) → {DEFAULT_LLM_FIXTURES_DIR}")
    for case in cases:
        res = run_case(case, llm_client=client, judge=judge)
        m = res.metrics
        print(
            f"  ✓ {case.case_id} ensemble={m['ensemble_kinds']} "
            f"conflict_f1={m['conflict_f1']} judge={m['judge_scores']} "
            f"entail={m['entailment']} measured={m['measured']} total={res.total}"
        )

    inp, outp = client.total_tokens
    print(
        f"done. recorded {len(client.calls)} LLM calls "
        f"({inp} in / {outp} out tokens, ~${client.total_cost_usd:.4f})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
