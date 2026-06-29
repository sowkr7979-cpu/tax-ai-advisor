"""tiw/eval/slices/slice4_synthesis.py — slice ④ harness (충돌 케이스 · 3소스 종합).

THE CAPSTONE. Drives ``src.synthesis.SynthesisEngine`` over the gold ensemble
scenarios (EVAL-011: 침묵·2v1·3way·법령부재) and scores the conflict(7) dimension
that was N/A in slices ①②③, plus the judge/citation/requirement/ops dimensions.

  DETERMINISTIC:
    - requirement (6) : ORCH-008(1≤SourceAnswer≤3·source_type 유일·SynthesisOpinion 1개)
                        + status 기록(ORCH-009) + applicable_basis + 검토항목
    - citation (12)   : 상속 인용 grounding(존재·버전·pinpoint·시점) + (judge) entailment
                        + lineage 무결성(추적불가 0, HALU-014) + 신규 인용 0(ORCH-012)
    - conflict (7) ★  : 충돌탐지 F1 + 결정테이블 outcome 일치 + 정확보류 + lineage +
                        authority_deficit 일치 (EVAL-012; 평균/뭉갬 → 0)
    - ops (2)         : 재현성(결정적 종합 + fixture replay)

  JUDGE (src.judge.SynthesisJudge, fixture-recorded):
    - legal_reasoning (20) · issue_spotting (10) · risk (11) · output (9) + entailment

  N/A (분모 77): search (9) → 검색은 per-source(①②③) ; security (14) → 격리는 slice⑥.

HARD GATES (docs/09 §2):
  - NOT_REPRODUCIBLE (75) : gen/judge fixture 부재·해시불일치 OR lineage 추적불가(HALU-014)
  - TEMPORAL_ERROR  (55)  : 종합이 적용시점 무효(구) 버전을 권위로 채택
  - FABRICATED_CITATION(60): 소스 인용 날조(HALU-013) OR entailment 미지지 OR 신규 인용
                            생성(ORCH-012) OR **충돌 평균/뭉갬**(suppressed) OR **미해소
                            충돌 단정**(abstain 회피) OR **권위 위계 위반**(웹/하위로 override)
  - MISSING_REVIEW_WARNING(60): 고위험/충돌 종합에 회계사 검토경고 누락

``engine_factory`` / ``citation_tamper`` / ``llm_client`` / ``judge`` are injectable
ONLY so adversarial tests can feed a conflict-averaging engine, a fabricated source
citation, an authority-overriding engine, an empty-fixture client, or a fake judge
through this SAME scoring path and prove the harness CATCHES it (anti-gaming).
"""

from __future__ import annotations

from datetime import date
from hashlib import sha256
from statistics import mean
from typing import Callable, Optional

from contract.base import (
    AlignmentStatus,
    SourceAnswerStatus,
    SourceKind,
    SourceType,
)
from contract.cluster_d_provenance import ProvisionVersion
from contract.cluster_f_qa import Citation, SourceAnswer
from contract.cluster_i_eval import (
    EvaluationCase,
    RubricResult,
    SynthesisScenario,
    SynthesisSourceSpec,
    TargetKind,
)
from rules.hard_gates import DIMENSION_WEIGHTS
from src.ai.law_data_source import LawSourceError, default_law_source
from src.ai.llm_client import (
    LLMClient,
    LLMError,
    LLMNotReproducible,
    LLMUnavailable,
    default_llm_client,
)
from src.judge import (
    EntailTarget,
    JudgeError,
    JudgeVerdict,
    SynthesisJudge,
    _provision_subject,
    default_synthesis_judge,
)
from src.law_anchor import build_law_source_answer
from src.legal_research import (
    ResearchGenerationError,
    generate_research_answer,
)
from src.source_registry import SourceRegistry
from src.synthesis import SourceContribution, SynthesisEngine, SynthesisResult
from tiw.eval.scorer import build_rubric_result

SLICE_NO = 4
PENDING_DIMS = ["legal_reasoning", "issue_spotting", "risk", "output"]
NA_DIMS = ["search", "security"]

EngineFactory = Callable[[], SynthesisEngine]
CitationTamper = Callable[[Citation], Citation]


