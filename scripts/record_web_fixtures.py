"""scripts/record_web_fixtures.py — ONE-TIME live recording of slice-③ fixtures.

# PROMPT.md: "라이브 1회 녹화(Tavily + judge opus) → 테스트/CI 재생(네트워크/키 0)."
# Phase 1: live Tavily search (TAVILY_API_KEY) for each gold web query's PRIMARY
#          query → tests/fixtures/web/ (raw JSON + content_hash, key redacted).
# Phase 2: REPLAY Tavily (just recorded) + LIVE Anthropic (ANTHROPIC_API_KEY) to
#          record the WEB SourceAnswer generation + judge verdict → tests/fixtures/llm/.
# After this, the slice-③ harness/tests REPLAY everything (no network, no keys).

Run once (network + TAVILY_API_KEY + ANTHROPIC_API_KEY + LAW_OC fixtures present):

    ./.venv/Scripts/python.exe scripts/record_web_fixtures.py
    ./.venv/Scripts/python.exe scripts/record_web_fixtures.py --tavily-only   # phase 1 only
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
from src.ai.tavily_client import (  # noqa: E402
    DEFAULT_WEB_FIXTURES_DIR,
    RecordingTavilyTransport,
    TavilyClient,
    WebSearchUnavailable,
    default_tavily_client,
)
from src.judge import Judge  # noqa: E402
from src.web_research import WebResearchPipeline, plan_queries  # noqa: E402
from tiw.eval.loader import load_hidden_cases, load_public_cases  # noqa: E402


def _utf8():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def _web_queries():
    cases = load_public_cases(3) + load_hidden_cases(3)
    for case in cases:
        for q in case.web_queries:
            yield case, q


def record_tavily() -> int:
    try:
        transport = RecordingTavilyTransport(DEFAULT_WEB_FIXTURES_DIR)
    except WebSearchUnavailable as exc:
        print(f"Tavily 녹화 불가: {exc}", file=sys.stderr)
        return 2
    client = TavilyClient(transport=transport)
    print(f"recording Tavily fixtures → {DEFAULT_WEB_FIXTURES_DIR}")
    for case, q in _web_queries():
        plan = plan_queries(law_name=q.law_name, article_label=q.article_label,
                            as_of_date=q.as_of_date, issue=q.issue, tax_type=q.tax_type)
        resp = client.search(plan.primary)
        official = [r for r in resp.results if r.official]
        print(f"  ✓ {case.case_id}/{q.query_id} '{plan.primary}'")
        print(f"      results={len(resp.results)} official={len(official)} "
              f"domains={sorted({r.domain for r in resp.results})}")
        for r in resp.results[:8]:
            tag = "OFFICIAL" if r.official else "non-official"
            print(f"        [{tag}] {r.domain}  {r.url[:90]}  (content {len(r.content)}b)")
    return 0


def record_llm() -> int:
    config = LLMConfig.from_vendors()
    try:
        transport = RecordingLLMTransport(config, DEFAULT_LLM_FIXTURES_DIR)
    except LLMUnavailable as exc:
        print(f"LLM 녹화 불가: {exc}", file=sys.stderr)
        return 2
    client = LLMClient(config=config, transport=transport)
    judge = Judge(client)
    # REPLAY Tavily (recorded in phase 1) + live law replay
    pipeline = WebResearchPipeline(tavily=default_tavily_client(), law_source=default_law_source())
    print(f"recording WEB gen+judge fixtures (model={config.model}) → {DEFAULT_LLM_FIXTURES_DIR}")
    for case, q in _web_queries():
        sa_id = f"sa_{case.case_id}_{q.query_id}"
        web = pipeline.run(
            question_text=q.question_text, law_name=q.law_name, article_label=q.article_label,
            as_of_date=q.as_of_date, issue=q.issue, tax_type=q.tax_type, high_risk=q.high_risk,
            basis_kind=q.basis_kind, source_answer_id=sa_id,
            answer_run_id=f"ar_{case.case_id}_{q.query_id}", llm_client=client,
        )
        if web.abstained or web.research is None:
            print(f"  ! {case.case_id}/{q.query_id} ABSTAINED (no promotion) — "
                  f"gold expect_promote={q.expect_promote}")
            continue
        verdict = judge.score(
            question_text=q.question_text, answer=web.research,
            provision_quote=web.promoted.provision_version.text,
            gold_issues=list(q.gold_issues), tag=f"judge_{case.case_id}_{q.query_id}",
        )
        print(f"  ✓ {case.case_id}/{q.query_id} promoted={web.promoted.snapshot.publisher} "
              f"→ judge {verdict.buckets} entail={[e.supported for e in verdict.entailments]}")
    inp, outp = client.total_tokens
    print(f"done. recorded {len(client.calls)} LLM calls "
          f"({inp} in / {outp} out tokens, ~${client.total_cost_usd:.4f}).")
    return 0


def main(argv: list[str] | None = None) -> int:
    _utf8()
    argv = argv if argv is not None else sys.argv[1:]
    if "--llm-only" in argv:            # reuse already-recorded Tavily fixtures (replay)
        return record_llm()
    rc = record_tavily()
    if rc != 0 or "--tavily-only" in argv:
        return rc
    return record_llm()


if __name__ == "__main__":
    raise SystemExit(main())
