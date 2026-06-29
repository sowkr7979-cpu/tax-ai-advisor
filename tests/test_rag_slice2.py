"""slice ② citation 검증 RAG — 결정적 테스트 (실키/torch/모델 없이 fixture 재생).

핵심:
  - 구조 인지 청킹(RAG-002/017): 법령을 조/항/호/목으로 분할 + source_locator·시점 메타.
  - Chroma 실 wiring(SEC-003): 테넌트별 collection 물리 격리 — A 질의가 B 청크 회수 0.
  - 시점 유효성 필터(RAG-005): as-of 가 시행일 버전을 검색공간에서 가른다.
  - citation entailment(HALU-003): 회수된 조문이 claim 을 지지(2/2 결정적).
  - RetrievalRun 재현성(RAG-013): tenant_scope·as_of·후보·채택 로깅.
  - 하버스 정직성(anti-gaming): 누수 store→TENANT_LEAK, 날조→FABRICATED, 시점불일치→
    TEMPORAL_ERROR, 임베딩 fixture 부재→NOT_REPRODUCIBLE 를 *동일 채점 경로*에서 적발.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from contract.base import ConfidentialityLevel, IndexScope, SourceType
from contract.cluster_f_qa import Citation
from contract.cluster_i_eval import EvaluationCase
from src.ai.chroma_backend import ChromaVectorStore
from src.ai.embedding_client import (
    CachedEmbedder,
    DeterministicFakeEmbedder,
    EmbeddingNotReproducible,
    EmbeddingUnavailable,
    default_rag_embedder,
)
from src.chunking import chunk_client_doc, chunk_provision
from src.internal_rag import InternalRagIndex
from src.isolation import IsolationError, TenantScope
from tiw.eval.loader import load_hidden_cases, load_public_cases
from tiw.eval.runner import run_slice
from tiw.eval.slices.slice2_rag import _recall_targets, _retrieval_entailment, run_case


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _fake_store_factory():
    """Record-mode CachedEmbedder over the fake embedder → exercises the FULL
    Chroma/isolation path without model2vec (plumbing-only tests)."""
    import tempfile

    def factory():
        emb = CachedEmbedder(fixtures_dir=tempfile.mkdtemp(),
                             backend=DeterministicFakeEmbedder(), record=True)
        return ChromaVectorStore(embedder=emb)

    return factory


def _fake_index() -> InternalRagIndex:
    return InternalRagIndex(_fake_store_factory()())


def _case(slice_no: int, case_id: str) -> EvaluationCase:
    for c in load_public_cases(slice_no) + load_hidden_cases(slice_no):
        if c.case_id == case_id:
            return c
    raise AssertionError(f"{case_id} not found")


# --------------------------------------------------------------------------- #
# ③ 구조 인지 청킹 (RAG-002/015/017)
# --------------------------------------------------------------------------- #
def test_chunk_provision_structure_and_metadata():
    cs = chunk_provision("법인세법", "제25조", 2024, doc_id="law25-2024", tax_type="법인세")
    p = cs.parent
    assert p.is_law and p.is_parent
    assert p.article_label == "제25조" and "기업업무추진비" in (p.article_title or "")
    assert p.effective_from == date(2024, 1, 1)
    assert "제25조" in (p.source_locator or "")           # pinpoint (RAG-017)
    assert p.content_hash and len(p.content_hash) == 64
    assert p.confidentiality_level is ConfidentialityLevel.L0_PUBLIC and p.client_id is None
    # children carry 항 pinpoint locators + inherit version metadata
    assert cs.children, "조문은 항 단위 자식 청크로 분할되어야 한다"
    for ch in cs.children:
        assert ch.parent_id == p.chunk_id
        assert "제25조" in (ch.source_locator or "") and "항" in (ch.source_locator or "")
        assert ch.effective_from == p.effective_from
    # contract Chunk validates (RAG-002/017 + SEC-003: shared chunk carries no client_id)
    contract_chunk = p.to_contract_chunk()
    assert contract_chunk.source_locator and contract_chunk.client_id is None


def test_chunk_versions_have_distinct_text_and_titles():
    v24 = chunk_provision("법인세법", "제25조", 2024).parent
    v20 = chunk_provision("법인세법", "제25조", 2020).parent
    assert "기업업무추진비" in (v24.article_title or "")
    assert "접대비" in (v20.article_title or "")
    assert v24.content_hash != v20.content_hash      # 다른 시행일 버전 = 다른 해시


def test_client_chunk_routes_and_validates():
    ch = chunk_client_doc(doc_id="A-1", text="client_A 원장", client_id="client_A",
                          confidentiality_level=ConfidentialityLevel.L3_CLIENT, doc_type="재무")
    assert ch.client_id == "client_A" and ch.parent_id is None
    assert ch.to_contract_chunk().client_id == "client_A"   # SEC-001 키 전파


# --------------------------------------------------------------------------- #
# ⑥ Chroma 물리 격리 (SEC-003 / RAG-007)
# --------------------------------------------------------------------------- #
def _two_client_index() -> InternalRagIndex:
    idx = _fake_index()
    chunks = []
    for lid, art, yr in [("law25-2024", "제25조", 2024)]:
        chunks += chunk_provision("법인세법", art, yr, doc_id=lid).all_chunks
    chunks.append(chunk_client_doc(doc_id="A-memo", text="client_A 기업업무추진비 한도 손금불산입",
                                   client_id="client_A", confidentiality_level=ConfidentialityLevel.L3_CLIENT))
    chunks.append(chunk_client_doc(doc_id="B-memo", text="client_B 기업업무추진비 한도 손금불산입",
                                   client_id="client_B", confidentiality_level=ConfidentialityLevel.L3_CLIENT))
    idx.ingest(chunks)
    return idx


def test_chroma_physical_separation_no_leak_shared_allowed():
    idx = _two_client_index()
    assert set(idx.store.tenant_ids()) == {"client_A", "client_B"}
    hits, _ = idx.retrieve(TenantScope("client_A"), "기업업무추진비 한도 손금불산입", date(2024, 1, 1), top_k=5)
    ids = {h.chunk_id for h in hits}
    assert "B-memo" not in ids                          # 누수 0 (물리 격리)
    assert "A-memo" in ids and "law25-2024" in ids      # 자기자료 + 공유 법령
    assert idx.leakage(TenantScope("client_A"), hits, ["B-memo"]) == 0


def test_chroma_search_requires_scope():
    store = ChromaVectorStore(embedder=CachedEmbedder(backend=DeterministicFakeEmbedder(), record=True))
    with pytest.raises(IsolationError):
        store.search("client_A", "q")  # type: ignore[arg-type]


def test_chroma_null_key_client_material_rejected():
    store = ChromaVectorStore(embedder=CachedEmbedder(backend=DeterministicFakeEmbedder(), record=True))
    with pytest.raises(IsolationError):
        store.add("x", "고객 원장", ConfidentialityLevel.L3_CLIENT, client_id=None)
    with pytest.raises(IsolationError):  # SEC-003: shared must not carry a key
        store.add("y", "법령", ConfidentialityLevel.L0_PUBLIC, client_id="client_A")


# --------------------------------------------------------------------------- #
# ⑤ 시점 유효성 필터 (RAG-005) — 검색공간 자체 제한
# --------------------------------------------------------------------------- #
def test_temporal_filter_selects_version_in_force():
    idx = _fake_index()
    chunks = []
    for lid, yr in [("law25-2024", 2024), ("law25-2020", 2020)]:
        chunks += chunk_provision("법인세법", "제25조", yr, doc_id=lid).all_chunks
    idx.ingest(chunks)
    h24, _ = idx.retrieve(TenantScope("client_A"), "기업업무추진비 손금불산입", date(2024, 1, 1), top_k=5)
    h20, _ = idx.retrieve(TenantScope("client_A"), "접대비 손금불산입", date(2020, 1, 1), top_k=5)
    ids24 = {h.chunk_id for h in h24}
    ids20 = {h.chunk_id for h in h20}
    assert "law25-2024" in ids24 and "law25-2020" not in ids24   # 2024 시점: 2020 버전 배제
    assert "law25-2020" in ids20 and "law25-2024" not in ids20   # 2020 시점: 2024 버전 배제


# --------------------------------------------------------------------------- #
# 하버스 end-to-end (slice ②) — judge 채점 + ≥90
# --------------------------------------------------------------------------- #
def test_slice2_harness_passes_gate():
    report = run_slice(2)
    assert report.case_results
    assert report.hidden_count >= 1 and report.public_count >= 1
    assert not report.hard_gate_hit
    assert report.pending is False
    assert report.passed is True
    assert report.score >= 90
    for r in report.case_results:
        assert r.metrics["recall"] == 1.0
        assert r.metrics["leakage_count"] == 0
        assert r.metrics["reproducible"] is True
        assert r.metrics["judge_scored"] is True
        assert r.metrics["entailment"] == "2/2"
        assert r.metrics["temporal_error"] is False
        scored = {s.dimension for s in r.dimension_scores if s.applicable and s.score is not None}
        assert {"legal_reasoning", "issue_spotting", "risk", "output", "security", "search"} <= scored


def test_slice2_retrieval_run_logged_for_reproducibility():
    idx = _two_client_index()
    hits, cands = idx.retrieve(TenantScope("client_A"), "기업업무추진비 손금불산입", date(2024, 1, 1), top_k=5)
    # RetrievalRun is built inside index.answer; here assert the candidate/selected
    # lineage exists (RAG-013): selected ⊆ candidates, candidates non-empty.
    assert cands and all(h.chunk_id in cands for h in hits)


# --------------------------------------------------------------------------- #
# 정직성: 누수 store → TENANT_LEAK (cap 0)
# --------------------------------------------------------------------------- #
class _LeakyChromaStore(ChromaVectorStore):
    """격리필터를 '깜빡한' 적대적 구현 — 모든 테넌트 collection 을 뒤진다(테스트 전용)."""

    def _candidate_collections(self, scope: TenantScope):  # type: ignore[override]
        cols = []
        for c in self._client.list_collections():
            if c.name.startswith(self._tenant_prefix) or c.name == self._shared_name:
                cols.append(c)
        return cols


def test_harness_catches_leakage_with_broken_store():
    case = _case(2, "S2-PUB-001")

    def leaky_factory():
        emb = CachedEmbedder(backend=DeterministicFakeEmbedder(), record=True)
        return _LeakyChromaStore(embedder=emb)

    res = run_case(case, store_factory=leaky_factory)
    assert res.metrics["leakage_count"] > 0
    assert any(f.code == "TENANT_LEAK" for f in res.failure_modes)
    assert res.total == 0.0


# --------------------------------------------------------------------------- #
# 정직성: 날조 인용 → FABRICATED_CITATION (cap 60)
# --------------------------------------------------------------------------- #
def test_harness_catches_fabricated_citation():
    case = _case(2, "S2-PUB-001")

    def tamper(cit: Citation) -> Citation:
        return cit.model_copy(update={"source_object_id": "pv_날조_제000조_19000101"})

    res = run_case(case, citation_tamper=tamper)
    assert res.metrics["fabricated_citation"] is True
    assert any(f.code == "FABRICATED_CITATION" for f in res.failure_modes)
    assert res.total <= 60


# --------------------------------------------------------------------------- #
# 정직성: 시행일/버전 불일치 → TEMPORAL_ERROR (cap 55)
# --------------------------------------------------------------------------- #
def test_harness_catches_temporal_mismatch():
    # gold 가 2020 버전을 기대하도록 변조하면, 회수된 2024 버전과 시행일 불일치 → 적발.
    case = _case(2, "S2-PUB-001").model_copy(deep=True)
    case.rag_queries[0].gold_law.expected_effective_from = date(2020, 1, 1)
    res = run_case(case)
    assert res.metrics["temporal_error"] is True
    assert any(f.code == "TEMPORAL_ERROR" for f in res.failure_modes)
    assert res.total <= 55


# --------------------------------------------------------------------------- #
# fail-closed: 임베딩 fixture 부재/변조 → NOT_REPRODUCIBLE / 예외 (만점 아님)
# --------------------------------------------------------------------------- #
def test_harness_fail_closed_on_missing_embeddings(tmp_path):
    case = _case(2, "S2-PUB-001")

    def empty_factory():
        emb = CachedEmbedder(fixtures_dir=tmp_path, record=False)   # 빈 캐시 → embed 시 fail-closed
        return ChromaVectorStore(embedder=emb)

    res = run_case(case, store_factory=empty_factory)
    assert res.metrics["measured"] is False
    assert any(f.code == "NOT_REPRODUCIBLE" for f in res.failure_modes)
    assert res.total < 90


class _MissingFixtureJudge:
    """Simulates a MISSING/TAMPERED judge fixture (replay transport raises)."""

    def score(self, **kwargs):
        from src.ai.llm_client import LLMUnavailable

        raise LLMUnavailable("no recorded judge fixture (test)")


def test_harness_fail_closed_on_missing_judge_fixture():
    # codex P1: a missing judge fixture must trip NOT_REPRODUCIBLE (a hard gate),
    # NOT leave the judge dimension as a silently-absent score that could pass.
    case = _case(2, "S2-PUB-001")
    res = run_case(case, judge=_MissingFixtureJudge())
    assert res.metrics["measured"] is False
    assert res.metrics["judge_scored"] is False
    assert any(f.code == "NOT_REPRODUCIBLE" for f in res.failure_modes)
    assert res.total < 90


def test_embedding_cache_tamper_fails_closed(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"model": "m", "dimension": 2, "vectors": {"k": [0.1, 0.2]},
                    "content_hash": "DEADBEEF"}),
        encoding="utf-8",
    )
    with pytest.raises(EmbeddingNotReproducible):
        CachedEmbedder(fixtures_dir=tmp_path, record=False)


def test_replay_embedder_missing_text_is_fail_closed():
    emb = default_rag_embedder()   # 녹화된 캐시
    with pytest.raises(EmbeddingUnavailable):
        emb.embed("녹화되지 않은 임의의 문장 — fixture 부재")


# --------------------------------------------------------------------------- #
# 정직성: 비지지 entailment → FABRICATED_CITATION
# --------------------------------------------------------------------------- #
class _UnsupportedJudge:
    def score(self, **kwargs):
        from src.judge import EntailmentCheck, JudgeVerdict

        return JudgeVerdict(
            fractions={"legal_reasoning": 1.0, "issue_spotting": 1.0, "risk": 1.0, "output": 1.0},
            entailments=[EntailmentCheck(claim="c", supported=False, rationale="비지지")],
        )


def test_harness_unsupported_entailment_trips_fabricated_gate():
    case = _case(2, "S2-PUB-001")
    res = run_case(case, judge=_UnsupportedJudge())
    assert res.metrics["fabricated_citation"] is True
    assert any(f.code == "FABRICATED_CITATION" for f in res.failure_modes)
    assert res.total <= 60


# --------------------------------------------------------------------------- #
# 정직성: high-risk 검토경고 — hidden 케이스는 고위험(경고 필수)
# --------------------------------------------------------------------------- #
def test_hidden_case_is_high_risk_and_carries_warning():
    hid = _case(2, "S2-HID-001")
    assert hid.rag_queries[0].high_risk is True
    res = run_case(hid)
    assert res.metrics["missing_review_warning"] is False   # 경고가 실제로 붙음
    assert not any(f.code == "MISSING_REVIEW_WARNING" for f in res.failure_modes)


# --------------------------------------------------------------------------- #
# anti-gaming: public/hidden 분리 + 서로 다른 조문(overfit 방지)
# --------------------------------------------------------------------------- #
def test_public_hidden_separate_and_distinct_articles():
    pub = load_public_cases(2)
    hid = load_hidden_cases(2)
    assert {c.case_id for c in pub} == {"S2-PUB-001", "S2-PUB-002"}
    assert {c.case_id for c in hid} == {"S2-HID-001"}
    pub_articles = {q.gold_law.article_label for c in pub for q in c.rag_queries}
    hid_articles = {q.gold_law.article_label for c in hid for q in c.rag_queries}
    assert hid_articles and not (hid_articles & pub_articles)   # 숨김셋은 공개셋과 다른 조문
    for c in pub + hid:
        for q in c.rag_queries:
            assert len(q.gold_issues) >= 4


def test_answer_channel_is_internal_rag():
    # 채널 ② INTERNAL_RAG 로 표기되는지(법령MCP ①과 구분) — 회수→인용근거 답변.
    # 녹화된 PUB-001 질문/조문을 사용해 생성 fixture 가 재생되도록 한다(키 0).
    case = _case(2, "S2-PUB-001")
    q = case.rag_queries[0]
    idx = _two_client_index()
    rag = idx.answer(
        question_text=q.question_text,
        scope=TenantScope("client_A"), as_of=q.as_of_date, basis_kind=q.basis_kind,
        source_answer_id=f"sa_{case.case_id}_{q.query_id}",
        answer_run_id=f"ar_{case.case_id}_{q.query_id}",
        run_id=f"rr_{case.case_id}_{q.query_id}",
        top_k=5,
    )
    assert rag.grounded and rag.answer is not None
    assert rag.answer.source_answer.source_type is SourceType.INTERNAL_RAG
    assert rag.answer.source_answer.retrieval_run_id == rag.retrieval_run.run_id


# --------------------------------------------------------------------------- #
# codex P1-1: recall 분모 dedupe — 동일 law parent 가 gold/shared 양쪽에 있어도 1회만
# --------------------------------------------------------------------------- #
def test_recall_targets_dedupe_no_double_count():
    q = _case(2, "S2-PUB-001").rag_queries[0]
    # gold 가 동일 law id 를 gold_chunk_ids + expect_shared 양쪽에 싣고 있음(중복 원인)
    raw = list(q.gold_chunk_ids) + list(q.expect_shared)
    assert len(raw) > len(set(raw)), "이 회귀 테스트는 gold 에 중복 law id 가 있어야 의미가 있다"
    assert "law25-2024" in q.gold_chunk_ids and "law25-2024" in q.expect_shared
    # dedupe 된 recall 대상은 회수 UNIT 당 정확히 1회 — 분모가 부풀지 않는다
    targets = _recall_targets(q)
    assert targets == {"law25-2024", "A-memo"}
    assert len(targets) == 2 and len(raw) == 3        # 3(중복)→2(정직한 분모)


def test_recall_dedupe_partial_miss_not_inflated():
    # law parent 를 놓치고 memo 만 회수하면 정직한 recall = 1/2(0.5),
    # 중복집계였다면 1/3(≈0.33)로 분모가 부풀었을 것.
    q = _case(2, "S2-PUB-001").rag_queries[0]
    targets = _recall_targets(q)
    selected = {"A-memo"}                              # law25-2024 회수 실패 가정
    hits = sum(1 for t in targets if t in selected)
    assert hits == 1 and len(targets) == 2
    assert hits / len(targets) == 0.5                  # not 1/3


# --------------------------------------------------------------------------- #
# codex P1-2: 회수집합 기준 결정적 entailment (회수 밖/미지지 → 적발)
# --------------------------------------------------------------------------- #
from types import SimpleNamespace as _NS  # noqa: E402

_PROV = (
    "제25조(기업업무추진비의 손금불산입) ① 내국법인이 한 사업연도에 지출한 "
    "기업업무추진비로서 일정 한도를 초과하는 금액은 손금에 산입하지 아니한다."
)
_QUOTE = "기업업무추진비로서 일정 한도를 초과하는 금액은 손금에 산입하지 아니한다"


def _ret(cid: str, text: str):
    return _NS(chunk_id=cid, chunk=_NS(text=text))


def test_retrieval_entailment_supported_when_in_set_and_anchored():
    claims = [_NS(proposition="법인세법 제25조(기업업무추진비) 한도 초과액은 손금불산입한다")]
    cits = [_NS(quote=_QUOTE)]
    retrieved = [_ret("law25-2024", _PROV), _ret("A-memo", "client_A 메모")]
    supported, total = _retrieval_entailment(claims, cits, ["law25-2024", "A-memo"], retrieved)
    assert (supported, total) == (1, 1)


def test_retrieval_entailment_citation_outside_retrieval_set_unsupported():
    # 인용이 가리키는 조문 chunk 가 회수(selected) 집합 밖이면 미지지(결정적).
    claims = [_NS(proposition="법인세법 제25조(기업업무추진비) 한도 초과액은 손금불산입한다")]
    cits = [_NS(quote=_QUOTE)]
    retrieved = [_ret("law25-2024", _PROV), _ret("A-memo", "client_A 메모")]
    # 동일 텍스트가 retrieved 에 있어도 selected 에 없으면 회수 밖 → 미지지
    supported, total = _retrieval_entailment(claims, cits, ["A-memo"], retrieved)
    assert (supported, total) == (0, 1)


def test_retrieval_entailment_retrieved_chunk_does_not_support_claim():
    # 회수 chunk 안에 인용 발췌는 있으나 claim 의 조문참조(제999조)가 본문에 없음 → 미지지.
    claims = [_NS(proposition="법인세법 제999조에 따라 기업업무추진비 한도 초과액은 손금불산입한다")]
    cits = [_NS(quote=_QUOTE)]
    retrieved = [_ret("law25-2024", _PROV)]
    supported, total = _retrieval_entailment(claims, cits, ["law25-2024"], retrieved)
    assert (supported, total) == (0, 1)


def test_harness_catches_citation_grounded_outside_retrieval_set():
    # 라이브 채점 경로: 인용 발췌를 회수집합에 없는 문구로 변조하면 retrieval-anchored
    # entailment 가 미지지로 적발 → FABRICATED_CITATION (cap 60). (source_object_id 는
    # 그대로라 레지스트리 존재검증은 통과 — 오직 회수↔claim 직접검증이 잡는다.)
    case = _case(2, "S2-PUB-001")

    def tamper(cit: Citation) -> Citation:
        return cit.model_copy(update={"quote": "회수 집합에 존재하지 않는 날조 인용 문구 ZZZ"})

    res = run_case(case, citation_tamper=tamper)
    assert res.metrics["retrieval_entailment"] == "0/2"
    assert res.metrics["fabricated_citation"] is True
    assert any(f.code == "FABRICATED_CITATION" for f in res.failure_modes)
    assert res.total <= 60
