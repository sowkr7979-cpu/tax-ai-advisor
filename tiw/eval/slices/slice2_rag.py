"""tiw/eval/slices/slice2_rag.py — slice ② harness (citation 검증된 RAG 답변).

Drives the channel-② internal-RAG pipeline (src.internal_rag) against the gold
cases and scores the dimensions it actually exercises:

  DETERMINISTIC:
    - search (9)      : recall@k — gold 청크(조문 parent + 고객 메모)/공유 회수
    - citation (12)   : grounding(존재·버전·pinpoint·시점) + (judge) entailment
    - requirement (6) : RetrievalRun(tenant_scope·as_of 포함) + 답변 + applicable_basis
    - security (14)   : **교차 테넌트 누수=0**(고객자료 RAG) + scope 필수 + 라우팅 + NULL거부
    - ops (2)         : 재현성(임베딩/조문 해시 replay + RetrievalRun 재구성)

  JUDGE (reused from slice ①):
    - legal_reasoning (20) · issue_spotting (10) · risk (11) · output (9) + entailment

  N/A: conflict (7) — cross-source 종합은 slice ④.

HARD GATES (docs/09 §2):
  - TENANT_LEAK (0)        : 고객 RAG에서 타사 청크 회수 → cap 0 (SEC-003)
  - FABRICATED_CITATION(60): 인용이 등록 소스객체로 해석 안 됨 OR entailment 미지지
  - TEMPORAL_ERROR (55)    : grounding 조문의 시행일이 gold 와 불일치(잘못된 버전 회수)
  - NOT_REPRODUCIBLE (75)  : 임베딩/조문 해시 replay 실패·grounding 실패·예외 → fail-closed
  - MISSING_REVIEW_WARNING(60): high-risk 질의에 회계사 검토경고 누락

`store_factory` / `citation_tamper` / `llm_client` / `judge` are injectable ONLY so
adversarial tests can feed a leaky store, a tampered citation, an empty-fixture
client, or a fake judge through this SAME path and prove the harness CATCHES it.
"""

from __future__ import annotations

from hashlib import sha256
from statistics import mean
from typing import Callable, Optional

from contract.base import ConfidentialityLevel, SourceKind
from contract.cluster_d_provenance import ProvisionVersion
from contract.cluster_f_qa import Citation
from contract.cluster_i_eval import EvaluationCase, RagQuery, RubricResult, TargetKind
from rules.hard_gates import DIMENSION_WEIGHTS
from src.ai.chroma_backend import ChromaVectorStore
from src.ai.embedding_client import EmbeddingNotReproducible, EmbeddingUnavailable, default_rag_embedder
from src.ai.law_data_source import LawSourceError
from src.ai.llm_client import (
    LLMClient,
    LLMError,
    LLMNotReproducible,
    LLMUnavailable,
    default_llm_client,
)
from src.chunking import LawChunkSet, RagChunk, chunk_client_doc, chunk_provision
from src.internal_rag import InternalRagIndex, RagAnswer
from src.isolation import IsolationError, TenantScope
from src.judge import Judge, JudgeError, JudgeVerdict, default_judge, verify_entailment
from src.legal_research import ResearchGenerationError
from src.source_registry import SourceRegistry
from tiw.eval.scorer import build_rubric_result

SLICE_NO = 2
PENDING_DIMS = ["legal_reasoning", "issue_spotting", "risk", "output"]

StoreFactory = Callable[[], ChromaVectorStore]
CitationTamper = Callable[[Citation], Citation]


def _safe_mean(values: list[float], default: float = 1.0) -> float:
    return mean(values) if values else default


def _recall_targets(q: RagQuery) -> set[str]:
    """codex P1-1: the DEDUPED set of gold retrieval units for recall.

    ``gold_chunk_ids`` (조문 parent + 고객 메모) and ``expect_shared`` (공유 법령)
    overlap — a gold law parent (e.g. ``law25-2024``) is listed in BOTH. The old
    loop walked ``gold_chunk_ids + expect_shared`` directly, so that single parent
    was counted TWICE in the recall denominator (and twice in the hits), slightly
    inflating recall. Deduping to a set counts each retrieval UNIT exactly once —
    the honest denominator."""
    return set(q.gold_chunk_ids) | set(q.expect_shared)


