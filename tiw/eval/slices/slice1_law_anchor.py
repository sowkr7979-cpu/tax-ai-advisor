"""tiw/eval/slices/slice1_law_anchor.py — slice ① harness (법령MCP 앵커 답변).

Drives the DETERMINISTIC law-anchor core (src.ai.law_data_source +
src.law_anchor + src.source_registry) against the gold law-queries and scores
ONLY the judge-free dimensions:

  SCORED (deterministic):
    - search (9)      : recall@k — gold 조문이 올바른 시행일 버전으로 회수됐는가
    - citation (12)   : grounding의 결정적 부분 — 존재·버전·pinpoint·시점 일치
                        (entailment 는 judge → PENDING)
    - requirement (6) : 적용시점(applicable_basis) 확보 + 워크플로 매핑
    - ops (2)         : 재현성(SourceSnapshot/Provision 해시 복원) + 무오류 완료

  PENDING_JUDGE (exercised, withheld until judge/CPA wired — NOT full, NOT N/A):
    - legal_reasoning (20), issue_spotting (10), risk (11), output (9)
    - (citation entailment 도 judge — citation 차원의 결정적 부분만 채점)

  N/A (not exercised by a single-source SHARED-knowledge lookup):
    - conflict (7)    : cross-source 종합은 slice ④
    - security (14)   : 법령은 SHARED 공개 지식 — 테넌트/고객자료 표면 없음

Hard gates (deterministic, docs/09 §2):
  - NOT_REPRODUCIBLE (75) : 조회 실패·빈 결과·해시 불일치 → fail-closed (만점 금지)
  - TEMPORAL_ERROR  (55) : 회수 버전의 시행일이 gold 와 불일치(잘못된 시행일 버전)
  - FABRICATED_CITATION (60): 인용이 등록 소스객체로 해석 안 됨(존재/kind 불일치)
  - MISSING_REVIEW_WARNING (60): high-risk 질의에 회계사 검토경고 누락

`law_source` / `citation_tamper` are injectable ONLY so an adversarial test can
feed a wrong-version source or a corrupted citation through this SAME scoring
path and prove the harness CATCHES it (anti-gaming evidence, mirrors slice ⑥).
Production code never overrides them.
"""

from __future__ import annotations

from hashlib import sha256
from statistics import mean
from typing import Callable, Optional

from contract.base import SourceKind
from contract.cluster_d_provenance import ProvisionVersion
from contract.cluster_f_qa import Citation
from contract.cluster_i_eval import EvaluationCase, LawAnchorQuery, RubricResult, TargetKind
from src.ai.law_data_source import (
    LawSourceError,
    ProvisionLookupResult,
    default_law_source,
)
from src.law_anchor import build_law_source_answer
from src.source_registry import SourceRegistry
from tiw.eval.scorer import build_rubric_result

SLICE_NO = 1

# judge/CPA dimensions a full ① answer exercises but that we deliberately withhold
PENDING_DIMS = ["legal_reasoning", "issue_spotting", "risk", "output"]

# TODO(judge wiring — NEXT STEP, needs ANTHROPIC_API_KEY):
#   The LLM-judge (prompts/judge.md via src/ai/llm_client.py) scores PENDING_DIMS
#   + citation entailment against the recorded ProvisionVersion quote. To wire it:
#     1. add a `judge` param (default None) to run_case;
#     2. when present, for each bundle call judge.score(answer, provision_quote,
#        gold) → {legal_reasoning, issue_spotting, risk, output, entailment} in
#        0..1, and pass the entailment-adjusted citation fraction here;
#     3. move those names from `pending_dimensions=` into `dim_fractions=`.
#   Until then they stay PENDING_JUDGE (never full marks — docs/09 §6).

LawSourceFactory = Callable[[], object]
CitationTamper = Callable[[Citation], Citation]


def _safe_mean(values: list[float], default: float = 1.0) -> float:
    return mean(values) if values else default


