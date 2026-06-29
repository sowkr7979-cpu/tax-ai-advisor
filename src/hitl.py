"""src/hitl.py — HITL 게이트 상태기계 (docs/03 §5, ORCH-007 / AGT-008 / OUT-004).

The HITL operating contract: every gate H1~H5 binds a **trigger condition, an
approver ROLE (evaluated via RoleAssignment — SEC-012, not a global role), a
timeout, an escalation role, and an audit record**. Decisions are recorded as
``ReviewerDecision``; every transition (trigger·approve·reject·timeout·escalate)
is appended to a **hash-chained ``ReviewHistory``** so a deleted/edited event
breaks the chain (tamper-evident, SEC-017).

CORE INVARIANT (코드로 강제): a ``FinalMemo`` / 고객 전달본(``ClientDeliverable``)
cannot be produced without the required approving decision — H5 always, plus H4
for a high-risk answer. An attempt without it raises ``UnapprovedReleaseError``
(미승인 고객본 생성 차단). A cross-tenant approver raises ``TenantBoundaryError``.

This module is deterministic (no LLM, no network).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from typing import Optional

from contract.base import ScopeType, utc_now
from contract.cluster_a_tenancy import RoleAssignment, RoleName
from contract.cluster_h_review import (
    ClientDeliverable,
    FinalMemo,
    GateType,
    ReleaseAuthorization,
    ReviewerDecision,
    ReviewHistory,
)


# --------------------------------------------------------------------------- #
# Errors (fail-closed surface)
# --------------------------------------------------------------------------- #
class HitlError(RuntimeError):
    """Base for HITL workflow errors."""


class ApproverAuthorizationError(HitlError):
    """The acting user does not hold the gate's required role in the matter scope
    (SEC-012). The gate is NOT approved — fail-closed."""


class UnapprovedReleaseError(HitlError):
    """A FinalMemo / 고객 전달본 was requested without the required gate approval
    (ORCH-007 / AGT-008 / OUT-004) — blocked."""


class TenantBoundaryError(HitlError):
    """An approver scoped to a DIFFERENT client tried to act (cross-tenant) — a
    tenant-boundary violation (SEC-003)."""


# --------------------------------------------------------------------------- #
# Gate specs (docs/03 §5)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GateSpec:
    gate: GateType
    approver_role: RoleName
    escalation_role: Optional[RoleName]
    timeout_required: bool                 # 확정 전 필수 / SLA
    blocks_client_deliverable: bool        # H4 (high-risk) / H5 (sign-off)
    evidence_label: str


# docs/03 §5 table. (CPA→Reviewer means the *approver* is CPA, escalating to
# Reviewer; H4/H5 are owned by Reviewer escalating to Manager.)
HITL_GATES: dict[GateType, GateSpec] = {
    GateType.H1_INTAKE: GateSpec(
        GateType.H1_INTAKE, RoleName.CPA, None, False, False,
        "검토범위·결손·한계 고지문",
    ),
    GateType.H2_CALC: GateSpec(
        GateType.H2_CALC, RoleName.CPA, RoleName.REVIEWER, True, False,
        "계산로그·플래그 항목",
    ),
    GateType.H3_CONFLICT: GateSpec(
        GateType.H3_CONFLICT, RoleName.CPA, RoleName.REVIEWER, True, False,
        "충돌소스·시점 가정",
    ),
    GateType.H4_HIGH_RISK: GateSpec(
        GateType.H4_HIGH_RISK, RoleName.REVIEWER, RoleName.MANAGER, True, True,
        "과세·방어논리·검토경고",
    ),
    GateType.H5_APPROVAL: GateSpec(
        GateType.H5_APPROVAL, RoleName.REVIEWER, RoleName.MANAGER, True, True,
        "전 게이트 통과·최종본",
    ),
}


def required_release_gates(high_risk: bool) -> list[GateType]:
    """Gates whose approval is a precondition of a 고객 전달본 (H5 always; H4 if
    the answer is high-risk — docs/03 §5 불변)."""
    gates = [GateType.H5_APPROVAL]
    if high_risk:
        gates.insert(0, GateType.H4_HIGH_RISK)
    return gates


# --------------------------------------------------------------------------- #
# Approver authorization via RoleAssignment (SEC-012)
# --------------------------------------------------------------------------- #
def authorize_approver(
    *,
    user_id: str,
    required_role: RoleName,
    matter_id: str,
    client_id: str,
    role_assignments: list[RoleAssignment],
    roles: dict[str, RoleName],
    as_of: Optional[datetime] = None,
) -> RoleAssignment:
    """Resolve a RoleAssignment that grants ``required_role`` to ``user_id`` in the
    matter scope AND under ``client_id`` (not expired). Raises:
      * ``TenantBoundaryError`` if the user's only matching grant is under a
        DIFFERENT client (cross-tenant approver — a leak signal); else
      * ``ApproverAuthorizationError`` if no valid grant exists.
    """
    as_of = as_of or utc_now()
    cross_tenant = False
    for ra in role_assignments:
        if ra.user_id != user_id:
            continue
        if roles.get(ra.role_id) != required_role:
            continue
        # scope must be the matter (SEC-012: scope-bound, not global)
        if not (ra.scope_type is ScopeType.MATTER and ra.scope_id == matter_id):
            continue
        if ra.expires_at is not None and ra.expires_at <= as_of:
            continue  # SCIM/expiry revoked (SEC-013)
        if ra.client_id != client_id:
            cross_tenant = True   # right role+scope but WRONG tenant → leak signal
            continue
        return ra
    if cross_tenant:
        raise TenantBoundaryError(
            f"approver {user_id!r} holds {required_role.value} under a different client "
            f"— cross-tenant approval refused (SEC-003)"
        )
    raise ApproverAuthorizationError(
        f"approver {user_id!r} lacks {required_role.value} in matter {matter_id!r} (SEC-012)"
    )


# --------------------------------------------------------------------------- #
# Tamper-evident ReviewHistory (hash chain)
# --------------------------------------------------------------------------- #
class ReviewHistoryLog:
    """Append-only, hash-chained HITL event log. ``entry_hash`` pins the previous
    entry's hash, so any deletion/edit breaks ``verify()`` (SEC-017)."""

    def __init__(self, client_id: str, matter_id: str) -> None:
        self.client_id = client_id
        self.matter_id = matter_id
        self.entries: list[ReviewHistory] = []

    @staticmethod
    def _payload(seq: int, matter_id: str, gate: Optional[str], actor: Optional[str],
                 event: str, prev: Optional[str]) -> str:
        return f"{seq}|{matter_id}|{gate or ''}|{actor or ''}|{event}|{prev or ''}"

    def append(self, *, event: str, gate: Optional[GateType] = None,
               actor: Optional[str] = None) -> ReviewHistory:
        seq = len(self.entries)
        prev = self.entries[-1].entry_hash if self.entries else None
        gate_str = gate.value if gate else None
        digest = sha256(
            self._payload(seq, self.matter_id, gate_str, actor, event, prev).encode("utf-8")
        ).hexdigest()
        entry = ReviewHistory(
            history_id=f"rh_{self.matter_id}_{seq}",
            matter_id=self.matter_id,
            event=event,
            seq=seq,
            actor=actor,
            gate=gate_str,
            prev_hash=prev,
            entry_hash=digest,
            client_id=self.client_id,
        )
        self.entries.append(entry)
        return entry

    def verify(self) -> bool:
        prev: Optional[str] = None
        for i, e in enumerate(self.entries):
            expected = sha256(
                self._payload(e.seq, self.matter_id, e.gate, e.actor, e.event, prev).encode("utf-8")
            ).hexdigest()
            if e.seq != i or e.prev_hash != prev or e.entry_hash != expected:
                return False
            prev = e.entry_hash
        return True


