"""slice ⑤ CPA HITL 워크플로 — 결정적 테스트 (실키/네트워크 불필요, fixture 재생).

핵심(docs/03 §5 H1~H5, ORCH-007 / AGT-008 / OUT-004, HALU-008/009):
  - HITL 상태기계(src.hitl): 게이트 H1~H5 트리거·승인자(RoleAssignment, SEC-012)·
    ReviewerDecision 기록·ReviewHistory **해시체인 변조방지**(SEC-017).
  - CORE INVARIANT: 승인(ReviewerDecision) 없이 FinalMemo/고객 전달본 생성 금지 —
    미승인 → UnapprovedReleaseError(차단). 교차 테넌트 approver → TenantBoundaryError.
  - 회계사 검토항목 자동생성(HALU-008) + 고위험·적극 절세 검토경고(HALU-009).
  - 하버스 정직성(anti-gaming)을 *동일 채점 경로*에서 적발:
      ① 승인 없이 release 시도(우회 factory) → UNAPPROVED_RELEASE(cap 0)
      ② 고위험 검토경고 누락(경고 strip 생성기) → MISSING_REVIEW_WARNING(cap 60)
      ③ 무권한/교차테넌트 approver → 거부(예외) / TENANT_LEAK(cap 0)
      ④ 에이전트 장애 → graceful degrade(부분 결과·누락 trace, 만점 아님)
      ⑤ judge/생성 미가동(측정 불가) → NOT_REPRODUCIBLE(cap 75)·보류(fail-closed)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from contract.base import ScopeType
from contract.cluster_a_tenancy import RoleAssignment, RoleName
from contract.cluster_h_review import (
    ClientDeliverable,
    FinalMemo,
    GateType,
    ReleaseAuthorization,
    ReviewItemCategory,
    ReviewerDecision,
)
from contract.cluster_i_eval import EvaluationCase
from src.ai.llm_client import (
    LLMClient,
    LLMConfig,
    LLMNotReproducible,
    ReplayLLMTransport,
)
from src.hitl import (
    ApproverAuthorizationError,
    HitlWorkflow,
    ReviewHistoryLog,
    TenantBoundaryError,
    UnapprovedReleaseError,
    authorize_approver,
    required_release_gates,
)
from src.legal_research import ResearchLiteAnswer, generate_research_answer
from src.review_items import (
    generate_review_items,
    has_high_risk_warning,
)
from src.ai.law_data_source import default_law_source
from tiw.eval.loader import load_hidden_cases, load_public_cases
from tiw.eval.runner import run_slice
from tiw.eval.slices.slice5_hitl import run_case


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _public_case(case_id: str) -> EvaluationCase:
    for c in load_public_cases(5):
        if c.case_id == case_id:
            return c
    raise AssertionError(f"{case_id} not found")


def _build_wf(client_id, matter_id, grants) -> HitlWorkflow:
    """Build a HitlWorkflow with materialized RoleAssignments (SEC-012). Each grant is
    ``(user_id, RoleName)`` or ``(user_id, RoleName, client_id)`` for a cross-tenant grant."""
    roles: dict[str, RoleName] = {}
    ras: list[RoleAssignment] = []
    for i, grant in enumerate(grants):
        uid, role = grant[0], grant[1]
        grant_client = grant[2] if len(grant) > 2 else client_id
        rid = f"role_{i}"
        roles[rid] = role
        ras.append(
            RoleAssignment(
                assignment_id=f"ra_{i}", user_id=uid, role_id=rid,
                scope_type=ScopeType.MATTER, scope_id=matter_id, client_id=grant_client,
            )
        )
    return HitlWorkflow(
        client_id=client_id, matter_id=matter_id, draft_id="d1",
        role_assignments=ras, roles=roles,
    )


def _answer(client_id="client_A") -> ResearchLiteAnswer:
    """A replayed channel-① answer (제25조 2024) for review-item tests (no network)."""
    src = default_law_source()
    from datetime import date

    lookup = src.lookup_provision("법인세법", "제25조", date(2024, 1, 1))
    return generate_research_answer(
        lookup=lookup,
        question_text=(
            "법인세법상 기업업무추진비(접대비) 손금불산입의 근거 조문은 무엇이고, "
            "2024 사업연도 기준 유효 버전은?"
        ),
        client_id=client_id, answer_run_id="ar",
        source_answer_id="sa_S5-PUB-001_S5-PUB-001-s1", high_risk=False,
    )


# --------------------------------------------------------------------------- #
# CORE INVARIANT: 승인 없이 FinalMemo/고객 전달본 생성 금지 (ORCH-007/AGT-008/OUT-004)
# --------------------------------------------------------------------------- #
def test_unapproved_final_memo_and_deliverable_blocked():
    wf = _build_wf("client_A", "matter_A1", [("u_cpa", RoleName.CPA), ("u_rev", RoleName.REVIEWER)])
    # 아무 게이트도 승인 안 됨 → 둘 다 차단
    with pytest.raises(UnapprovedReleaseError):
        wf.produce_final_memo(high_risk=False)
    with pytest.raises(UnapprovedReleaseError):
        wf.produce_client_deliverable(high_risk=False)


def test_h5_approval_unlocks_release_low_risk():
    wf = _build_wf("client_A", "matter_A1", [("u_cpa", RoleName.CPA), ("u_rev", RoleName.REVIEWER)])
    wf.trigger(GateType.H1_INTAKE)
    wf.decide(GateType.H1_INTAKE, approver_user_id="u_cpa", approved=True)
    wf.trigger(GateType.H5_APPROVAL)
    wf.decide(GateType.H5_APPROVAL, approver_user_id="u_rev", approved=True)
    # H5 승인 선행 → 전달본/최종본 생성 가능 (저위험은 H5만)
    deliverable = wf.produce_client_deliverable(high_risk=False)
    memo = wf.produce_final_memo(high_risk=False)
    assert deliverable.approved and deliverable.excludes_internal_strategy
    assert memo.approved and memo.client_id == "client_A"


def test_high_risk_requires_both_h4_and_h5():
    # 고위험 release 는 H4(고위험 검토)+H5(사인오프) 둘 다 필요(docs/03 §5 불변)
    assert required_release_gates(high_risk=True) == [GateType.H4_HIGH_RISK, GateType.H5_APPROVAL]
    assert required_release_gates(high_risk=False) == [GateType.H5_APPROVAL]

    wf = _build_wf("client_A", "matter_A1", [("u_cpa", RoleName.CPA), ("u_rev", RoleName.REVIEWER)])
    for g in (GateType.H1_INTAKE, GateType.H4_HIGH_RISK, GateType.H5_APPROVAL):
        wf.trigger(g)
    wf.decide(GateType.H4_HIGH_RISK, approver_user_id="u_rev", approved=True)
    # H4 만 승인, H5 미승인 → 고위험 전달본 여전히 차단
    assert wf.missing_release_gates(high_risk=True) == [GateType.H5_APPROVAL]
    with pytest.raises(UnapprovedReleaseError):
        wf.produce_client_deliverable(high_risk=True)
    # H5 까지 승인하면 생성 가능
    wf.decide(GateType.H5_APPROVAL, approver_user_id="u_rev", approved=True)
    assert wf.release_authorized(high_risk=True)
    assert wf.produce_client_deliverable(high_risk=True).approved


# --------------------------------------------------------------------------- #
# approver 권한 검증 (SEC-012) + 교차 테넌트 (SEC-003) + 만료 (SEC-013)
# --------------------------------------------------------------------------- #
def test_unauthorized_approver_refused():
    wf = _build_wf("client_A", "matter_A1", [("u_cpa", RoleName.CPA), ("u_rev", RoleName.REVIEWER)])
    wf.trigger(GateType.H5_APPROVAL)
    # 권한 없는 사용자가 H5 승인 시도 → 거부(fail-closed), 게이트 미승인 유지
    with pytest.raises(ApproverAuthorizationError):
        wf.decide(GateType.H5_APPROVAL, approver_user_id="u_nobody", approved=True)
    assert not wf.approved_gate(GateType.H5_APPROVAL)
    assert wf.unauthorized_attempts == 1


def test_cross_tenant_approver_refused():
    # 올바른 역할/스코프지만 '다른 client' 의 approver → 교차 테넌트 거부(leak signal)
    wf = _build_wf(
        "client_A", "matter_A1",
        [("u_cpa", RoleName.CPA), ("u_other", RoleName.REVIEWER, "client_OTHER")],
    )
    wf.trigger(GateType.H5_APPROVAL)
    with pytest.raises(TenantBoundaryError):
        wf.decide(GateType.H5_APPROVAL, approver_user_id="u_other", approved=True)
    assert wf.cross_tenant_attempts == 1
    assert not wf.approved_gate(GateType.H5_APPROVAL)


def test_expired_grant_revokes_authorization():
    from datetime import timedelta

    from contract.base import utc_now

    expired = RoleAssignment(
        assignment_id="ra_x", user_id="u_rev", role_id="role_rev",
        scope_type=ScopeType.MATTER, scope_id="matter_A1", client_id="client_A",
        expires_at=utc_now() - timedelta(days=1),
    )
    with pytest.raises(ApproverAuthorizationError):
        authorize_approver(
            user_id="u_rev", required_role=RoleName.REVIEWER, matter_id="matter_A1",
            client_id="client_A", role_assignments=[expired], roles={"role_rev": RoleName.REVIEWER},
        )


# --------------------------------------------------------------------------- #
# ReviewHistory 변조방지 (SEC-017) 해시체인
# --------------------------------------------------------------------------- #
def test_review_history_hash_chain_tamper_evident():
    log = ReviewHistoryLog("client_A", "matter_A1")
    log.append(event="H1 트리거", gate=GateType.H1_INTAKE, actor="u_cpa")
    log.append(event="H1 승인", gate=GateType.H1_INTAKE, actor="u_cpa")
    log.append(event="H5 승인", gate=GateType.H5_APPROVAL, actor="u_rev")
    assert log.verify() is True
    # 중간 이벤트 변조 → 체인 깨짐(삭제·수정 감지)
    log.entries[1].event = "H1 반려(위조)"
    assert log.verify() is False


# --------------------------------------------------------------------------- #
# HALU-008 검토항목 자동생성 + HALU-009 고위험 검토경고
# --------------------------------------------------------------------------- #
def test_review_items_autogenerated_halu008():
    items = generate_review_items(
        answer=_answer(), client_id="client_A", matter_id="matter_A1",
        high_risk=False, aggressive=False,
        agent_gaps=["판례검색"], data_limits=["전기 신고서 미확보"],
    )
    cats = {i.category for i in items}
    # 시점 가정·근거확인·자료한계(에이전트 장애 포함)는 결정적으로 도출됨
    assert ReviewItemCategory.TEMPORAL_ASSUMPTION in cats
    assert ReviewItemCategory.WEAK_BASIS in cats
    assert ReviewItemCategory.DATA_LIMIT in cats
    assert all(i.client_id == "client_A" for i in items)


def test_high_risk_aggressive_warning_present_halu009():
    items = generate_review_items(
        answer=_answer(), client_id="client_A", matter_id="matter_A1",
        high_risk=True, aggressive=True,
    )
    assert has_high_risk_warning(items) is True
    hi = [i for i in items if i.category is ReviewItemCategory.HIGH_RISK_AGGRESSIVE]
    assert hi and hi[0].requires_warning
    # 적극 절세 가드레일: 과세논리·방어논리 양면 적시(AGT-008)
    assert "방어논리" in hi[0].description and "과세" in hi[0].description


# --------------------------------------------------------------------------- #
# 하버스 end-to-end (slice ⑤) — judge 채점 + 완료게이트
# --------------------------------------------------------------------------- #
def test_slice5_harness_scored_and_passes():
    report = run_slice(5)
    assert report.case_results
    assert report.public_count == 2 and report.hidden_count == 1
    assert not report.hard_gate_hit
    assert report.pending is False          # issue_spotting judge 채점됨(보류 아님)
    assert report.passed is True
    assert report.score >= 90
    assert report.completion_score == report.score
    for r in report.case_results:
        assert r.metrics["reproducible"] is True
        assert r.metrics["judge_scored"] is True
        # N/A 분모 투명성: 미행사 차원은 명시적으로 제외
        assert r.metrics["applicable_denominator"] == 52
        assert set(r.metrics["na_dimensions"]) == {"search", "conflict", "citation", "legal_reasoning"}


def test_slice5_blocked_and_degrade_measured_honestly():
    # gold 케이스가 차단(미승인 H5)·graceful degrade 를 정직 실측한다.
    pub2 = run_case(_public_case("S5-PUB-002"))
    assert pub2.metrics["degraded_scenarios"] == 1        # 에이전트 장애 부분 결과
    assert pub2.metrics["deliverables_produced"] == 2
    # graceful degrade → requirement 만점 아님(입력 완전성 차감)
    req = next(s for s in pub2.dimension_scores if s.dimension == "requirement")
    assert req.score is not None and req.score < 100


# --------------------------------------------------------------------------- #
# 정직성 ① (P0): 승인 proof 없이 FinalMemo/고객 전달본 직접 생성 → contract 거부
#   (워크플로 missing_release_gates 게이트를 우회한 직접 생성도 막는 defense-in-depth)
# --------------------------------------------------------------------------- #
def _approved_h5_decision(
    client_id="client_A", matter_id="matter_A1", gate="H5", decision_id="dec_ok"
) -> ReviewerDecision:
    return ReviewerDecision(
        decision_id=decision_id, review_id="rev_ok", approved=True,
        reviewer_user_id="u_rev", gate=gate, outcome="APPROVED",
        client_id=client_id, matter_id=matter_id,
    )


def test_contract_blocks_direct_unapproved_construction():
    # 승인 proof(ReleaseAuthorization) 자체가 없으면 필수 필드 누락 → ValidationError.
    with pytest.raises(ValidationError):
        ClientDeliverable(
            deliverable_id="cd_forged", draft_id="d_forged", decision_id="forged",
            approved=True, excludes_internal_strategy=True,
            client_id="client_A", matter_id="matter_A1",
        )
    with pytest.raises(ValidationError):
        FinalMemo(
            final_memo_id="fm_forged", draft_id="d_forged", decision_id="forged",
            approved=True, client_id="client_A", matter_id="matter_A1",
        )


def test_contract_rejects_insufficient_or_mismatched_proof():
    # (a) 저위험인데 필수 H5 승인이 없는 proof → ReleaseAuthorization 자체가 거부
    with pytest.raises(ValidationError):
        ReleaseAuthorization(
            high_risk=False, client_id="client_A", matter_id="matter_A1",
            decisions=[_approved_h5_decision(gate="H1")],     # H5 누락
        )
    # (b) 고위험인데 H4 누락 → 거부(저위험 H5 / 고위험 H4+H5)
    with pytest.raises(ValidationError):
        ReleaseAuthorization(
            high_risk=True, client_id="client_A", matter_id="matter_A1",
            decisions=[_approved_h5_decision(gate="H5")],     # H4 누락
        )
    # (c) 교차 테넌트 결정이 섞인 proof → 거부(SEC-003)
    with pytest.raises(ValidationError):
        ReleaseAuthorization(
            high_risk=False, client_id="client_A", matter_id="matter_A1",
            decisions=[_approved_h5_decision(client_id="client_OTHER")],
        )
    # (d) 유효 proof 라도 산출물과 decision_id binding 불일치 → 거부
    good = ReleaseAuthorization(
        high_risk=False, client_id="client_A", matter_id="matter_A1",
        decisions=[_approved_h5_decision(decision_id="dec_h5")],
    )
    with pytest.raises(ValidationError):
        ClientDeliverable(
            deliverable_id="cd1", draft_id="d1", decision_id="WRONG",   # H5 와 불일치
            approved=True, excludes_internal_strategy=True,
            client_id="client_A", matter_id="matter_A1", release_proof=good,
        )
    # 정상 binding(decision_id == H5 사인오프) → 생성 가능(우회 아님·정상경로 검증)
    ok = ClientDeliverable(
        deliverable_id="cd1", draft_id="d1", decision_id="dec_h5",
        approved=True, excludes_internal_strategy=True,
        client_id="client_A", matter_id="matter_A1", release_proof=good,
    )
    assert ok.approved and ok.release_proof.signoff_decision_id == "dec_h5"


def _bypass_release(wf: HitlWorkflow, high_risk: bool) -> ClientDeliverable:
    """승인 proof 없이 전달본을 강제 생성하려는 우회 factory — 이제 ValidationError."""
    return ClientDeliverable(
        deliverable_id="cd_forged", draft_id="d_forged", decision_id="forged",
        approved=True, excludes_internal_strategy=True,
        client_id=wf.client_id, matter_id=wf.matter_id,
    )


def test_harness_blocks_bypass_factory_fail_closed():
    # 우회 factory 를 하버스에 주입해도 contract 거부(ValidationError) → 차단 처리되어
    # 미승인 전달본이 실재(escape)하지 못한다(하버스도 fail-closed).
    case = _public_case("S5-PUB-001").model_copy(deep=True)
    sc = case.hitl_scenarios[0]
    sc.gate_plan = [gp for gp in sc.gate_plan if gp.gate != "H5"]      # H5 미승인
    res = run_case(case, deliverable_factory=_bypass_release)
    assert res.metrics["deliverables_produced"] == 0                  # escape 없음
    assert res.metrics["blocked"] >= 1


# --------------------------------------------------------------------------- #
# 정직성 ①' (P1): side-effect 로 만들고 None 반환 → 감사로그(RELEASE_ATTEMPT) 적발
# --------------------------------------------------------------------------- #
def _side_effect_release(wf: HitlWorkflow, high_risk: bool):
    """미승인 상태에서 release 를 side-effect(의무 감사이벤트)로 시도하되 None 을
    반환해 *반환값 기반* 검출을 회피하는 적대 factory. 감사로그가 적발한다(P1)."""
    wf.record_release(
        kind="고객 전달본(side-effect)", deliverable_id="cd_sneak", high_risk=high_risk
    )
    return None


def test_harness_catches_unapproved_release_via_audit_log():
    case = _public_case("S5-PUB-001").model_copy(deep=True)
    sc = case.hitl_scenarios[0]
    sc.gate_plan = [gp for gp in sc.gate_plan if gp.gate != "H5"]      # H5 미승인
    res = run_case(case, deliverable_factory=_side_effect_release)
    # 반환값은 None 이지만, 감사로그(released_unapproved)로 미승인 release 적발
    assert res.metrics["unapproved_release"] is True
    assert any(f.code == "UNAPPROVED_RELEASE" for f in res.failure_modes)
    assert res.cap == 0 and res.total <= 0          # 미승인 release = 누수급(cap 0)


# --------------------------------------------------------------------------- #
# 정직성 ②: 고위험 검토경고 누락(strip 생성기) → MISSING_REVIEW_WARNING (cap 60)
# --------------------------------------------------------------------------- #
def _strip_warning_items(**kwargs):
    # 고위험인데 검토경고(HIGH_RISK_AGGRESSIVE)를 누락시키는 적대 생성기
    return generate_review_items(**{**kwargs, "high_risk": False, "aggressive": False})


def test_harness_catches_missing_review_warning():
    # PUB-002 s1 은 고위험(적극 절세) — 경고를 누락하면 게이트가 떠야 한다.
    res = run_case(_public_case("S5-PUB-002"), review_item_generator=_strip_warning_items)
    assert res.metrics["missing_review_warning"] is True
    assert any(f.code == "MISSING_REVIEW_WARNING" for f in res.failure_modes)
    assert res.total <= 60


# --------------------------------------------------------------------------- #
# 정직성 ③: 교차 테넌트 approver → TENANT_LEAK (cap 0), 전달본 차단
# --------------------------------------------------------------------------- #
def test_harness_catches_cross_tenant_approver():
    case = _public_case("S5-PUB-001").model_copy(deep=True)
    sc = case.hitl_scenarios[0]
    # H5 Reviewer 를 '다른 client' 의 approver 로 위조 → 교차 테넌트 시도
    for g in sc.role_grants:
        if g.role_name == RoleName.REVIEWER:
            g.client_id = "client_OTHER"
    res = run_case(case)
    assert res.metrics["leakage_count"] >= 1
    assert any(f.code == "TENANT_LEAK" for f in res.failure_modes)
    assert res.cap == 0 and res.total <= 0
    assert res.metrics["blocked"] >= 1              # 교차 테넌트 → 전달본 차단


# --------------------------------------------------------------------------- #
# 정직성 ④: graceful degrade (에이전트 장애) → 부분 결과·누락 trace (만점 아님)
# --------------------------------------------------------------------------- #
def test_graceful_degrade_partial_not_full_marks():
    # PUB-002 s2 의 판례검색 에이전트 장애 → DATA_LIMIT 검토항목 + 입력 완전성 차감.
    res = run_case(_public_case("S5-PUB-002"))
    assert res.metrics["degraded_scenarios"] == 1
    covered = res.metrics["covered_categories"]
    assert any("DATA_LIMIT" in (c or []) for c in covered)   # 누락 분석 trace 검토항목
    req = next(s for s in res.dimension_scores if s.dimension == "requirement")
    assert req.score < 100                                   # 부분 결과 → 만점 아님
    assert not res.hard_gate_hit                             # 정상 처리(하드게이트 아님)


# --------------------------------------------------------------------------- #
# 정직성 ⑤: judge/생성 미가동(측정 불가) → NOT_REPRODUCIBLE (cap 75)·보류
# --------------------------------------------------------------------------- #
def test_fail_closed_when_llm_fixtures_missing(tmp_path):
    empty = LLMClient(config=LLMConfig.from_vendors(), transport=ReplayLLMTransport(tmp_path))
    res = run_case(_public_case("S5-PUB-001"), llm_client=empty)
    assert res.metrics["measured"] is False
    assert any(f.code == "NOT_REPRODUCIBLE" for f in res.failure_modes)
    assert res.total < 90
    assert res.has_pending and "issue_spotting" in res.pending_dimensions


class _BrokenJudge:
    """녹화 fixture 변조(해시 불일치)를 모사하는 judge — 재생 거부(fail-closed)."""

    def score(self, **kwargs):
        raise LLMNotReproducible("tampered judge fixture (test)")


def test_fail_closed_when_judge_replay_tampered():
    res = run_case(_public_case("S5-PUB-001"), judge=_BrokenJudge())
    assert res.metrics["measured"] is False
    assert any(f.code == "NOT_REPRODUCIBLE" for f in res.failure_modes)
    assert res.total < 90


# --------------------------------------------------------------------------- #
# anti-gaming: hidden/public 분리 로딩 + slice 필터
# --------------------------------------------------------------------------- #
def test_public_hidden_separate_and_slice_filtered():
    pub = load_public_cases(5)
    hid = load_hidden_cases(5)
    assert {c.case_id for c in pub} == {"S5-PUB-001", "S5-PUB-002"}
    assert {c.case_id for c in hid} == {"S5-HID-001"}
    assert all(c.slice == 5 for c in pub + hid)
