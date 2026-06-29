"""tiw/eval/slices/slice6_isolation.py — slice ⑥ harness (tenant isolation).

Drives the DETERMINISTIC engine (src/isolation, src/vector_store, src/retrieval)
against the gold cases and computes the rubric dimensions it actually exercises:
  - security (14): cross-tenant leakage = 0, NULL-key rejection, SHARED⟂TENANT routing
  - search   (9): intra-tenant recall + SHARED reference recall
  - requirement (6): mandatory scope, guard, routing, retrieval all functional
  - ops      (2): runs complete without unexpected errors

Hard gate: any cross-tenant retrieval (leakage>0) → TENANT_LEAK (cap 0).

`store_factory` is injectable ONLY so an adversarial test can feed a deliberately
leaky store through this SAME scoring path and prove the harness CATCHES leakage
(anti-gaming evidence). Production code never overrides it.
"""

from __future__ import annotations

from statistics import mean
from typing import Callable, Optional

from contract.base import ConfidentialityLevel
from contract.cluster_i_eval import EvaluationCase, RubricResult, TargetKind, Visibility
from src.isolation import IsolationError, TenantScope
from src.retrieval import IsolatedRetriever, count_cross_tenant_leakage
from src.vector_store import DeterministicVectorStore
from tiw.eval.scorer import build_rubric_result

StoreFactory = Callable[[], DeterministicVectorStore]

SLICE_NO = 6


def _safe_mean(values: list[float], default: float = 1.0) -> float:
    return mean(values) if values else default


def run_case(case: EvaluationCase, store_factory: Optional[StoreFactory] = None) -> RubricResult:
    store = (store_factory or DeterministicVectorStore)()

    # -- ingestion (SEC-001 NULL-key rejection + SEC-003 routing) ---------- #
    reject_total = reject_correct = 0
    unexpected_ingest_errors = 0
    expected_shared_ids: set[str] = set()
    expected_tenants: set[str] = set()

    for doc in case.corpus:
        level = ConfidentialityLevel(doc.confidentiality_level)
        if doc.expect_reject:
            reject_total += 1
            try:
                store.add(doc.doc_id, doc.text, level, doc.client_id)
            except IsolationError:
                reject_correct += 1  # correctly refused (NULL/inconsistent isolation key)
            # else: guard FAILED to reject — reflected in security/requirement dims
            continue
        # valid doc: record where it SHOULD land, then ingest
        if level.is_client_scoped:
            expected_tenants.add(doc.client_id or "")
        else:
            expected_shared_ids.add(doc.doc_id)
        try:
            store.add(doc.doc_id, doc.text, level, doc.client_id)
        except IsolationError:
            unexpected_ingest_errors += 1

    routing_ok = (
        store.shared_count() == len(expected_shared_ids)
        and set(store.tenant_ids()) == expected_tenants
    )

    # -- retrieval (SEC-002 mandatory scope + SEC-003 no cross-tenant) ----- #
    retriever = IsolatedRetriever(store)
    total_leak = 0
    recall_hits = recall_total = 0
    shared_hits = shared_total = 0
    queries_executed = 0
    empty_query_results = False
    completed = True
    try:
        for q in case.queries:
            scope = TenantScope(q.as_client)
            hits = retriever.retrieve(scope, q.text, top_k=case.top_k)
            queries_executed += 1
            if not hits:
                empty_query_results = True  # retrieval produced NO signal for this query
            total_leak += count_cross_tenant_leakage(scope, hits, q.forbidden_doc_ids)
            ids = {h.doc_id for h in hits}
            for gold in q.gold_doc_ids:
                recall_total += 1
                recall_hits += int(gold in ids)
            for shared in q.expect_shared:
                shared_total += 1
                shared_hits += int(shared in ids)
    except Exception:  # noqa: BLE001 — a crash is an ops failure, not a silent pass
        completed = False

    # FAIL-CLOSED (docs/09 §2, NFR-007/SEC-007): retrieval must actually RUN and
    # yield signal, otherwise the leak/recall/shared denominators are 0 and would
    # silently default to "perfect" — i.e. "측정 못 함 = 만점". A crash, an
    # unexecuted/empty query set, or an empty hit-list means isolation could not be
    # PROVEN, so we refuse to credit it and trip a hard gate below.
    retrieval_measured = (
        completed
        and queries_executed == len(case.queries)
        and queries_executed > 0
        and not empty_query_results
    )

    # -- dimension fractions (0..1) --------------------------------------- #
    no_leak = 1.0 if total_leak == 0 else 0.0
    null_rejection = (reject_correct / reject_total) if reject_total else 1.0
    routing_frac = 1.0 if routing_ok else 0.0
    filter_mandatory = 1.0  # structural: TenantScope is a required arg (SEC-002)
    recall_frac = (recall_hits / recall_total) if recall_total else 1.0
    shared_frac = (shared_hits / shared_total) if shared_total else 1.0

    if not retrieval_measured:
        # unmeasured retrieval earns NO isolation/search credit (fail-closed)
        no_leak = 0.0
        recall_frac = 0.0
        shared_frac = 0.0

    security_frac = _safe_mean([no_leak, null_rejection, routing_frac, filter_mandatory])
    search_frac = _safe_mean([recall_frac, shared_frac])
    requirement_frac = _safe_mean(
        [filter_mandatory, null_rejection, routing_frac, 1.0 if recall_frac > 0 else 0.0]
    )
    ops_frac = 1.0 if (completed and unexpected_ingest_errors == 0) else 0.0

    # -- hard gates ------------------------------------------------------- #
    hard_gate_codes: list[str] = []
    if total_leak > 0:
        hard_gate_codes.append("TENANT_LEAK")  # SEC-003 누수 → cap 0
    if not retrieval_measured:
        # 측정 불가(예외/미실행/빈 결과) → 재현 불가로 간주, cap 75 (게이트 통과 금지)
        hard_gate_codes.append("NOT_REPRODUCIBLE")  # NFR-007/SEC-007

    metrics = {
        "leakage_count": total_leak,
        "recall": round(recall_frac, 3),
        "shared_recall": round(shared_frac, 3),
        "null_key_rejected": f"{reject_correct}/{reject_total}",
        "routing_ok": routing_ok,
        "completed": completed,
        "retrieval_measured": retrieval_measured,
        "queries_executed": queries_executed,
        "tenants": store.tenant_ids(),
        "shared_docs": store.shared_count(),
    }

    return build_rubric_result(
        case_id=case.case_id,
        slice_no=SLICE_NO,
        target_id=case.case_id,
        visibility=case.visibility,
        target_kind=TargetKind.SLICE,
        dim_fractions={
            "security": security_frac,
            "search": search_frac,
            "requirement": requirement_frac,
            "ops": ops_frac,
        },
        dim_details={
            "security": f"leak={total_leak} null_rej={reject_correct}/{reject_total} "
            f"routing_ok={routing_ok}",
            "search": f"recall={recall_frac:.2f} shared_recall={shared_frac:.2f}",
            "requirement": f"scope_mandatory routing_ok={routing_ok}",
            "ops": f"completed={completed} measured={retrieval_measured} "
            f"ingest_errors={unexpected_ingest_errors}",
        },
        hard_gate_codes=hard_gate_codes,
        metrics=metrics,
    )


def run_cases(cases: list[EvaluationCase], store_factory: Optional[StoreFactory] = None) -> list[RubricResult]:
    return [run_case(c, store_factory=store_factory) for c in cases]
