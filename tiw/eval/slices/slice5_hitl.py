"""tiw/eval/slices/slice5_hitl.py — slice ⑤ harness (CPA 검토 HITL 워크플로).

Drives the HITL state machine (src.hitl) + review-item auto-generation
(src.review_items, HALU-008) over an upstream answer (reuses the slice-① channel
so generation+judge REPLAY deterministically from the recorded fixtures), and
scores the dimensions it actually exercises:

  DETERMINISTIC:
    - requirement (6): 게이트 H1~H5 트리거·승인자(RoleAssignment)·ReviewerDecision
                       기록·ReviewHistory 변조방지 + 검토항목 자동생성(HALU-008) 커버리지
                       + (graceful degrade 시) 입력 완전성(누락 에이전트 반영, 만점 아님)
    - risk (11)      : 고위험 escalate·검토경고·과신회피·적극 절세 가드레일
    - output (9)     : reviewer actionability(검토항목)·승인흐름·고객 전달본↔내부메모 분리·
                       deliverable 생성/차단 상태 정합
    - security (14)  : approver 권한 검증(RoleAssignment)·테넌트 격리·미승인 release 차단
    - ops (2)        : 재현성(history 해시체인 검증·무오류 완료)

  JUDGE (reuse slice ①, fixture-recorded):
    - issue_spotting (10): 검토항목/답변이 gold 기대쟁점을 짚는가 (HALU-008 품질)

  N/A (분모 명시, 투명성):
    - search (9)        : HITL 단계는 검색 안 함 (slice ①/②)
    - conflict (7)      : cross-source 종합/충돌 해소는 slice ④
    - citation (12)     : 인용 grounding 은 상위 ①/② 에서 검증됨
    - legal_reasoning(20): 법리 추론 품질은 상위 ①/②/④ 에서 측정 (HITL 은 검토·승인 단계)
  → applicable denominator = 100 - (9+7+12+20) = 52.

HARD GATES (docs/09 §2):
  - TENANT_LEAK (0)         : 교차 테넌트 approver / 타사 자료 표면 → cap 0 (SEC-003)
  - UNAPPROVED_RELEASE (0)  : 승인 없이 고객 전달본/FinalMemo 생성 → cap 0 (ORCH-007/AGT-008)
  - MISSING_REVIEW_WARNING(60): 고위험 답변에 회계사 검토경고 누락 → cap 60 (HALU-009)
  - NOT_REPRODUCIBLE (75)   : gen/judge 재생 실패·history 체인 손상·예외 → fail-closed

`law_source` / `llm_client` / `judge` / `generator` / `review_item_generator` /
`deliverable_factory` are injectable ONLY so adversarial tests can feed a broken
release path, a warning-stripping generator, a cross-tenant approver, or an empty-
fixture client through this SAME scoring path and prove the harness CATCHES it.
"""

from __future__ import annotations

from datetime import timedelta
from statistics import mean
from typing import Callable, Optional

from pydantic import ValidationError

from contract.base import utc_now
from contract.cluster_a_tenancy import RoleAssignment, RoleName
from contract.cluster_h_review import ClientDeliverable, ReviewItemCategory
from contract.cluster_i_eval import EvaluationCase, HitlScenario, RubricResult, TargetKind
from rules.hard_gates import DIMENSION_WEIGHTS
from src.ai.law_data_source import LawSourceError, default_law_source
from src.ai.llm_client import (
    LLMClient,
    LLMError,
    LLMNotReproducible,
    LLMUnavailable,
    default_llm_client,
)
from src.hitl import (
    GateType,
    HitlWorkflow,
    TenantBoundaryError,
    UnapprovedReleaseError,
    required_release_gates,
)
from src.judge import Judge, JudgeError, JudgeVerdict, default_judge
from src.legal_research import (
    ResearchGenerationError,
    ResearchLiteAnswer,
    generate_research_answer,
)
from src.review_items import covered_categories, generate_review_items, has_high_risk_warning
from tiw.eval.scorer import build_rubric_result

SLICE_NO = 5
PENDING_DIMS = ["issue_spotting"]            # only judge dim slice ⑤ exercises

# dims this slice does NOT exercise (measured in ①/②/④) — explicit denominator.
NA_DIMS = ["search", "conflict", "citation", "legal_reasoning"]