def run_case(
    case: EvaluationCase,
    law_source: Optional[object] = None,
    citation_tamper: Optional[CitationTamper] = None,
) -> RubricResult:
    source = law_source or default_law_source()
    registry = SourceRegistry()

    queries: list[LawAnchorQuery] = list(case.law_queries)
    n = len(queries)

    recall_hits = recall_total = 0
    cit_passed = cit_total = 0
    basis_present = answer_produced = 0
    entailment_pending = 0
    search_step_hits = 0
    resolved = 0

    reproducible = True
    temporal_error = False
    fabricated = False
    missing_warning = False
    fallback_used: list[str] = []

    for q in queries:
        try:
            lookup: ProvisionLookupResult = source.lookup_provision(
                q.law_name, q.article_label, q.as_of_date
            )
        except LawSourceError:
            # fail-closed: an unresolved query means isolation of reproducibility
            # cannot be proven for this case (handled via `measured` below).
            continue
        resolved += 1
        fallback_used = lookup.fallback_chain or [lookup.backend]
        pv = lookup.provision_version

        # reproducibility (API-004): the recorded snapshot hash was already
        # re-verified on replay; here we re-check the provision text hash.
        if sha256(pv.text.encode("utf-8")).hexdigest() != pv.hash:
            reproducible = False
        if lookup.search_found:
            search_step_hits += 1

        gold_source_type = q.gold[0].source_type if q.gold else "법률"
        bundle = build_law_source_answer(
            lookup=lookup,
            client_id="client_eval",
            answer_run_id=f"ar_{case.case_id}_{q.query_id}",
            source_answer_id=f"sa_{case.case_id}_{q.query_id}",
            basis_kind=q.basis_kind,
            source_type_label=gold_source_type,
            high_risk=q.high_risk,
        )
        registry.register_all(bundle.source_objects)

        citation = citation_tamper(bundle.citation) if citation_tamper else bundle.citation
        verification = registry.verify_citation(citation)
        if verification.is_fabrication:
            fabricated = True

        if q.high_risk and not bundle.review_warnings:
            missing_warning = True

        basis_present += int(bundle.applicable_basis is not None)
        answer_produced += int(bool(bundle.source_answer.answer_text))
        entailment_pending += 1

        # -- recall@k (search) vs gold provision -------------------------- #
        for g in q.gold:
            recall_total += 1
            title = lookup.article_title or ""
            text = pv.text or ""
            match = (
                lookup.law_name == g.law_name
                and lookup.article_label == g.article_label
                and (g.title_contains in title or g.title_contains in text)
            )
            recall_hits += int(match)
            # -- TEMPORAL_ERROR: wrong 시행일 버전 -------------------------- #
            if pv.effective_from != g.expected_effective_from or g.title_contains not in (
                title + text
            ):
                temporal_error = True

        # -- citation grounding deterministic sub-checks (4) -------------- #
        existence = verification.ok
        registered = registry.get(citation.source_kind, citation.source_object_id)
        version_ok = (
            citation.source_kind is SourceKind.PROVISION_VERSION
            and isinstance(registered, ProvisionVersion)
        )
        pinpoint_ok = bool(citation.source_locator) and q.article_label in (
            citation.source_locator or ""
        )
        temporal_ok = pv.effective_from <= q.as_of_date and (
            pv.effective_to is None or q.as_of_date < pv.effective_to
        )
        cit_total += 4
        cit_passed += int(existence) + int(version_ok) + int(pinpoint_ok) + int(temporal_ok)

    # FAIL-CLOSED (docs/09 §2): every gold query must (a) RESOLVE, (b) replay its
    # recorded snapshot/version hash AND (c) complete the lawSearch step. A
    # missing/empty/tampered search fixture only sets search_found=False (the
    # efbody call can still pin the version); without making the search step a
    # REQUIRED reproducibility condition here, a silent search failure would still
    # score ~94 and pass. So search recall is fail-closed too (mirrors slice ⑥
    # retrieval_measured) — search failure is NOT a silent passthrough.
    search_complete = search_step_hits == n
    measured = n > 0 and resolved == n and reproducible and search_complete

    # -- dimension fractions (0..1) --------------------------------------- #
    search_frac = (recall_hits / recall_total) if recall_total else 0.0
    citation_frac = (cit_passed / cit_total) if cit_total else 0.0
    requirement_frac = _safe_mean(
        [
            (basis_present / n) if n else 0.0,
            (answer_produced / n) if n else 0.0,
            (search_step_hits / n) if n else 0.0,
        ]
    )
    ops_frac = 1.0 if measured else 0.0

    if not measured:
        search_frac = citation_frac = requirement_frac = 0.0

    # -- hard gates ------------------------------------------------------- #
    hard_gate_codes: list[str] = []
    if not measured:
        hard_gate_codes.append("NOT_REPRODUCIBLE")          # cap 75
    if temporal_error:
        hard_gate_codes.append("TEMPORAL_ERROR")            # cap 55
    if fabricated:
        hard_gate_codes.append("FABRICATED_CITATION")       # cap 60
    if missing_warning:
        hard_gate_codes.append("MISSING_REVIEW_WARNING")    # cap 60

    metrics = {
        "recall": round(search_frac, 3),
        "citation_grounding": f"{cit_passed}/{cit_total}",
        "entailment": "PENDING_JUDGE",
        "temporal_error": temporal_error,
        "fabricated_citation": fabricated,
        "missing_review_warning": missing_warning,
        "reproducible": reproducible,
        "search_complete": search_complete,
        "measured": measured,
        "resolved_queries": f"{resolved}/{n}",
        "search_found": f"{search_step_hits}/{n}",
        "backend_chain": fallback_used,
        "pending_judge_dims": PENDING_DIMS + ["citation:entailment"],
    }

    return build_rubric_result(
        case_id=case.case_id,
        slice_no=SLICE_NO,
        target_id=case.case_id,
        visibility=case.visibility,
        target_kind=TargetKind.SLICE,
        dim_fractions={
            "requirement": requirement_frac,
            "search": search_frac,
            "citation": citation_frac,
            "ops": ops_frac,
        },
        dim_details={
            "requirement": f"basis={basis_present}/{n} answer={answer_produced}/{n} "
            f"search_found={search_step_hits}/{n}",
            "search": f"recall={search_frac:.2f} ({recall_hits}/{recall_total})",
            "citation": f"existence/version/pinpoint/temporal={cit_passed}/{cit_total} "
            f"(entailment=PENDING_JUDGE)",
            "ops": f"measured={measured} reproducible={reproducible} "
            f"search_complete={search_complete} ({search_step_hits}/{n})",
        },
        hard_gate_codes=hard_gate_codes,
        metrics=metrics,
        pending_dimensions=PENDING_DIMS,
    )


def run_cases(
    cases: list[EvaluationCase],
    law_source: Optional[object] = None,
    citation_tamper: Optional[CitationTamper] = None,
) -> list[RubricResult]:
    return [run_case(c, law_source=law_source, citation_tamper=citation_tamper) for c in cases]