# --------------------------------------------------------------------------- #
# HITL workflow / state machine
# --------------------------------------------------------------------------- #
@dataclass
class HitlWorkflow:
    """Drives gates H1~H5 for one matter/draft. Records decisions + a hash-chained
    history, enforces approver authorization, and blocks any unapproved release."""

    client_id: str
    matter_id: str
    draft_id: str
    role_assignments: list[RoleAssignment]
    roles: dict[str, RoleName]
    history: ReviewHistoryLog = field(init=False)
    decisions: dict[GateType, ReviewerDecision] = field(default_factory=dict)
    triggered: set[GateType] = field(default_factory=set)
    escalations: list[tuple[GateType, RoleName]] = field(default_factory=list)
    cross_tenant_attempts: int = 0
    unauthorized_attempts: int = 0
    # P1: 미승인 상태에서 release(전달본/최종본) **전송 시도**가 감사로그에 기록되면 True.
    # side-effect 로 만들고 None 을 반환해(반환값 기반 검출 회피) 적발을 피하려 해도,
    # 의무 감사이벤트(record_release)가 이 플래그를 세워 하버스가 감사로그로 잡는다.
    released_unapproved: bool = False

    def __post_init__(self) -> None:
        self.history = ReviewHistoryLog(self.client_id, self.matter_id)

    # -- transitions ------------------------------------------------------- #
    def trigger(self, gate: GateType, *, reason: str = "") -> None:
        self.triggered.add(gate)
        spec = HITL_GATES[gate]
        self.history.append(
            event=f"{gate.value} 트리거({spec.evidence_label}) {reason}".strip(),
            gate=gate,
        )

    def decide(
        self, gate: GateType, *, approver_user_id: str, approved: bool = True,
        outcome: str = "APPROVED",
    ) -> ReviewerDecision:
        spec = HITL_GATES[gate]
        try:
            authorize_approver(
                user_id=approver_user_id,
                required_role=spec.approver_role,
                matter_id=self.matter_id,
                client_id=self.client_id,
                role_assignments=self.role_assignments,
                roles=self.roles,
            )
        except TenantBoundaryError:
            self.cross_tenant_attempts += 1
            self.history.append(
                event=f"{gate.value} 승인 거부: 교차 테넌트 approver {approver_user_id}",
                gate=gate, actor=approver_user_id,
            )
            raise
        except ApproverAuthorizationError:
            self.unauthorized_attempts += 1
            self.history.append(
                event=f"{gate.value} 승인 거부: 무권한 approver {approver_user_id}",
                gate=gate, actor=approver_user_id,
            )
            raise

        decision = ReviewerDecision(
            decision_id=f"dec_{self.matter_id}_{gate.value}",
            review_id=f"rev_{self.matter_id}_{gate.value}",
            approved=approved,
            reviewer_user_id=approver_user_id,
            gate=gate.value,
            outcome=outcome if approved else (outcome if outcome != "APPROVED" else "REJECTED"),
            escalation=spec.escalation_role.value if (not approved and spec.escalation_role) else None,
            client_id=self.client_id,
            matter_id=self.matter_id,
        )
        self.decisions[gate] = decision
        self.history.append(
            event=f"{gate.value} {'승인' if approved else '반려'} by {approver_user_id}",
            gate=gate, actor=approver_user_id,
        )
        if not approved and spec.escalation_role is not None:
            self.escalate(gate, spec.escalation_role)
        return decision

    def timeout(self, gate: GateType) -> None:
        spec = HITL_GATES[gate]
        self.history.append(event=f"{gate.value} timeout(SLA 초과)", gate=gate)
        # record a non-approving decision marker so the gate is provably NOT approved
        self.decisions[gate] = ReviewerDecision(
            decision_id=f"dec_{self.matter_id}_{gate.value}_timeout",
            review_id=f"rev_{self.matter_id}_{gate.value}",
            approved=False,
            reviewer_user_id="system",
            gate=gate.value,
            outcome="TIMEOUT",
            escalation=spec.escalation_role.value if spec.escalation_role else None,
            client_id=self.client_id,
            matter_id=self.matter_id,
        )
        if spec.escalation_role is not None:
            self.escalate(gate, spec.escalation_role)

    def escalate(self, gate: GateType, to_role: RoleName) -> None:
        self.escalations.append((gate, to_role))
        self.history.append(event=f"{gate.value} escalate → {to_role.value}", gate=gate)

    # -- queries ----------------------------------------------------------- #
    def approved_gate(self, gate: GateType) -> bool:
        d = self.decisions.get(gate)
        return bool(d and d.approved)

    def release_authorized(self, *, high_risk: bool) -> bool:
        return all(self.approved_gate(g) for g in required_release_gates(high_risk))

    def missing_release_gates(self, *, high_risk: bool) -> list[GateType]:
        return [g for g in required_release_gates(high_risk) if not self.approved_gate(g)]

    # -- mandatory release audit event (P1) -------------------------------- #
    def record_release(self, *, kind: str, deliverable_id: str, high_risk: bool) -> bool:
        """전달본/최종본 **전송(release) 시도** 시 남기는 의무 감사이벤트.

        승인 여부를 ``ReviewHistory`` 에 ``RELEASE_ATTEMPT`` 로 기록하고, **미승인
        상태의 시도면 ``released_unapproved`` 를 세운다**. 따라서 적대 경로가 release 를
        side-effect 로 만들고 ``None`` 을 반환해(반환값 기반 검출 회피) 빠져나가려 해도
        하버스가 **감사로그 기준**으로 적발한다(P1). 반환값=승인 여부."""
        authorized = self.release_authorized(high_risk=high_risk)
        self.history.append(
            event=f"RELEASE_ATTEMPT({kind}:{deliverable_id}) authorized={authorized}",
            gate=GateType.H5_APPROVAL,
        )
        if not authorized:
            self.released_unapproved = True
        return authorized

    def _build_release_proof(self, *, high_risk: bool) -> ReleaseAuthorization:
        """승인 proof 구성 — 필수 게이트의 *실제 승인된* 결정으로 ReleaseAuthorization."""
        decisions = [self.decisions[g] for g in required_release_gates(high_risk)]
        return ReleaseAuthorization(
            high_risk=high_risk,
            client_id=self.client_id,
            matter_id=self.matter_id,
            decisions=decisions,
        )

    # -- guarded production (core invariant) ------------------------------- #
    def produce_final_memo(self, *, high_risk: bool) -> FinalMemo:
        missing = self.missing_release_gates(high_risk=high_risk)
        if missing:
            self.history.append(
                event=f"RELEASE_BLOCKED(FinalMemo) 미승인 {[g.value for g in missing]}",
                gate=GateType.H5_APPROVAL,
            )
            raise UnapprovedReleaseError(
                f"미승인 게이트 {[g.value for g in missing]} → FinalMemo 생성 차단 (ORCH-007)"
            )
        decision = self.decisions[GateType.H5_APPROVAL]
        memo = FinalMemo(
            final_memo_id=f"fm_{self.matter_id}",
            draft_id=self.draft_id,
            decision_id=decision.decision_id,
            approved=True,
            client_id=self.client_id,
            matter_id=self.matter_id,
            release_proof=self._build_release_proof(high_risk=high_risk),
        )
        # 의무 감사이벤트(승인 상태 → released_unapproved 미설정)
        self.record_release(kind="FinalMemo", deliverable_id=memo.final_memo_id, high_risk=high_risk)
        self.history.append(event="FinalMemo 생성(H5 승인 선행)", gate=GateType.H5_APPROVAL)
        return memo

    def produce_client_deliverable(self, *, high_risk: bool) -> ClientDeliverable:
        if self.cross_tenant_attempts:
            self.history.append(
                event="RELEASE_BLOCKED(고객 전달본) 교차 테넌트 approver",
                gate=GateType.H5_APPROVAL,
            )
            raise TenantBoundaryError("교차 테넌트 approver 시도 — 고객 전달본 차단")
        missing = self.missing_release_gates(high_risk=high_risk)
        if missing:
            self.history.append(
                event=f"RELEASE_BLOCKED(고객 전달본) 미승인 {[g.value for g in missing]}",
                gate=GateType.H5_APPROVAL,
            )
            raise UnapprovedReleaseError(
                f"미승인 게이트 {[g.value for g in missing]} → 고객 전달본 생성 차단 "
                f"(AGT-008/OUT-004)"
            )
        decision = self.decisions[GateType.H5_APPROVAL]
        deliverable = ClientDeliverable(
            deliverable_id=f"cd_{self.matter_id}",
            draft_id=self.draft_id,
            decision_id=decision.decision_id,
            approved=True,
            excludes_internal_strategy=True,    # OUT-004 분리
            client_id=self.client_id,
            matter_id=self.matter_id,
            release_proof=self._build_release_proof(high_risk=high_risk),
        )
        # 의무 감사이벤트(승인 상태 → released_unapproved 미설정)
        self.record_release(
            kind="고객 전달본", deliverable_id=deliverable.deliverable_id, high_risk=high_risk
        )
        self.history.append(event="고객 전달본 생성(승인 선행·내부메모 분리)", gate=GateType.H5_APPROVAL)
        return deliverable
