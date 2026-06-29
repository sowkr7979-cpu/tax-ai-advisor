"""tiw/eval/slices/slice1_law_anchor.py — slice ① harness (법령MCP 앵커 답변).

Drives the channel-① pipeline against the gold law-queries and scores it:

  DETERMINISTIC dimensions (always):
    - search (9)      : recall@k — gold 조문이 올바른 시행일 버전으로 회수됐는가
    - citation (12)   : grounding 결정적 부분(존재·버전·pinpoint·시점) + (judge 가동 시)
                        **entailment** 를 더한 인용 채점
    - requirement (6) : 적용시점(applicable_basis) 확보 + 워크플로 매핑
    - ops (2)         : 재현성(SourceSnapshot/Provision 해시 복원) + 무오류 완료

  JUDGE dimensions (LLM-judge via prompts/judge.md + src/ai/llm_client.py):
    - legal_reasoning (20) · issue_spotting (10) · risk (11) · output (9)
    - + citation entailment(각 인용이 claim을 지지하는가; 미지지 → 거부, HALU-003 cap60)

  N/A (single-source SHARED-knowledge lookup):
    - conflict (7)    : cross-source 종합은 slice ④
    - security (14)   : 법령은 SHARED 공개 지식 — 테넌트/고객자료 표면 없음

FAIL-CLOSED (PROMPT.md §4-5, docs/09 §6): the judge dimensions are moved from
``pending_dimensions`` into ``dim_fractions`` ONLY when the LLM-judge actually
ran for EVERY query AND the case is reproducibly ``measured``. If the judge is
not wired (no key / missing fixture / malformed output) or the case is not
measured, those dimensions STAY PENDING (never full marks) and the slice stays
INCOMPLETE. The live generation/judge call is recorded ONCE
(scripts/record_llm_fixtures.py); tests/CI replay fixtures (network/key = 0).

Hard gates (deterministic, docs/09 §2):
  - NOT_REPRODUCIBLE (75) : 조회 실패·빈 결과·해시 불일치 → fail-closed (만점 금지)
  - TEMPORAL_ERROR  (55) : 회수 버전의 시행일이 gold 와 불일치
  - FABRICATED_CITATION (60): 인용이 등록 소스객체로 해석 안 됨 OR judge entailment 미지지
  - MISSING_REVIEW_WARNING (60): high-risk 질의에 회계사 검토경고 누락

`law_source` / `citation_tamper` / `llm_client` / `judge` / `generator` are
injectable ONLY so adversarial tests can feed a wrong-version source, a corrupted
citation, an empty-fixture client, or a fake judge verdict through this SAME
scoring path and prove the harness CATCHES it (anti-gaming evidence).
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
from src.ai.llm_client import LLMClient, LLMError, default_llm_client
from src.judge import Judge, JudgeError, JudgeVerdict, default_judge
from src.law_anchor import build_law_source_answer
from src.legal_research import (
    ResearchGenerationError,
    ResearchLiteAnswer,
    generate_research_answer,
)
from src.source_registry import SourceRegistry
from rules.hard_gates import DIMENSION_WEIGHTS
from tiw.eval.scorer import build_rubric_result

SLICE_NO = 1

# judge/CPA dimensions a full ① answer exercises; moved scored↔pending per run.
PENDING_DIMS = ["legal_reasoning", "issue_spotting", "risk", "output"]

LawSourceFactory = Callable[[], object]
CitationTamper = Callable[[Citation], Citation]
# generator(**kwargs) -> ResearchLiteAnswer (default: src.legal_research)
ResearchGenerator = Callable[..., ResearchLiteAnswer]


def _safe_mean(values: list[float], default: float = 1.0) -> float:
    return mean(values) if values else default


def run_case(
    case: EvaluationCase,
    law_source: Optional[object] = None,
    citation_tamper: Optional[CitationTamper] = None,
    llm_client: Optional[LLMClient] = None,
    judge: Optional[Judge] = None,
    generator: Optional[ResearchGenerator] = None,
) -> RubricResult:
    source = law_source or default_law_source()
    registry = SourceRegistry()
    # Shared replay LLM client (no key/network). Generation + judge log usage here.
    client = llm_client or default_llm_client()
    jdg = judge or default_judge(client)
    gen = generator or generate_research_answer

    queries: list[LawAnchorQuery] = list(case.law_queries)
    n = len(queries)

    recall_hits = recall_total = 0
    cit_passed = cit_total = 0
    basis_present = answer_produced = 0
    search_step_hits = 0
    resolved = 0

    reproducible = True
    temporal_error = False
    fabricated = False
    missing_warning = False
    fallback_used: list[str] = []

    # -- judge accumulators (only filled when the LLM-judge runs per query) --- #
    judge_ran = 0                       # queries for which gen+judge succeeded
    judge_fracs: dict[str, list[float]] = {d: [] for d in PENDING_DIMS}
    # codex P1-1: count entailment PER CITATION (deterministic verdict), not a
    # per-query rollup, so a single unsupported citation is visible and penalized.
    entail_pass = 0                     # citations deterministically entailed
    entail_total = 0                    # citations evaluated
    llm_input_tokens = llm_output_tokens = 0
    llm_cost = 0.0
    judge_model = "n/a"

    for q in queries:
        try:
            lookup: ProvisionLookupResult = source.lookup_provision(
                q.law_name, q.article_label, q.as_of_date
            )
        except LawSourceError:
            continue
        resolved += 1
        fallback_used = lookup.fallback_chain or [lookup.backend]
        pv = lookup.provision_version

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

        # -- recall@k (search) vs gold provision --------------------------- #
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
            if pv.effective_from != g.expected_effective_from or g.title_contains not in (
                title + text
            ):
                temporal_error = True

        # -- citation grounding deterministic sub-checks (4) --------------- #
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

        # -- JUDGE layer (LLM, fail-closed) -------------------------------- #
        # Generation + judge run on the recorded fixtures. ANY failure (missing
        # fixture, malformed output, no key) leaves this query's judge dims
        # unscored — the case then stays PENDING (never full marks).
        try:
            answer: ResearchLiteAnswer = gen(
                lookup=lookup,
                question_text=q.question_text,
                client_id="client_eval",
                answer_run_id=f"ar_{case.case_id}_{q.query_id}",
                source_answer_id=f"sa_{case.case_id}_{q.query_id}",
                source_type_label=gold_source_type,
                high_risk=q.high_risk,
                llm_client=client,
            )
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
                llm_input_tokens += answer.llm.input_tokens
                llm_output_tokens += answer.llm.output_tokens
                llm_cost += answer.llm.cost_usd
            if verdict.llm:
                llm_input_tokens += verdict.llm.input_tokens
                llm_output_tokens += verdict.llm.output_tokens
                llm_cost += verdict.llm.cost_usd
                judge_model = verdict.llm.model
        except (LLMError, ResearchGenerationError, JudgeError):
            # fail-closed: keep judge dims pending for this case
            pass

    # FAIL-CLOSED reproducibility (docs/09 §2): every gold query must RESOLVE,
    # replay its hash AND complete the lawSearch step.
    search_complete = search_step_hits == n
    measured = n > 0 and resolved == n and reproducible and search_complete

    # judge is SCORED only if it ran for every query AND the case is measured.
    judge_scored = judge_ran == n and n > 0 and measured

    # entailment → citation fraction + FABRICATED gate (HALU-003).
    # entail_pass/total are PER-CITATION deterministic verdicts (codex P1-1):
    # any citation whose provision excerpt fails to support its claim trips the
    # FABRICATED_CITATION gate (cap 60), regardless of the judge's self-report.
    entailment_unsupported = False
    if judge_scored:
        cit_passed += entail_pass
        cit_total += entail_total
        if entail_pass < entail_total:
            entailment_unsupported = True

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

    dim_fractions = {
        "requirement": requirement_frac,
        "search": search_frac,
        "citation": citation_frac,
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
    if not measured:
        hard_gate_codes.append("NOT_REPRODUCIBLE")          # cap 75
    if temporal_error:
        hard_gate_codes.append("TEMPORAL_ERROR")            # cap 55
    if fabricated or entailment_unsupported:
        hard_gate_codes.append("FABRICATED_CITATION")       # cap 60 (HALU-003)
    if missing_warning:
        hard_gate_codes.append("MISSING_REVIEW_WARNING")    # cap 60

    entailment_metric = (
        f"{entail_pass}/{entail_total}" if judge_scored else "PENDING_JUDGE"
    )

    # -- scope transparency (codex P1-3): this slice scores only the dimensions it
    # actually exercises; conflict(7)/security(14) are N/A here (measured in
    # slice④/⑥). The headline is the WEIGHTED mean RENORMALIZED over the applicable
    # denominator — so a "100/100" is 100% of the APPLICABLE 79 points, NOT全 100점
    # coverage. The scoring math is unchanged; this only makes the denominator
    # explicit so the number is not mistaken for full-rubric coverage.
    na_dims = [d for d in ("conflict", "security")]
    applicable_denominator = 100 - sum(DIMENSION_WEIGHTS[d] for d in na_dims)
    scope_note = (
        f"점수는 적용 차원 재정규화(분모 {applicable_denominator}점)입니다 — "
        f"conflict({DIMENSION_WEIGHTS['conflict']})·security({DIMENSION_WEIGHTS['security']})는 "
        f"이 slice에서 N/A(분모 제외)이며 slice④(충돌)·slice⑥(보안)에서 측정됩니다."
    )

    metrics = {
        "recall": round(search_frac, 3),
        "citation_grounding": f"{cit_passed}/{cit_total}",
        "entailment": entailment_metric,
        "temporal_error": temporal_error,
        "fabricated_citation": fabricated or entailment_unsupported,
        "missing_review_warning": missing_warning,
        "reproducible": reproducible,
        "search_complete": search_complete,
        "measured": measured,
        "resolved_queries": f"{resolved}/{n}",
        "search_found": f"{search_step_hits}/{n}",
        "backend_chain": fallback_used,
        "judge_scored": judge_scored,
        "judge_ran": f"{judge_ran}/{n}",
        "judge_scores": judge_buckets,
        "judge_model": judge_model,
        "llm_tokens": f"{llm_input_tokens}in/{llm_output_tokens}out",
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
            f"search_found={search_step_hits}/{n}",
            "search": f"recall={search_frac:.2f} ({recall_hits}/{recall_total})",
            "citation": f"grounding+entailment={cit_passed}/{cit_total} "
            f"(entailment={entailment_metric})",
            "ops": f"measured={measured} reproducible={reproducible} "
            f"search_complete={search_complete} ({search_step_hits}/{n})",
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


def run_cases(
    cases: list[EvaluationCase],
    law_source: Optional[object] = None,
    citation_tamper: Optional[CitationTamper] = None,
    llm_client: Optional[LLMClient] = None,
    judge: Optional[Judge] = None,
    generator: Optional[ResearchGenerator] = None,
) -> list[RubricResult]:
    return [
        run_case(
            c, law_source=law_source, citation_tamper=citation_tamper,
            llm_client=llm_client, judge=judge, generator=generator,
        )
        for c in cases
    ]