def _retrieval_entailment(
    claims, citations, selected_chunk_ids: list[str], retrieved,
) -> tuple[int, int]:
    """codex P1-2: entailment anchored to the ACTUAL retrieval set.

    The judge verifies each citation against the grounding ``provision_quote`` it
    was HANDED; that proves nothing about whether the cited basis was actually
    *retrieved*. Here each (claim, citation) is verified DIRECTLY against the text
    of the chunks the ``RetrievalRun`` SELECTED:

      (a) the cited excerpt must appear in some chunk that is in the SELECTED
          retrieval set — a citation grounded OUTSIDE the retrieval set (no
          selected chunk contains it) is UNSUPPORTED → FABRICATED_CITATION; and
      (b) that chunk's text must support the claim's statutory anchors
          (deterministic ``verify_entailment`` — same rule matching as the judge).

    Returns (supported, total). Deterministic: no LLM, no judge self-report."""
    selected = set(selected_chunk_ids)
    texts = [rc.chunk.text for rc in retrieved if rc.chunk_id in selected]
    supported = total = 0
    for claim, cit in zip(claims, citations):
        total += 1
        supported += int(
            any(verify_entailment(claim.proposition, cit.quote, t).supported for t in texts)
        )
    return supported, total


def _build_corpus(case: EvaluationCase) -> tuple[list[RagChunk], int, int]:
    """Chunk the rag_corpus → (chunks, null_reject_total, null_reject_correct).

    Law docs are structure-chunked from the committed 법제처 fixture; client docs
    are single chunks. NULL-key client docs (expect_reject) are SEC-001 negatives:
    they must be REFUSED at ingest, so they are not added to the index here."""
    chunks: list[RagChunk] = []
    reject_total = reject_correct = 0
    for doc in case.rag_corpus:
        if doc.kind == "law":
            cs: LawChunkSet = chunk_provision(
                doc.law_name, doc.article_label, doc.effective_year,
                doc_id=doc.doc_id, tax_type=doc.tax_type,
            )
            chunks.extend(cs.all_chunks)
            continue
        # client doc
        level = ConfidentialityLevel(doc.confidentiality_level)
        if doc.expect_reject:
            reject_total += 1
            # SEC-001: a NULL/blank isolation key on client material must be refused.
            if level.is_client_scoped and not (doc.client_id and doc.client_id.strip()):
                reject_correct += 1
            continue
        chunks.append(
            chunk_client_doc(
                doc_id=doc.doc_id, text=doc.text, client_id=doc.client_id,
                confidentiality_level=level, doc_type=doc.chunk_type, tax_type=doc.tax_type,
            )
        )
    return chunks, reject_total, reject_correct