ReviewGenerator = Callable[..., ResearchLiteAnswer]
# deliverable_factory(workflow, high_risk) -> Optional[ClientDeliverable]
DeliverableFactory = Callable[..., Optional[ClientDeliverable]]


def _safe_mean(values: list[float], default: float = 1.0) -> float:
    return mean(values) if values else default


def _build_roles(sc: HitlScenario) -> tuple[dict[str, RoleName], list[RoleAssignment]]:
    """Materialize the scenario's role grants as real RoleAssignments (SEC-012)."""
    roles: dict[str, RoleName] = {}
    ras: list[RoleAssignment] = []
    for i, g in enumerate(sc.role_grants):
        role_id = f"role_{g.role_name.value}_{i}"
        roles[role_id] = g.role_name
        ras.append(
            RoleAssignment(
                assignment_id=f"ra_{sc.scenario_id}_{i}",
                user_id=g.user_id,
                role_id=role_id,
                scope_type=g.scope_type,
                scope_id=g.scope_id,
                client_id=g.client_id,
                expires_at=(utc_now() - timedelta(days=1)) if g.expired else None,
            )
        )
    return roles, ras


def _default_release(wf: HitlWorkflow, high_risk: bool) -> Optional[ClientDeliverable]:
    """Production path: 승인 선행 불변식을 강제(미승인 → 예외 → 차단)."""
    deliverable = wf.produce_client_deliverable(high_risk=high_risk)
    wf.produce_final_memo(high_risk=high_risk)
    return deliverable