def _safe_mean(values: list[float], default: float = 1.0) -> float:
    return mean(values) if values else default


# --------------------------------------------------------------------------- #
# Source-answer construction (reuses the shared SourceAnswer generators)
# --------------------------------------------------------------------------- #
def _build_contribution(
    spec: SynthesisSourceSpec, scenario: SynthesisScenario, *, case_id: str,
    law_source, llm_client: LLMClient, registry: SourceRegistry,
    citation_tamper: Optional[CitationTamper],
) -> SourceContribution:
    """Build one channel's INDEPENDENT SourceAnswer (① anchor builder / shared
    research generator), register its citations, and flag fabrication (HALU-013)."""
    sa_id = f"sa_{case_id}_{scenario.scenario_id}_{spec.channel_label}"
    ar_id = f"ar_{case_id}_{scenario.scenario_id}"

    if spec.status is not SourceAnswerStatus.ANSWERED:
        # SILENT/ERROR/BLOCKED — a coverage gap, NOT a conflict (docs/08 §5-0).
        sa = SourceAnswer(
            source_answer_id=sa_id, answer_run_id=ar_id, source_type=spec.source_type,
            status=spec.status, answer_text="(침묵: 해당 채널 근거 없음 — 커버리지 갭)",
            client_id="client_eval",
        )
        return SourceContribution(
            source_type=spec.source_type, channel_label=spec.channel_label,
            authority_label=spec.authority_label, status=spec.status, source_answer=sa,
            topic_key=spec.topic_key, stance="", provision_version=None,
        )

    lookup = law_source.lookup_provision(
        spec.law_name, spec.article_label, date(spec.grounding_year, 1, 1)
    )
    pv = lookup.provision_version
    stance = _provision_subject(pv.text) if spec.stance_from_subject else spec.stance

    if spec.is_primary:
        # the source whose full LLM 법리 the synthesis presents (one gen per scenario)
        research = generate_research_answer(
            lookup=lookup, question_text=scenario.question_text, client_id="client_eval",
            answer_run_id=ar_id, source_answer_id=sa_id,
            source_type_label=spec.authority_label, high_risk=scenario.high_risk,
            answer_source_type=spec.source_type, channel_label=spec.channel_label,
            basis_kind=scenario.basis_kind, llm_client=llm_client,
        )
        claims = list(research.claims)
        citations = list(research.citations)
        sa = research.source_answer
        contribution_research = research
    else:
        bundle = build_law_source_answer(
            lookup=lookup, client_id="client_eval", answer_run_id=ar_id,
            source_answer_id=sa_id, basis_kind=scenario.basis_kind,
            source_type_label=spec.authority_label, high_risk=scenario.high_risk,
            answer_source_type=spec.source_type, channel_label=spec.channel_label,
        )
        claims = [bundle.claim]
        citations = [bundle.citation]
        sa = bundle.source_answer
        contribution_research = None

    if citation_tamper is not None:
        citations = [citation_tamper(c) for c in citations]

    # register source objects + verify each citation (HALU-013 fabrication detection)
    registry.register(pv)
    registry.register(lookup.snapshot)
    fabricated = any(registry.verify_citation(c).is_fabrication for c in citations)

    return SourceContribution(
        source_type=spec.source_type, channel_label=spec.channel_label,
        authority_label=spec.authority_label, status=spec.status, source_answer=sa,
        topic_key=spec.topic_key, stance=stance, dispositive=spec.dispositive,
        fact_match=spec.fact_match, version_based=spec.stance_from_subject,
        provision_version=pv, claims=claims, citations=citations,
        research=contribution_research, is_primary=spec.is_primary, fabricated=fabricated,
    )