def run_case(
    case: EvaluationCase,
    store_factory: Optional[StoreFactory] = None,
    citation_tamper: Optional[CitationTamper] = None,
    llm_client: Optional[LLMClient] = None,
    judge: Optional[Judge] = None,
) -> RubricResult:
    client = llm_client or default_llm_client()
    jdg = judge or default_judge(client)

    queries: list[RagQuery] = list(case.rag_queries)
    n = len(queries)

    recall_hits = recall_total = 0
    cit_passed = cit_total = 0
    basis_present = answer_produced = run_logged = 0
    grounded_ok = 0
    total_leak = 0
    reproducible = True
    temporal_error = False
    fabricated = False
    missing_warning = False
    null_reject_total = null_reject_correct = 0
    routing_ok = True

    # judge accumulators
    judge_ran = 0
    judge_fracs: dict[str, list[float]] = {d: [] for d in PENDING_DIMS}
    entail_pass = entail_total = 0
    retr_entail_pass = retr_entail_total = 0   # codex P1-2: retrieval-anchored
    llm_in = llm_out = 0
    llm_cost = 0.0
    judge_model = "n/a"
    completed = True

    try:
        store = (store_factory or (lambda: ChromaVectorStore(embedder=default_rag_embedder())))()
        index = InternalRagIndex(store)
        chunks, null_reject_total, null_reject_correct = _build_corpus(case)
        # SHARED routing sanity: law chunks must land SHARED, client chunks TENANT
        expected_shared = sum(1 for c in chunks if c.client_id is None)
        index.ingest(chunks)
        routing_ok = store.shared_count() == expected_shared
    except (EmbeddingUnavailable, EmbeddingNotReproducible, IsolationError, LawSourceError):
        # fail-closed: cannot build the index reproducibly
        return _fail_closed_result(case, reason="index_build_failed")
    except Exception:  # noqa: BLE001
        return _fail_closed_result(case, reason="index_build_error")

    registry_by_q: dict[str, SourceRegistry] = {}

    for q in queries:
        scope = TenantScope(q.as_client)
        reg = SourceRegistry()
        registry_by_q[q.query_id] = reg
        try:
            rag: RagAnswer = index.answer(
                question_text=q.question_text,
                scope=scope,
                as_of=q.as_of_date,
                basis_kind=q.basis_kind,
                source_answer_id=f"sa_{case.case_id}_{q.query_id}",
                answer_run_id=f"ar_{case.case_id}_{q.query_id}",
                run_id=f"rr_{case.case_id}_{q.query_id}",
                high_risk=q.high_risk,
                source_type_label=q.gold_law.source_type,
                top_k=case.top_k,
                llm_client=client,
                registry=reg,
            )
        except (EmbeddingUnavailable, EmbeddingNotReproducible, LawSourceError,
                ResearchGenerationError, LLMError):
            # fail-closed: a missing/tampered generation (or embedding/source)
            # fixture is NOT a silent pass — the case becomes unmeasurable
            # (→ NOT_REPRODUCIBLE). LLMError covers LLMUnavailable/LLMNotReproducible.
            completed = False
            continue

        run = rag.retrieval_run
        run_logged += int(
            run is not None
            and run.filters.get("tenant_scope") == q.as_client
            and "as_of_date" in run.filters
        )

        selected = set(run.selected_chunk_ids)
        # -- recall@k (gold chunks + shared, DEDUPED — codex P1-1) --------- #
        for gid in _recall_targets(q):
            recall_total += 1
            recall_hits += int(gid in selected)

        # -- leakage (security hard gate) ---------------------------------- #
        total_leak += index.leakage(scope, rag.retrieved, list(q.forbidden_chunk_ids))

        if not rag.grounded or rag.answer is None:
            # no groundable provision retrieved → cannot citation-ground (fail-closed)
            reproducible = False
            continue
        grounded_ok += 1
        answer = rag.answer
        lookup = rag.grounding_lookup
        pv = lookup.provision_version

        # reproducibility: replay the provision hash
        if sha256(pv.text.encode("utf-8")).hexdigest() != pv.hash:
            reproducible = False

        basis_present += int(answer.bundle.applicable_basis is not None)
        answer_produced += int(bool(answer.answer_text))
        if q.high_risk and not answer.review_warnings:
            missing_warning = True

        # -- temporal correctness of the grounded version (RAG-005) -------- #
        g = q.gold_law
        title = lookup.article_title or ""
        text = pv.text or ""
        if (
            lookup.article_label != g.article_label
            or pv.effective_from != g.expected_effective_from
            or g.title_contains not in (title + text)
        ):
            temporal_error = True

        # -- citation grounding (deterministic 4 sub-checks) --------------- #
        reg.register_all(answer.bundle.source_objects)
        citation = citation_tamper(answer.bundle.citation) if citation_tamper else answer.bundle.citation
        verification = reg.verify_citation(citation)
        if verification.is_fabrication:
            fabricated = True
        registered = reg.get(citation.source_kind, citation.source_object_id)
        existence = verification.ok
        version_ok = (
            citation.source_kind is SourceKind.PROVISION_VERSION
            and isinstance(registered, ProvisionVersion)
        )
        pinpoint_ok = bool(citation.source_locator) and g.article_label in (citation.source_locator or "")
        temporal_ok = pv.effective_from <= q.as_of_date and (
            pv.effective_to is None or q.as_of_date < pv.effective_to
        )
        cit_total += 4
        cit_passed += int(existence) + int(version_ok) + int(pinpoint_ok) + int(temporal_ok)

        # -- DETERMINISTIC entailment vs the RETRIEVED chunks (codex P1-2) -- #
        # Each citation must be groundable in a chunk that is in THIS query's
        # RetrievalRun selected set, and that chunk text must support the claim.
        # A tampered citation is fed through the SAME path (adversarial honesty).
        ent_citations = (
            [citation_tamper(c) for c in answer.citations]
            if citation_tamper else answer.citations
        )
        rp, rt = _retrieval_entailment(
            answer.claims, ent_citations, run.selected_chunk_ids, rag.retrieved,
        )
        retr_entail_pass += rp
        retr_entail_total += rt
        cit_total += rt
        cit_passed += rp

        # -- JUDGE (reuse slice ①) ----------------------------------------- #
        try:
            verdict: JudgeVerdict = jdg.score(
                question_text=q.question_text,
                answer=answer,
                provision_quote=pv.text,
                gold_issues=list(q.gold_issues),
                tag=f"judge_{case.case_id}_{q.query_id}",
            )
            for d in PENDING_DIMS:
                judge_fracs[d].append(verdict.fractions[d])
            entail_pass += sum(1 for e in verdict.entailments if e.supported)
            entail_total += len(verdict.entailments)
            judge_ran += 1
            if answer.llm:
                llm_in += answer.llm.input_tokens
                llm_out += answer.llm.output_tokens
                llm_cost += answer.llm.cost_usd
            if verdict.llm:
                llm_in += verdict.llm.input_tokens
                llm_out += verdict.llm.output_tokens
                llm_cost += verdict.llm.cost_usd
                judge_model = verdict.llm.model
        except (LLMUnavailable, LLMNotReproducible):
            # codex P1: a MISSING/TAMPERED judge fixture is a reproducibility
            # failure (the replay infra is broken), not mere judge-incompleteness.
            # Trip NOT_REPRODUCIBLE (via measured=False) — never a silently absent
            # score. (A malformed verdict below is different: judge ran, output bad
            # → stay PENDING.)
            reproducible = False
        except (LLMError, ResearchGenerationError, JudgeError):
            # judge ran but produced no/invalid verdict → dims stay PENDING
            # (incomplete; slice can never be a ≥90 completion — never full marks).
            pass

    # FAIL-CLOSED reproducibility: every query must complete + ground + replay hash.
    measured = (
        n > 0 and completed and grounded_ok == n and reproducible and run_logged == n
    )
    judge_scored = judge_ran == n and n > 0 and measured

    entailment_unsupported = False
    if judge_scored:
        cit_passed += entail_pass
        cit_total += entail_total
        if entail_pass < entail_total:
            entailment_unsupported = True

    # codex P1-2: a citation whose basis is NOT in the retrieval set, or whose
    # retrieved chunk does not support the claim, is fabrication — deterministic,
    # judge-independent (trips even when the judge could not score).
    retr_entailment_unsupported = (
        retr_entail_total > 0 and retr_entail_pass < retr_entail_total
    )

    # -- dimension fractions ---------------------------------------------- #
    search_frac = (recall_hits / recall_total) if recall_total else 0.0
    citation_frac = (cit_passed / cit_total) if cit_total else 0.0
    requirement_frac = _safe_mean([
        (basis_present / n) if n else 0.0,
        (answer_produced / n) if n else 0.0,
        (run_logged / n) if n else 0.0,
    ])
    no_leak = 1.0 if total_leak == 0 else 0.0
    null_rej = (null_reject_correct / null_reject_total) if null_reject_total else 1.0
    scope_mandatory = 1.0  # structural: TenantScope is a required arg (SEC-002)
    security_frac = _safe_mean([no_leak, scope_mandatory, 1.0 if routing_ok else 0.0, null_rej])
    ops_frac = 1.0 if measured else 0.0

    if not measured:
        search_frac = citation_frac = requirement_frac = 0.0
        no_leak_unmeasured = total_leak == 0
        # security still reflects leakage truth, but unmeasured retrieval gets no recall credit
        security_frac = _safe_mean([
            1.0 if no_leak_unmeasured else 0.0, scope_mandatory,
            1.0 if routing_ok else 0.0, null_rej,
        ])

    dim_fractions = {
        "requirement": requirement_frac,
        "search": search_frac,
        "citation": citation_frac,
        "security": security_frac,
        "ops": ops_frac,
    }
    pending = list(PENDING_DIMS)
    judge_buckets: dict[str, int] = {}
    if judge_scored:
        for d in PENDING_DIMS:
            dim_fractions[d] = _safe_mean(judge_fracs[d], default=0.0)
            judge_buckets[d] = round(dim_fractions[d] * 100)
        pending = []

    # -- hard gates ------------------------------------------------------- #
    hard_gate_codes: list[str] = []
    if total_leak > 0:
        hard_gate_codes.append("TENANT_LEAK")             # cap 0 (SEC-003)
    if not measured:
        hard_gate_codes.append("NOT_REPRODUCIBLE")        # cap 75
    if temporal_error:
        hard_gate_codes.append("TEMPORAL_ERROR")          # cap 55
    if fabricated or entailment_unsupported or retr_entailment_unsupported:
        hard_gate_codes.append("FABRICATED_CITATION")     # cap 60
    if missing_warning:
        hard_gate_codes.append("MISSING_REVIEW_WARNING")  # cap 60

    entailment_metric = f"{entail_pass}/{entail_total}" if judge_scored else "PENDING_JUDGE"
    na_dims = ["conflict"]
    applicable_denominator = 100 - sum(DIMENSION_WEIGHTS[d] for d in na_dims)
    scope_note = (
        f"점수는 적용 차원 재정규화(분모 {applicable_denominator}점)입니다 — "
        f"conflict({DIMENSION_WEIGHTS['conflict']})는 이 slice에서 N/A(분모 제외)이며 "
        f"slice④(충돌)에서 측정됩니다."
    )

    metrics = {
        "recall": round(search_frac, 3),
        "leakage_count": total_leak,
        "citation_grounding": f"{cit_passed}/{cit_total}",
        "entailment": entailment_metric,
        "retrieval_entailment": f"{retr_entail_pass}/{retr_entail_total}",
        "temporal_error": temporal_error,
        "fabricated_citation": fabricated or entailment_unsupported or retr_entailment_unsupported,
        "missing_review_warning": missing_warning,
        "reproducible": reproducible,
        "grounded": f"{grounded_ok}/{n}",
        "retrieval_runs_logged": f"{run_logged}/{n}",
        "routing_ok": routing_ok,
        "null_key_rejected": f"{null_reject_correct}/{null_reject_total}",
        "measured": measured,
        "judge_scored": judge_scored,
        "judge_ran": f"{judge_ran}/{n}",
        "judge_scores": judge_buckets,
        "judge_model": judge_model,
        "embedding_model": getattr(default_rag_embedder(), "model_name", "n/a"),
        "llm_tokens": f"{llm_in}in/{llm_out}out",
        "llm_cost_usd": round(llm_cost, 6),
        "pending_judge_dims": pending or "none(scored)",
        "na_dimensions": na_dims,
        "applicable_denominator": applicable_denominator,
        "scope_note": scope_note,
    }

    return build_rubric_result(
        case_id=case.case_id,
        slice_no=SLICE_NO,
        target_id=case.case_id,
        visibility=case.visibility,
        target_kind=TargetKind.SLICE,
        dim_fractions=dim_fractions,
        dim_details={
            "requirement": f"basis={basis_present}/{n} answer={answer_produced}/{n} "
            f"retrieval_run={run_logged}/{n}",
            "search": f"recall={search_frac:.2f} ({recall_hits}/{recall_total})",
            "citation": f"grounding+entailment={cit_passed}/{cit_total} "
            f"(judge_entailment={entailment_metric} retrieval_entailment={retr_entail_pass}/{retr_entail_total})",
            "security": f"leak={total_leak} null_rej={null_reject_correct}/{null_reject_total} "
            f"routing_ok={routing_ok}",
            "ops": f"measured={measured} reproducible={reproducible} grounded={grounded_ok}/{n}",
            "legal_reasoning": f"judge bucket={judge_buckets.get('legal_reasoning')}"
            if judge_scored else "PENDING_JUDGE — judge/CPA 미연결 (보류)",
            "issue_spotting": f"judge bucket={judge_buckets.get('issue_spotting')}"
            if judge_scored else "PENDING_JUDGE — judge/CPA 미연결 (보류)",
            "risk": f"judge bucket={judge_buckets.get('risk')}"
            if judge_scored else "PENDING_JUDGE — judge/CPA 미연결 (보류)",
            "output": f"judge bucket={judge_buckets.get('output')}"
            if judge_scored else "PENDING_JUDGE — judge/CPA 미연결 (보류)",
        },
        hard_gate_codes=hard_gate_codes,
        metrics=metrics,
        pending_dimensions=pending,
    )


def _fail_closed_result(case: EvaluationCase, reason: str) -> RubricResult:
    """Index could not be built reproducibly → NOT_REPRODUCIBLE (never full marks)."""
    return build_rubric_result(
        case_id=case.case_id,
        slice_no=SLICE_NO,
        target_id=case.case_id,
        visibility=case.visibility,
        target_kind=TargetKind.SLICE,
        dim_fractions={"requirement": 0.0, "search": 0.0, "citation": 0.0,
                       "security": 0.0, "ops": 0.0},
        dim_details={"ops": f"fail-closed: {reason}"},
        hard_gate_codes=["NOT_REPRODUCIBLE"],
        metrics={"measured": False, "reason": reason, "leakage_count": 0},
        pending_dimensions=list(PENDING_DIMS),
    )


def run_cases(
    cases: list[EvaluationCase],
    store_factory: Optional[StoreFactory] = None,
    citation_tamper: Optional[CitationTamper] = None,
    llm_client: Optional[LLMClient] = None,
    judge: Optional[Judge] = None,
) -> list[RubricResult]:
    return [
        run_case(c, store_factory=store_factory, citation_tamper=citation_tamper,
                 llm_client=llm_client, judge=judge)
        for c in cases
    ]
