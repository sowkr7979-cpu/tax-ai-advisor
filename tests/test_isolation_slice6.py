"""slice ⑥ 테넌트 격리 — 결정적 테스트(실키 불필요).

핵심: A사 검색이 B사 자료를 회수하면 누수=교차회수>0 → 하드게이트 0.
또한 하버스가 *실제로* 누수를 잡는지(정직성)를 일부러 깨진 store로 증명한다.
"""

from __future__ import annotations

import pytest

from contract.base import ConfidentialityLevel
from contract.cluster_i_eval import CorpusDoc, EvaluationCase, GoldQuery, Visibility
from src.isolation import IsolationError, TenantScope
from src.retrieval import IsolatedRetriever, count_cross_tenant_leakage
from src.vector_store import DeterministicVectorStore
from tiw.eval.runner import run_slice
from tiw.eval.slices.slice6_isolation import run_case


# --- SEC-002 격리필터 비활성 불가 --------------------------------------- #
def test_tenant_scope_requires_nonempty_key():
    with pytest.raises(IsolationError):
        TenantScope("")
    with pytest.raises(IsolationError):
        TenantScope("   ")


def test_search_signature_requires_scope():
    store = DeterministicVectorStore()
    # 타입 시스템상 scope 없이 호출 불가; 잘못된 타입도 거부
    with pytest.raises(IsolationError):
        store.search("client_A", "질의")  # type: ignore[arg-type]


# --- SEC-001 NULL 격리키 적재 거부 -------------------------------------- #
def test_null_key_client_material_rejected():
    store = DeterministicVectorStore()
    with pytest.raises(IsolationError):
        store.add("x", "고객 원장", ConfidentialityLevel.L3_CLIENT, client_id=None)


def test_shared_material_with_key_rejected():
    store = DeterministicVectorStore()
    with pytest.raises(IsolationError):
        store.add("x", "법령", ConfidentialityLevel.L0_PUBLIC, client_id="client_A")


# --- SEC-003 교차 테넌트 누수 0 + 공유 회수 허용 ------------------------- #
def _two_client_store() -> DeterministicVectorStore:
    store = DeterministicVectorStore()
    store.add("A-memo", "client_A 접대비 한도 손금불산입", ConfidentialityLevel.L3_CLIENT, "client_A")
    store.add("B-memo", "client_B 접대비 한도 손금불산입", ConfidentialityLevel.L3_CLIENT, "client_B")
    store.add("law25", "법인세법 제25조 접대비 손금불산입 한도", ConfidentialityLevel.L0_PUBLIC)
    return store


def test_no_cross_tenant_leakage_and_shared_allowed():
    retriever = IsolatedRetriever(_two_client_store())
    scope = TenantScope("client_A")
    hits = retriever.retrieve(scope, "접대비 한도 손금불산입", top_k=5)
    ids = {h.doc_id for h in hits}
    assert "B-memo" not in ids                      # 누수 0
    assert count_cross_tenant_leakage(scope, hits, ["B-memo"]) == 0
    assert "A-memo" in ids                          # 자기 자료 회수
    assert "law25" in ids                           # 공유 법령 회수 허용


def test_physical_partition_separation():
    store = _two_client_store()
    assert set(store.tenant_ids()) == {"client_A", "client_B"}
    assert store.shared_count() == 1


# --- 하버스 end-to-end (slice ⑥) ---------------------------------------- #
def test_slice6_harness_passes_gate():
    report = run_slice(6)
    assert report.case_results, "gold 케이스가 로드되어야 한다"
    assert report.hidden_count >= 1 and report.public_count >= 1
    assert not report.hard_gate_hit, f"하드게이트 위반: {report.case_results}"
    assert report.score >= 90, f"slice ⑥ 점수 {report.score} < 90"
    for r in report.case_results:
        assert r.metrics["leakage_count"] == 0


# --- 정직성: 깨진 store로 누수를 *실제로* 잡는지 검증 -------------------- #
class _LeakyStore(DeterministicVectorStore):
    """격리필터를 '깜빡한' 적대적 구현 — 모든 파티션을 뒤진다(테스트 전용)."""

    def _candidate_partitions(self, scope: TenantScope):  # type: ignore[override]
        parts = list(self._tenant_partitions.values())
        parts.append(self._shared_partition)
        return parts


def _leak_case() -> EvaluationCase:
    return EvaluationCase(
        case_id="S6-LEAKTEST",
        slice=6,
        visibility=Visibility.PUBLIC,
        adversarial=True,
        corpus=[
            CorpusDoc(doc_id="A1", confidentiality_level="L3_CLIENT", client_id="client_A",
                      text="client_A 접대비 한도 손금불산입"),
            CorpusDoc(doc_id="B1", confidentiality_level="L3_CLIENT", client_id="client_B",
                      text="client_B 접대비 한도 손금불산입"),
        ],
        queries=[
            GoldQuery(query_id="q1", as_client="client_A", text="접대비 한도 손금불산입",
                      gold_doc_ids=["A1"], forbidden_doc_ids=["B1"]),
        ],
        top_k=5,
    )


def test_harness_catches_leakage_with_broken_store():
    # 동일한 채점 경로로, 깨진 store는 반드시 누수로 적발되어 cap 0 이어야 한다.
    leaky = run_case(_leak_case(), store_factory=_LeakyStore)
    assert leaky.metrics["leakage_count"] > 0
    assert leaky.hard_gate_hit
    assert any(f.code == "TENANT_LEAK" for f in leaky.failure_modes)
    assert leaky.total == 0.0

    # 정상 store는 같은 케이스에서 누수 0 + 높은 점수.
    clean = run_case(_leak_case())
    assert clean.metrics["leakage_count"] == 0
    assert not clean.hard_gate_hit
    assert clean.total >= 90


# --- fail-closed: "측정 못 함 = 만점" 금지 (P0-1) ----------------------- #
class _ThrowingStore(DeterministicVectorStore):
    """retrieval(search) 중 예외를 던지는 적대적 엔진 — 측정 불가."""

    def search(self, scope, query, top_k=5):  # type: ignore[override]
        raise RuntimeError("retrieval engine down")


class _EmptyStore(DeterministicVectorStore):
    """검색이 항상 빈 결과 — retrieval 사실상 비활성(미실행과 동치)."""

    def search(self, scope, query, top_k=5):  # type: ignore[override]
        return []


def test_harness_fail_closed_on_retrieval_exception():
    # 동일 채점 경로: retrieval이 예외로 전혀 측정되지 않으면 만점이 아니라 실패.
    res = run_case(_leak_case(), store_factory=_ThrowingStore)
    assert res.metrics["completed"] is False
    assert res.metrics["retrieval_measured"] is False
    assert res.hard_gate_hit
    assert any(f.code == "NOT_REPRODUCIBLE" for f in res.failure_modes)
    assert res.total < 90  # 게이트(≥90) 통과 불가


def test_harness_fail_closed_on_empty_retrieval():
    # 빈 쿼리 결과(측정 신호 없음)도 만점이 아니라 fail-closed.
    res = run_case(_leak_case(), store_factory=_EmptyStore)
    assert res.metrics["retrieval_measured"] is False
    assert res.hard_gate_hit
    assert any(f.code == "NOT_REPRODUCIBLE" for f in res.failure_modes)
    assert res.total < 90


def test_broken_retrieval_breaks_slice_gate():
    # 깨진 엔진이 동일 슬라이스 집계에 들어가면 슬라이스가 게이트를 통과하지 못한다.
    broken = run_case(_leak_case(), store_factory=_ThrowingStore)
    assert broken.hard_gate_hit and broken.total < 90
