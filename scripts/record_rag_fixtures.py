"""scripts/record_rag_fixtures.py — ONE-TIME live recording of slice-② fixtures.

Records, in a single pass over the slice-② gold cases (public + hidden):
  * EVERY embedding the harness will compute (corpus chunk texts + query texts),
    using the LOCAL model2vec embedder → tests/fixtures/embeddings/manifest.json;
  * the generation + judge LLM responses (live claude-opus-4-8) →
    tests/fixtures/llm/.

After this, the slice-② harness/tests REPLAY with NO model, NO torch and NO API
key (network/key = 0). Fail-closed on any missing/tampered fixture.

Run once (network + ANTHROPIC_API_KEY in .env + model2vec installed):

    ./.venv/Scripts/python.exe scripts/record_rag_fixtures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.ai.chroma_backend import ChromaVectorStore  # noqa: E402
from src.ai.embedding_client import (  # noqa: E402
    CachedEmbedder,
    Model2VecEmbedder,
)
from src.ai.llm_client import (  # noqa: E402
    DEFAULT_LLM_FIXTURES_DIR,
    LLMClient,
    LLMConfig,
    LLMUnavailable,
    RecordingLLMTransport,
)
from src.judge import Judge  # noqa: E402
from tiw.eval.loader import load_hidden_cases, load_public_cases  # noqa: E402
from tiw.eval.slices import slice2_rag  # noqa: E402


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    config = LLMConfig.from_vendors()
    try:
        llm_transport = RecordingLLMTransport(config, DEFAULT_LLM_FIXTURES_DIR)
    except LLMUnavailable as exc:
        print(f"녹화 불가(LLM): {exc}", file=sys.stderr)
        return 2

    rec_client = LLMClient(config=config, transport=llm_transport)
    judge = Judge(rec_client)

    # shared recording embedder (real local model2vec) — accumulates all vectors
    rec_embedder = CachedEmbedder(backend=Model2VecEmbedder(), record=True)

    def store_factory() -> ChromaVectorStore:
        return ChromaVectorStore(embedder=rec_embedder)

    cases = load_public_cases(2) + load_hidden_cases(2)
    print(
        f"recording slice② fixtures: embeddings(model={rec_embedder.model_name}) "
        f"+ LLM(model={config.model})"
    )
    results = slice2_rag.run_cases(
        cases, store_factory=store_factory, llm_client=rec_client, judge=judge
    )

    rec_embedder.save()
    print(f"saved {len(rec_embedder)} embeddings → tests/fixtures/embeddings/manifest.json")
    for r in results:
        m = r.metrics
        print(
            f"  {r.case_id}: total={r.total} recall={m.get('recall')} leak={m.get('leakage_count')} "
            f"entail={m.get('entailment')} judge={m.get('judge_scores')} "
            f"temporal_err={m.get('temporal_error')} measured={m.get('measured')}"
        )
    inp, outp = rec_client.total_tokens
    print(f"done. {len(rec_client.calls)} LLM calls ({inp} in / {outp} out, ~${rec_client.total_cost_usd:.4f}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