# --------------------------------------------------------------------------- #
# Per-scenario run + scoring
# --------------------------------------------------------------------------- #
def _run_scenario(
    scenario: SynthesisScenario, *, case_id: str, law_source, llm_client: LLMClient,
    judge: SynthesisJudge, engine: SynthesisEngine, citation_tamper: Optional[CitationTamper],
) -> dict:
    out: dict = {"completed": True, "judge_ran": False}
    registry = SourceRegistry()
    try:
        contributions = [
            _build_contribution(
                spec, scenario, case_id=case_id, law_source=law_source,
                llm_client=llm_client, registry=registry, citation_tamper=citation_tamper,
            )
            for spec in scenario.sources
        ]
    except (LawSourceError, LLMError, ResearchGenerationError):
        out["completed"] = False
        return out

    primary = next((c for c in contributions if c.is_primary), None)
    result: SynthesisResult = engine.synthesize(
        contributions=contributions, as_of_date=scenario.as_of_date,
        answer_run_id=f"ar_{case_id}_{scenario.scenario_id}",
        synthesis_id=f"syn_{case_id}_{scenario.scenario_id}",
        high_risk=scenario.high_risk,
        primary_research=(primary.research if primary else None),
    )

    # -- reproducibility: source provision hashes replay ---------------------- #
    reproducible = all(
        sha256(c.provision_version.text.encode("utf-8")).hexdigest() == c.provision_version.hash
        for c in contributions if c.provision_version is not None
    )
    out["reproducible"] = reproducible

    # -- lineage 무결성 (HALU-014) ------------------------------------------- #
    untraceable = result.untraceable_claims()
    new_citations = result.new_citations
    out["lineage_ok"] = (not untraceable) and (not new_citations)
    out["fabricated_sources"] = list(result.fabricated_source_ids)

    # -- conflict(7): alignment / resolution vs gold (EVAL-012) --------------- #
    gold_by_topic = {t.topic_key: t for t in scenario.topics}
    recon_by_topic = {r.topic_key: r for r in result.reconciliations}
    tp = fp = fn = 0
    outcome_hits = outcome_total = 0
    align_hits = align_total = 0
    adopted_hits = adopted_total = 0
    excluded_hits = excluded_total = 0
    for tk, gold in gold_by_topic.items():
        recon = recon_by_topic.get(tk)
        align_total += 1
        if recon is None:
            fn += int(gold.expected_status is AlignmentStatus.CONFLICT)
            excluded_total += 1                   # missing recon → expected 배제 미적용
            continue
        syn_status = recon.alignment.status
        syn_outcome = recon.result.outcome
        align_hits += int(syn_status == gold.expected_status)
        # conflict-detection confusion matrix (CONFLICT = positive)
        g_conf = gold.expected_status is AlignmentStatus.CONFLICT
        s_conf = syn_status is AlignmentStatus.CONFLICT
        tp += int(g_conf and s_conf)
        fp += int(s_conf and not g_conf)
        fn += int(g_conf and not s_conf)         # suppressed conflict (averaging sin)
        # resolution outcome match
        outcome_total += 1
        outcome_hits += int(syn_outcome.value == gold.expected_outcome.value)
        # adopted channels match (권위 위계 적용 검증)
        if gold.expected_adopted:
            adopted_total += 1
            adopted_chan = {
                c.channel_label for c in contributions
                if recon.synthesis_claim is not None
                and c.source_answer.source_answer_id == recon.synthesis_claim.source_answer_id
            }
            adopted_hits += int(adopted_chan == set(gold.expected_adopted))
        # expected-EXCLUDED channels match (codex P1-2): gold ``expected_excluded``
        # are the 시점/사실 배제 채널. Every topic is scored, so BOTH under-exclusion
        # (배제돼야 할 채널이 채택/잔존) AND over-exclusion lower the conflict score.
        excluded_total += 1
        actual_excluded = {p.channel_label for p in recon.result.excluded}
        excluded_hits += int(actual_excluded == set(gold.expected_excluded))

    conflict_suppressed = fn > 0
    # F1 (codex P2-2): only meaningful when there IS a positive(CONFLICT) topic.
    # With zero positives (SILENT/LAW_ABSENT 합의), precision/recall are undefined —
    # report N/A and EXCLUDE F1 from the conflict 산식 instead of a trivial 1.0.
    has_positive = (tp + fp + fn) > 0
    if has_positive:
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        out["conflict_f1"] = round(f1, 3)
    else:
        f1 = None
        out["conflict_f1"] = "N/A"
    outcome_rate = (outcome_hits / outcome_total) if outcome_total else 1.0
    align_rate = (align_hits / align_total) if align_total else 1.0
    adopted_rate = (adopted_hits / adopted_total) if adopted_total else 1.0
    excluded_rate = (excluded_hits / excluded_total) if excluded_total else 1.0

    abstain_correct = result.abstained == scenario.expect_abstain
    deficit_correct = result.authority_deficit == scenario.expect_authority_deficit
    unresolved_asserted = scenario.expect_abstain and not result.abstained

    out["conflict_suppressed"] = conflict_suppressed
    out["excluded_match"] = (excluded_hits == excluded_total)
    out["unresolved_asserted"] = unresolved_asserted
    out["abstain_correct"] = abstain_correct
    out["deficit_correct"] = deficit_correct

    # -- authority-hierarchy / temporal violation (권위 override·구버전 채택) -- #
    temporal_error = False
    authority_violated = unresolved_asserted
    for recon in result.reconciliations:
        if recon.synthesis_claim is None:
            continue
        adopted = next(
            (c for c in contributions
             if c.source_answer.source_answer_id == recon.synthesis_claim.source_answer_id),
            None,
        )
        if adopted is None or adopted.provision_version is None:
            continue
        ef = adopted.provision_version.effective_from
        # superseded-version adoption: a later in-force version exists but wasn't adopted
        peers = [
            c for c in contributions
            if c.topic_key == recon.topic_key and c.answered and c.provision_version is not None
        ]
        later_in_force = any(
            c.provision_version.effective_from > ef
            and c.provision_version.effective_from <= scenario.as_of_date
            for c in peers
        )
        if ef > scenario.as_of_date or later_in_force:
            temporal_error = True
        # authority override (codex P0 — outcome-INDEPENDENT): compute the ACTUALLY
        # adopted source's decision-table rank and compare it directly against each
        # peer's rank. A synthesis that adopts a STRICTLY-LOWER authority than an
        # available, temporally-valid, dispositive, fact-usable peer taking a
        # DIFFERENT stance on the same topic has let 하위 권위가 상위(법령)를 override
        # — caught even if the ``outcome`` label is forged to a 합의 (the old gate
        # only fired when outcome was literally AUTHORITY, so 라벨 변조로 우회됐다).
        from rules.conflict_resolution import authority_rank_of
        adopted_rank = authority_rank_of(adopted.authority_label)
        for c in peers:
            if c is adopted:
                continue
            pv_c = c.provision_version
            c_temporally_valid = pv_c.effective_from <= scenario.as_of_date and (
                pv_c.effective_to is None or scenario.as_of_date < pv_c.effective_to
            )
            if (
                authority_rank_of(c.authority_label) < adopted_rank
                and c.dispositive
                and c.fact_match
                and c_temporally_valid
                and c.stance != adopted.stance
            ):
                authority_violated = True
    out["temporal_error"] = temporal_error
    out["authority_violated"] = authority_violated

    conflict_components = [
        outcome_rate, align_rate, adopted_rate, excluded_rate,
        1.0 if abstain_correct else 0.0,
        1.0 if deficit_correct else 0.0,
        1.0 if out["lineage_ok"] else 0.0,
    ]
    if f1 is not None:                            # exclude trivial F1 on no-positive
        conflict_components.insert(0, f1)
    conflict_frac = _safe_mean(conflict_components, default=0.0)
    # 충돌 무결성 위반 → conflict 0점 (하드게이트와 별개로 차원 자체를 0으로):
    #   평균/뭉갬 · 미해소 단정 · 권위 위반 · lineage 추적불가/신규 인용(ORCH-012/HALU-014).
    conflict_integrity_broken = not out["lineage_ok"]
    if (conflict_suppressed or unresolved_asserted or authority_violated
            or conflict_integrity_broken):
        conflict_frac = 0.0
    out["conflict_frac"] = conflict_frac

    # -- requirement(6): ORCH-008/009 + applicable_basis + 검토항목 ----------- #
    src_types = [c.source_type for c in contributions]
    orch008_ok = (1 <= len(contributions) <= 3) and len(set(src_types)) == len(src_types)
    synth_count_ok = True  # SynthesisOpinion is exactly 1 by construction (ORCH-008②)
    status_recorded = all(isinstance(c.status, SourceAnswerStatus) for c in contributions)
    basis_ok = all(
        cit.applicable_basis is not None for c in contributions for cit in c.citations
    )
    needs_items = any(
        r.alignment.status is AlignmentStatus.CONFLICT for r in result.reconciliations
    ) or scenario.high_risk or result.abstained
    items_ok = (not needs_items) or bool(result.review_items)
    requirement_frac = _safe_mean([
        1.0 if orch008_ok else 0.0, 1.0 if synth_count_ok else 0.0,
        1.0 if status_recorded else 0.0, 1.0 if basis_ok else 0.0,
        1.0 if items_ok else 0.0,
    ])
    out["requirement"] = requirement_frac

    # -- citation(12): 상속 인용 grounding + lineage + 신규 인용 0 ------------ #
    fabricated = bool(result.fabricated_source_ids)
    cit_passed = cit_total = 0
    primary_spec = next((s for s in scenario.sources if s.is_primary), None)
    if primary is not None and primary.research is not None:
        pv = primary.provision_version
        art = primary_spec.article_label if primary_spec else ""
        for citation in (primary.research.bundle.citation, primary.research.conclusion_citation):
            cit = citation
            verification = registry.verify_citation(cit)
            if verification.is_fabrication:
                fabricated = True
            registered = registry.get(cit.source_kind, cit.source_object_id)
            existence = verification.ok
            version_ok = (
                cit.source_kind is SourceKind.PROVISION_VERSION
                and isinstance(registered, ProvisionVersion)
            )
            pinpoint_ok = bool(cit.source_locator) and (art or "") in (cit.source_locator or "")
            temporal_ok = pv.effective_from <= scenario.as_of_date and (
                pv.effective_to is None or scenario.as_of_date < pv.effective_to
            )
            cit_total += 4
            cit_passed += int(existence) + int(version_ok) + int(pinpoint_ok) + int(temporal_ok)
    out["cit_passed"] = cit_passed
    out["cit_total"] = cit_total
    out["fabricated"] = fabricated
    out["new_citations"] = len(new_citations)

    # -- review warning (high-risk) ----------------------------------------- #
    from src.synthesis import SYNTHESIS_REVIEW_WARNING
    out["missing_warning"] = scenario.high_risk and not any(
        SYNTHESIS_REVIEW_WARNING in it for it in result.review_items
    )

    # -- JUDGE (synthesis) --------------------------------------------------- #
    if primary is not None and primary.research is not None:
        research = primary.research
        positions_str = "\n".join(
            f"- {c.channel_label} {c.source_type.value}({c.authority_label}): "
            + (f"'{c.stance}'" if c.answered else "침묵(SILENT)")
            for c in contributions
        )
        resolution_str = "\n".join(
            f"- [{r.topic_key}] {r.alignment.status.value} → {r.result.outcome.value}: "
            f"{r.result.rule_applied}"
            for r in result.reconciliations
        )
        targets = [
            EntailTarget(claim_text=cl.proposition, quote=(cit.quote or ""),
                         provision_text=research.provision_version.text)
            for cl, cit in zip(research.claims, research.citations)
        ]
        try:
            verdict: JudgeVerdict = judge.score(
                question_text=scenario.question_text,
                opinion_text=result.synthesis.opinion_text,
                source_positions=positions_str, resolution_summary=resolution_str,
                entail_targets=targets, provision_body=research.provision_version.text,
                gold_issues=list(scenario.gold_issues),
                tag=f"synthjudge_{case_id}_{scenario.scenario_id}",
            )
            out["judge_fracs"] = {d: verdict.fractions[d] for d in PENDING_DIMS}
            out["entail_pass"] = sum(1 for e in verdict.entailments if e.supported)
            out["entail_total"] = len(verdict.entailments)
            out["judge_ran"] = True
            if research.llm:
                out["llm_in"] = research.llm.input_tokens
                out["llm_out"] = research.llm.output_tokens
                out["llm_cost"] = research.llm.cost_usd
            if verdict.llm:
                out["judge_in"] = verdict.llm.input_tokens
                out["judge_out"] = verdict.llm.output_tokens
                out["judge_cost"] = verdict.llm.cost_usd
                out["judge_model"] = verdict.llm.model
        except (LLMUnavailable, LLMNotReproducible):
            out["completed"] = False
        except (LLMError, ResearchGenerationError, JudgeError):
            pass  # judge ran but invalid → dims stay PENDING (never full marks)
    else:
        out["completed"] = False   # no primary research → cannot judge (fail-closed)

    return out