def _scenario_result(
    sc: HitlScenario,
    *,
    law_source,
    client: LLMClient,
    jdg: Judge,
    gen: ReviewGenerator,
    gen_items,
    deliverable_factory: DeliverableFactory,
) -> dict:
    """Run one HITL scenario and return its per-dimension sub-scores + gate signals."""
    out: dict = {"completed": True, "judge_ran": False, "issue_frac": None}

    up = sc.upstream
    high_risk = up.high_risk or sc.aggressive_tax_saving

    # 1) upstream answer — REPLAY the slice-① generation fixture (deterministic) --
    try:
        lookup = law_source.lookup_provision(up.law_name, up.article_label, up.as_of_date)
        answer = gen(
            lookup=lookup,
            question_text=up.question_text,
            client_id=sc.as_client,
            answer_run_id=f"ar_{sc.scenario_id}",
            source_answer_id=f"sa_{sc.scenario_id}",
            source_type_label=(up.gold[0].source_type if up.gold else "법률"),
            high_risk=up.high_risk,
            llm_client=client,
        )
    except (LawSourceError, LLMError, ResearchGenerationError):
        out["completed"] = False
        return out

    # 2) HALU-008 회계사 검토항목 자동생성 ----------------------------------- #
    items = gen_items(
        answer=answer,
        client_id=sc.as_client,
        matter_id=sc.matter_id,
        high_risk=high_risk,
        aggressive=sc.aggressive_tax_saving,
        unresolved_conflicts=sc.unresolved_conflicts,
        agent_gaps=sc.agent_failures,
        data_limits=sc.data_limits,
        prefix=f"ri_{sc.scenario_id}",
    )
    covered = covered_categories(items)
    warning_ok = (not high_risk) or has_high_risk_warning(items)
    out["missing_warning"] = high_risk and not has_high_risk_warning(items)

    # 3) HITL state machine -------------------------------------------------- #
    roles, ras = _build_roles(sc)
    wf = HitlWorkflow(
        client_id=sc.as_client, matter_id=sc.matter_id, draft_id=f"draft_{sc.scenario_id}",
        role_assignments=ras, roles=roles,
    )
    planned = [GateType(gp.gate) for gp in sc.gate_plan]
    decisions_recorded = 0
    for gp in sc.gate_plan:
        gate = GateType(gp.gate)
        wf.trigger(gate, reason=sc.scenario_id)
        if gp.outcome == "TIMEOUT":
            wf.timeout(gate)
            decisions_recorded += 1
            continue
        try:
            wf.decide(gate, approver_user_id=gp.approver_user_id,
                      approved=gp.approved, outcome=gp.outcome)
            decisions_recorded += 1
        except (TenantBoundaryError):
            pass  # cross-tenant approver → counted in wf.cross_tenant_attempts (leak)
        except Exception:  # noqa: BLE001 — unauthorized → counted in wf.unauthorized_attempts
            pass

    # 4) guarded release (core invariant) ------------------------------------ #
    blocked = False
    deliverable: Optional[ClientDeliverable] = None
    try:
        deliverable = deliverable_factory(wf, high_risk)
    except (UnapprovedReleaseError, TenantBoundaryError, ValidationError):
        # ValidationError = contract 레이어가 승인 proof 없는 직접 생성을 거부(P0
        # defense-in-depth) → 워크플로 가드와 동일하게 fail-closed(차단)로 처리.
        blocked = True

    leak = wf.cross_tenant_attempts
    # released without the required approval = the unapproved-release violation.
    # (반환값 기반) 미승인 상태에서 전달본이 실재 OR (감사로그 기준 P1) 미승인
    # release 시도가 ReviewHistory 에 기록됨 → side-effect+None 반환 우회도 적발.
    released_without_approval = (
        (deliverable is not None and not wf.release_authorized(high_risk=high_risk))
        or wf.released_unapproved
    )
    # cross-tenant materialized deliverable (client_id mismatch) = leak (belt & suspenders)
    if deliverable is not None and deliverable.client_id != sc.as_client:
        leak += 1

    history_ok = wf.history.verify() and len(wf.history.entries) > 0

    # 5) per-dimension sub-scores ------------------------------------------- #
    triggered_frac = (
        len([g for g in planned if g in wf.triggered]) / len(planned) if planned else 1.0
    )
    decisions_frac = (decisions_recorded / len(planned)) if planned else 1.0
    items_present = 1.0 if items else 0.0
    coverage_frac = (
        len(set(sc.gold_review_categories) & covered) / len(set(sc.gold_review_categories))
        if sc.gold_review_categories else 1.0
    )
    process_completeness = _safe_mean(
        [triggered_frac, decisions_frac, 1.0 if history_ok else 0.0,
         items_present, coverage_frac]
    )
    # graceful degrade (ORCH-006): 누락 에이전트만큼 입력 완전성 차감 (분모=전체 로스터)
    if sc.expected_agents:
        input_completeness = max(
            0.0,
            (len(sc.expected_agents) - len(sc.agent_failures)) / len(sc.expected_agents),
        )
    else:
        input_completeness = 1.0
    # min: 가장 약한 완전성이 requirement 를 gates — graceful degrade 는 부분 결과(만점 아님)
    requirement_frac = min(process_completeness, input_completeness)

    # risk: 고위험 처리 + 과신회피 + 적극 절세 가드레일
    if high_risk:
        h4_handled = (
            GateType.H4_HIGH_RISK in wf.triggered
            and wf.approved_gate(GateType.H4_HIGH_RISK)
            and warning_ok
        )
        high_risk_handled = 1.0 if h4_handled else 0.0
    else:
        high_risk_handled = 1.0
    interp = answer.certainty.strip() in ("해석", "interpretation") or answer.abstained
    has_interp_item = any(
        i.category in (ReviewItemCategory.INTERPRETATION, ReviewItemCategory.UNCERTAIN)
        for i in items
    )
    overconfidence_avoided = 1.0 if (not interp or has_interp_item) else 0.0
    if sc.aggressive_tax_saving:
        aggressive_guardrail = 1.0 if any(
            i.category is ReviewItemCategory.HIGH_RISK_AGGRESSIVE
            and "방어논리" in i.description and "과세" in i.description
            for i in items
        ) else 0.0
    else:
        aggressive_guardrail = 1.0
    risk_frac = _safe_mean([high_risk_handled, overconfidence_avoided, aggressive_guardrail])

    # output: reviewer actionability + 승인흐름 + 분리 + deliverable 상태
    reviewer_actionable = 1.0 if all(i.description and i.category for i in items) and items else 0.0
    release_required = required_release_gates(high_risk)
    approval_flow_complete = 1.0 if all(g in wf.decisions for g in release_required) else 0.0
    if sc.expect_blocked:
        deliverable_state_correct = 1.0 if blocked else 0.0
    elif sc.expect_deliverable:
        deliverable_state_correct = 1.0 if (deliverable is not None and not blocked) else 0.0
    else:
        deliverable_state_correct = 1.0
    separation_ok = 1.0 if (deliverable is None or deliverable.excludes_internal_strategy) else 0.0
    output_frac = _safe_mean(
        [reviewer_actionable, approval_flow_complete, deliverable_state_correct, separation_ok]
    )

    # security: approver 권한 + 격리 + 미승인 release 차단 + scope 필수
    approver_authorized = 1.0 if wf.unauthorized_attempts == 0 else 0.0
    no_leak = 1.0 if leak == 0 else 0.0
    release_blocked = 1.0 if not released_without_approval else 0.0
    scope_mandatory = 1.0  # structural: client_id/matter_id required on every record
    security_frac = _safe_mean([approver_authorized, no_leak, release_blocked, scope_mandatory])

    out.update(
        completed=True,
        requirement=requirement_frac,
        risk=risk_frac,
        output=output_frac,
        security=security_frac,
        history_ok=history_ok,
        leak=leak,
        released_without_approval=released_without_approval,
        blocked=blocked,
        deliverable_produced=deliverable is not None,
        covered_categories=sorted(covered),
        degraded=bool(sc.agent_failures),
        review_item_count=len(items),
    )

    # 6) JUDGE issue_spotting (reuse slice ①; fail-closed) ------------------- #
    try:
        verdict: JudgeVerdict = jdg.score(
            question_text=up.question_text,
            answer=answer,
            provision_quote=lookup.provision_version.text,
            gold_issues=list(up.gold_issues),
            tag=f"judge_{sc.scenario_id}",
        )
        out["issue_frac"] = verdict.fractions["issue_spotting"]
        out["judge_ran"] = True
        if answer.llm:
            out["llm_in"] = answer.llm.input_tokens
            out["llm_out"] = answer.llm.output_tokens
            out["llm_cost"] = answer.llm.cost_usd
        if verdict.llm:
            out["judge_in"] = verdict.llm.input_tokens
            out["judge_out"] = verdict.llm.output_tokens
            out["judge_cost"] = verdict.llm.cost_usd
            out["judge_model"] = verdict.llm.model
    except (LLMUnavailable, LLMNotReproducible):
        # missing/tampered judge fixture = reproducibility failure → NOT_REPRODUCIBLE
        out["completed"] = False
    except (LLMError, ResearchGenerationError, JudgeError):
        pass  # judge ran but invalid → issue_spotting stays PENDING (never full marks)

    return out


