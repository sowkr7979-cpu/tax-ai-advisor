"""tests/test_rag_db_index.py — 내부 RAG DB numpy 코사인 인덱스 단위 검증.

실제 10k 청크 인덱스는 런타임 데이터(gitignore)이므로, 합성 코퍼스 + 결정적 fake 임베더로
핵심 로직(저장·복원·회수·fail-closed 가드)을 검증한다(PDF·model2vec 불필요).
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

import src.rag_db_index as ragdb
from src.ai.embedding_client import DeterministicFakeEmbedder

_DIM = 64
_DOCS = [
    "수입배당금 익금불산입 출자비율 보유기간 요건",
    "가업승계 증여세 과세특례 사후관리 추징",
    "통합투자세액공제 적격 투자자산 기본공제 추가공제",
    "기업업무추진비 접대비 한도 적격증빙",
]


def _emb() -> DeterministicFakeEmbedder:
    return DeterministicFakeEmbedder(dimension=_DIM)


def _build_manual(d, texts, emb, *, dim=_DIM, model=None, with_hash=True):
    """build_index 출력과 동일한 형태(사이드카·벡터·매니페스트 + content hash)를 손으로 구성."""
    d.mkdir(parents=True, exist_ok=True)
    sidecar = d / "chunks.jsonl"
    vectors = d / "vectors.npy"
    manifest = d / "manifest.json"
    mat = np.zeros((len(texts), dim), dtype="float32")
    with sidecar.open("w", encoding="utf-8") as fh:
        for i, t in enumerate(texts):
            mat[i] = np.asarray(emb.embed(t), dtype="float32")
            fh.write(json.dumps({
                "chunk_id": f"c{i}", "text": t, "doc_type": "실무가이드",
                "source_locator": f"가이드 p.{i + 1}", "tax_type": "법인세",
            }, ensure_ascii=False) + "\n")
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    mat = (mat / norms).astype("float32")
    np.save(vectors, mat)
    stats = {
        "model": model or emb.model_name, "dimension": dim, "chunks": len(texts),
        "backend": "numpy-cosine",
    }
    if with_hash:
        stats["sidecar_sha256"] = hashlib.sha256(sidecar.read_bytes()).hexdigest()
        stats["vectors_sha256"] = hashlib.sha256(vectors.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(stats, ensure_ascii=False), encoding="utf-8")
    return sidecar, vectors, manifest


def _load(d, emb):
    return ragdb.load_index(sidecar=d / "chunks.jsonl", vectors_path=d / "vectors.npy",
                            manifest=d / "manifest.json", embedder=emb)


def test_roundtrip_and_relevant_topk(tmp_path):
    emb = _emb()
    _build_manual(tmp_path, _DOCS, emb)
    store = _load(tmp_path, emb)
    assert store.vectors.shape == (len(_DOCS), _DIM)
    res = ragdb.query_rag_db(store, "수입배당금 익금불산입 요건", top_k=2)
    assert res.grounded and len(res.passages) == 2
    # 가장 관련 있는 문서(수입배당금)가 1위 + 출처 보존
    assert "수입배당금" in res.passages[0].text
    assert res.passages[0].source == "가이드 p.1"
    assert res.passages[0].rank == 1


def test_search_rejects_nonpositive_top_k(tmp_path):
    emb = _emb()
    _build_manual(tmp_path, _DOCS, emb)
    store = _load(tmp_path, emb)
    assert store.search("x", top_k=0) == []
    assert store.search("x", top_k=-1) == []
    # top_k > N 도 N 개로 안전 클램프
    assert len(store.search("수입배당금", top_k=99)) == len(_DOCS)


def test_failclosed_missing_manifest(tmp_path):
    emb = _emb()
    _build_manual(tmp_path, _DOCS, emb)
    (tmp_path / "manifest.json").unlink()
    with pytest.raises(FileNotFoundError):
        _load(tmp_path, emb)


def test_failclosed_dimension_mismatch(tmp_path):
    _build_manual(tmp_path, _DOCS, _emb(), dim=_DIM)
    with pytest.raises(RuntimeError):
        _load(tmp_path, DeterministicFakeEmbedder(dimension=32))  # 차원 다른 임베더


def test_failclosed_model_mismatch(tmp_path):
    emb = _emb()
    _build_manual(tmp_path, _DOCS, emb, model="some-other-model")
    with pytest.raises(RuntimeError):
        _load(tmp_path, emb)


def test_failclosed_hash_mismatch_on_tamper(tmp_path):
    emb = _emb()
    sidecar, _, _ = _build_manual(tmp_path, _DOCS, emb)
    # 해시 계산 후 사이드카를 변조 → 부분 덮어쓰기/손상 탐지
    with sidecar.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"chunk_id": "x", "text": "변조"}, ensure_ascii=False) + "\n")
    with pytest.raises(RuntimeError):
        _load(tmp_path, emb)


def test_failclosed_row_count_mismatch(tmp_path):
    emb = _emb()
    sidecar, vectors, manifest = _build_manual(tmp_path, _DOCS, emb, with_hash=False)
    # 벡터 행을 1개 줄여 사이드카(4)와 불일치 → fail-closed(해시 없는 구버전 경로의 폴백 검증)
    mat = np.load(vectors)[:-1]
    np.save(vectors, mat)
    with pytest.raises(RuntimeError):
        _load(tmp_path, emb)


def test_close_index_is_noop():
    # numpy 백엔드는 닫을 OS 핸들이 없다 — None/임의 객체에도 안전
    ragdb.close_index(None)
    ragdb.close_index(object())