# --------------------------------------------------------------------------- #
# Case scoring
# --------------------------------------------------------------------------- #
def run_case(
    case: EvaluationCase,
    engine_factory: Optional[EngineFactory] = None,
    citation_tamper: Optional[CitationTamper] = None,
    llm_client: Optional[LLMClient] = None,
    judge: Optional[SynthesisJudge] = None,
    law_source: Optional[object] = None,
) -> RubricResult:
    client = llm_client or default_llm_client()
    jdg = judge or default_synthesis_judge(client)
    engine = (engine_factory or SynthesisEngine)()
    law = law_source or default_law_source()

    scenarios: list[SynthesisScenario] = list(case.synthesis_scenarios)
    n = len(scenarios)

    results = [
        _run_scenario(
            sc, case_id=case.case_id, law_source=law, llm_client=client, judge=jdg,
            engine=engine, citation_tamper=citation_tamper,
        )
        for sc in scenarios
    ]

    completed = n > 0 and all(r["completed"] for r in results)
    reproducible = all(r.get("reproducible", False) for r in results if r["completed"])
    lineage_ok = all(r.get("lineage_ok", False) for r in results if r["completed"])
    measured = completed and reproducible and lineage_ok

    judge_ran = sum(1 for r in results if r["judge_ran"])
    judge_scored = judge_ran == n and n > 0 and measured

    # -- aggregate gate signals --------------------------------------------- #
    temporal_error = any(r.get("temporal_error") for r in results)
    conflict_suppressed = any(r.get("conflict_suppressed") for r in results)
    unresolved_asserted = any(r.get("unresolved_asserted") for r in results)
    authority_violated = any(r.get("authority_violated") for r in results)
    fabricated = any(r.get("fabricated") for r in results)
    new_citation_minted = any(r.get("new_citations", 0) > 0 for r in results)
    missing_warning = any(r.get("missing_warning") for r in results)

    # entailment (judge) folded into citation when scored
    entail_pass = sum(r.get("entail_pass", 0) for r in results)
    entail_total = sum(r.get("entail_total", 0) for r in results)
    entailment_unsupported = False

    cit_passed = sum(r.get("cit_passed", 0) for r in results)
    cit_total = sum(r.get("cit_total", 0) for r in results)
    if judge_scored:
        cit_passed += entail_pass
        cit_total += entail_total
        if entail_pass < entail_total:
            entailment_unsupported = True

    # -- dimension fractions ------------------------------------------------ #
    def dim_mean(key: str) -> float:
        return _safe_mean([r[key] for r in results if key in r], default=0.0)

    requirement_frac = dim_mean("requirement")
    conflict_frac = dim_mean("conflict_frac")
    citation_frac = (cit_passed / cit_total) if cit_total else 0.0
    ops_frac = 1.0 if measured else 0.0

    if not measured:
        requirement_frac = citation_frac = 0.0
        # conflict still reflects suppression/lineage truth even when unmeasured
        conflict_frac = dim_mean("conflict_frac")

    dim_fractions = {
        "requirement": requirement_frac,
        "citation": citation_frac,
        "conflict": conflict_frac,
        "ops": ops_frac,
    }
    pending = list(PENDING_DIMS)
    judge_buckets: dict[str, int] = {}
    if judge_scored:
        for d in PENDING_DIMS:
            vals = [r["judge_fracs"][d] for r in results if "judge_fracs" in r]
            dim_fractions[d] = _safe_mean(vals, default=0.0)
            judge_buckets[d] = round(dim_fractions[d] * 100)
        pending = []

    # -- hard gates --------------------------------------------------------- #
    hard_gate_codes: list[str] = []
    if not measured:
        hard_gate_codes.append("NOT_REPRODUCIBLE")            # cap 75 (lineage/replay/fixture)
    if temporal_error:
        hard_gate_codes.append("TEMPORAL_ERROR")              # cap 55
    if (fabricated or entailment_unsupported or new_citation_minted
            or conflict_suppressed or unresolved_asserted or authority_violated):
        hard_gate_codes.append("FABRICATED_CITATION")         # cap 60
    if missing_warning:
        hard_gate_codes.append("MISSING_REVIEW_WARNING")      # cap 60

    entailment_metric = f"{entail_pass}/{entail_total}" if judge_scored else "PENDING_JUDGE"
    conflict_f1s = [r.get("conflict_f1") for r in results if "conflict_f1" in r]
    applicable_denominator = 100 - sum(DIMENSION_WEIGHTS[d] for d in NA_DIMS)
    scope_note = (
        f"점수는 적용 차원 재정규화(분모 {applicable_denominator}점)입니다 — "
        f"search({DIMENSION_WEIGHTS['search']})·security({DIMENSION_WEIGHTS['security']})는 "
        f"이 slice에서 N/A(분모 제외; 검색은 per-source ①②③·격리는 slice⑥). "
        f"conflict({DIMENSION_WEIGHTS['conflict']})는 이 slice의 핵심 차원으로 측정됩니다."
    )

    metrics = {
        "ensemble_kinds": [sc.ensemble_kind.value for sc in scenarios],
        "conflict_f1": conflict_f1s,
        "conflict_dimension": round(conflict_frac, 3),
        "conflict_suppressed": conflict_suppressed,
        "unresolved_asserted": unresolved_asserted,
        "authority_violated": authority_violated,
        "abstain_correct": all(r.get("abstain_correct", False) for r in results if r["completed"]),
        "deficit_correct": all(r.get("deficit_correct", False) for r in results if r["completed"]),
        "excluded_channels_ok": all(r.get("excluded_match", False) for r in results if r["completed"]),
        "lineage_integrity": "100%" if lineage_ok else "추적불가>0",
        "new_citations_minted": new_citation_minted,
        "citation_grounding": f"{cit_passed}/{cit_total}",
        "entailment": entailment_metric,
        "fabricated_citation": (fabricated or entailment_unsupported or new_citation_minted
                                or conflict_suppressed or unresolved_asserted or authority_violated),
        "fabricated_sources": [r.get("fabricated_sources") for r in results],
        "temporal_error": temporal_error,
        "missing_review_warning": missing_warning,
        "reproducible": reproducible,
        "measured": measured,
        "judge_scored": judge_scored,
        "judge_ran": f"{judge_ran}/{n}",
        "judge_scores": judge_buckets,
        "judge_model": next((r.get("judge_model") for r in results if r.get("judge_model")), "n/a"),
        "llm_cost_usd": round(
            sum(r.get("llm_cost", 0.0) + r.get("judge_cost", 0.0) for r in results), 6
        ),
        "pending_judge_dims": pending or "none(scored)",
        "na_dimensions": NA_DIMS,
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
            "requirement": f"ORCH-008/009·applicable_basis·검토항목 frac={requirement_frac:.2f}",
            "citation": f"상속인용 grounding+entailment={cit_passed}/{cit_total} "
            f"(entail={entailment_metric}) lineage={'100%' if lineage_ok else 'BROKEN'} "
            f"new_citations={new_citation_minted}",
            "conflict": f"F1={conflict_f1s} outcome/abstain/deficit/lineage 종합 frac={conflict_frac:.2f} "
            f"(suppressed={conflict_suppressed} authority_violated={authority_violated})",
            "ops": f"measured={measured} reproducible={reproducible} lineage_ok={lineage_ok}",
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
    engine_factory: Optional[EngineFactory] = None,
    citation_tamper: Optional[CitationTamper] = None,
    llm_client: Optional[LLMClient] = None,
    judge: Optional[SynthesisJudge] = None,
    law_source: Optional[object] = None,
) -> list[RubricResult]:
    return [
        run_case(c, engine_factory=engine_factory, citation_tamper=citation_tamper,
                 llm_client=llm_client, judge=judge, law_source=law_source)
        for c in cases
    ]