def run_case(
    case: EvaluationCase,
    law_source: Optional[object] = None,
    llm_client: Optional[LLMClient] = None,
    judge: Optional[Judge] = None,
    generator: Optional[ReviewGenerator] = None,
    review_item_generator=None,
    deliverable_factory: Optional[DeliverableFactory] = None,
) -> RubricResult:
    law = law_source or default_law_source()
    client = llm_client or default_llm_client()
    jdg = judge or default_judge(client)
    gen = generator or generate_research_answer
    gen_items = review_item_generator or generate_review_items
    release = deliverable_factory or _default_release

    scenarios: list[HitlScenario] = list(case.hitl_scenarios)
    n = len(scenarios)

    results = [
        _scenario_result(
            sc, law_source=law, client=client, jdg=jdg, gen=gen, gen_items=gen_items,
            deliverable_factory=release,
        )
        for sc in scenarios
    ]

    completed = all(r["completed"] for r in results) and n > 0
    history_ok_all = all(r.get("history_ok", False) for r in results if r["completed"])
    measured = completed and history_ok_all

    total_leak = sum(r.get("leak", 0) for r in results)
    unapproved_release = any(r.get("released_without_approval", False) for r in results)
    missing_warning = any(r.get("missing_warning", False) for r in results)

    judge_ran = sum(1 for r in results if r["judge_ran"])
    judge_scored = judge_ran == n and n > 0 and measured

    # -- dimension fractions (mean over scenarios) ------------------------- #
    def dim(name: str) -> float:
        vals = [r[name] for r in results if name in r]
        return _safe_mean(vals, default=0.0)

    requirement_frac = dim("requirement")
    risk_frac = dim("risk")
    output_frac = dim("output")
    security_frac = dim("security")
    ops_frac = 1.0 if measured else 0.0

    if not measured:
        requirement_frac = risk_frac = output_frac = 0.0
        # security still reflects leakage/authorization truth even when unmeasured
        sec_vals = [r["security"] for r in results if "security" in r]
        security_frac = _safe_mean(sec_vals, default=0.0)

    dim_fractions = {
        "requirement": requirement_frac,
        "risk": risk_frac,
        "output": output_frac,
        "security": security_frac,
        "ops": ops_frac,
    }
    pending = list(PENDING_DIMS)
    issue_bucket: Optional[int] = None
    if judge_scored:
        issue_vals = [r["issue_frac"] for r in results if r.get("issue_frac") is not None]
        issue_frac = _safe_mean(issue_vals, default=0.0)
        dim_fractions["issue_spotting"] = issue_frac
        issue_bucket = round(issue_frac * 100)
        pending = []

    # -- hard gates -------------------------------------------------------- #
    hard_gate_codes: list[str] = []
    if total_leak > 0:
        hard_gate_codes.append("TENANT_LEAK")             # cap 0 (SEC-003)
    if unapproved_release:
        hard_gate_codes.append("UNAPPROVED_RELEASE")      # cap 0 (ORCH-007/AGT-008)
    if missing_warning:
        hard_gate_codes.append("MISSING_REVIEW_WARNING")  # cap 60 (HALU-009)
    if not measured:
        hard_gate_codes.append("NOT_REPRODUCIBLE")        # cap 75

    applicable_denominator = 100 - sum(DIMENSION_WEIGHTS[d] for d in NA_DIMS)
    scope_note = (
        f"점수는 적용 차원 재정규화(분모 {applicable_denominator}점)입니다 — "
        f"search({DIMENSION_WEIGHTS['search']})·conflict({DIMENSION_WEIGHTS['conflict']})·"
        f"citation({DIMENSION_WEIGHTS['citation']})·legal_reasoning({DIMENSION_WEIGHTS['legal_reasoning']})는 "
        f"이 slice에서 N/A(분모 제외)이며 slice①/②/④에서 측정됩니다."
    )

    metrics = {
        "scenarios": n,
        "leakage_count": total_leak,
        "unapproved_release": unapproved_release,
        "missing_review_warning": missing_warning,
        "degraded_scenarios": sum(1 for r in results if r.get("degraded")),
        "deliverables_produced": sum(1 for r in results if r.get("deliverable_produced")),
        "blocked": sum(1 for r in results if r.get("blocked")),
        "measured": measured,
        "reproducible": history_ok_all,
        "judge_scored": judge_scored,
        "judge_ran": f"{judge_ran}/{n}",
        "issue_spotting_bucket": issue_bucket,
        "judge_model": next((r.get("judge_model") for r in results if r.get("judge_model")), "n/a"),
        "review_items": [r.get("review_item_count") for r in results],
        "covered_categories": [r.get("covered_categories") for r in results],
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
            "requirement": f"gates/decisions/history/items/coverage + 입력완전성(degrade) "
            f"frac={requirement_frac:.2f}",
            "risk": f"고위험 escalate·과신회피·적극절세 가드레일 frac={risk_frac:.2f}",
            "output": f"검토항목·승인흐름·고객전달본↔내부메모 분리·deliverable 상태 frac={output_frac:.2f}",
            "security": f"approver 권한(RoleAssignment)·격리(leak={total_leak})·"
            f"미승인 release 차단 frac={security_frac:.2f}",
            "ops": f"measured={measured} history_chain={history_ok_all}",
            "issue_spotting": f"judge bucket={issue_bucket}"
            if judge_scored else "PENDING_JUDGE — judge/CPA 미연결 (보류)",
        },
        hard_gate_codes=hard_gate_codes,
        metrics=metrics,
        pending_dimensions=pending,
    )


def run_cases(
    cases: list[EvaluationCase],
    law_source: Optional[object] = None,
    llm_client: Optional[LLMClient] = None,
    judge: Optional[Judge] = None,
    generator: Optional[ReviewGenerator] = None,
    review_item_generator=None,
    deliverable_factory: Optional[DeliverableFactory] = None,
) -> list[RubricResult]:
    return [
        run_case(
            c, law_source=law_source, llm_client=llm_client, judge=judge,
            generator=generator, review_item_generator=review_item_generator,
            deliverable_factory=deliverable_factory,
        )
        for c in cases
    ]
