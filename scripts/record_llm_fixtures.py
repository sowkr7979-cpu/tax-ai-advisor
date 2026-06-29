"""scripts/record_llm_fixtures.py — ONE-TIME live recording of slice-① LLM fixtures.

# PROMPT.md §5: "라이브로 1회 생성+judge 실행 → fixture 녹화 → 테스트/CI는 fixture 재생."
# Records, for every slice-① gold case (public + hidden), the generation answer
# AND the judge verdict to tests/fixtures/llm/ (raw text + ModelVersion + tokens).
# After this, the slice-① harness/tests REPLAY with NO network and NO API key.

Run once (network + ANTHROPIC_API_KEY in .env required):

    ./.venv/Scripts/python.exe scripts/record_llm_fixtures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.ai.law_data_source import default_law_source  # noqa: E402
from src.ai.llm_client import (  # noqa: E402
    DEFAULT_LLM_FIXTURES_DIR,
    LLMClient,
    LLMConfig,
    LLMUnavailable,
    RecordingLLMTransport,
)
from src.judge import Judge  # noqa: E402
from src.legal_research import generate_research_answer  # noqa: E402
from tiw.eval.loader import load_hidden_cases, load_public_cases  # noqa: E402


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
    judge = Judge(client)
    law = default_law_source()

    cases = load_public_cases(1) + load_hidden_cases(1)
    print(f"recording LLM fixtures (model={config.model}) → {DEFAULT_LLM_FIXTURES_DIR}")
    for case in cases:
        for q in case.law_queries:
            lookup = law.lookup_provision(q.law_name, q.article_label, q.as_of_date)
            sa_id = f"sa_{case.case_id}_{q.query_id}"
            answer = generate_research_answer(
                lookup=lookup,
                question_text=q.question_text,
                client_id="client_eval",
                answer_run_id=f"ar_{case.case_id}_{q.query_id}",
                source_answer_id=sa_id,
                source_type_label=(q.gold[0].source_type if q.gold else "법률"),
                high_risk=q.high_risk,
                llm_client=client,
            )
            verdict = judge.score(
                question_text=q.question_text,
                answer=answer,
                provision_quote=lookup.provision_version.text,
                gold_issues=list(q.gold_issues),
                tag=f"judge_{case.case_id}_{q.query_id}",
            )
            print(
                f"  ✓ {case.case_id}/{q.query_id} {q.law_name} {q.article_label} "
                f"→ judge {verdict.buckets} entail={[e.supported for e in verdict.entailments]}"
            )

    inp, outp = client.total_tokens
    print(
        f"done. recorded {len(client.calls)} LLM calls "
        f"({inp} in / {outp} out tokens, ~${client.total_cost_usd:.4f})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
