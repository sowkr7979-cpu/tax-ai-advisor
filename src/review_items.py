"""src/review_items.py — HALU-008 회계사 검토항목 자동생성 (deterministic).

# HALU-008 답변마다 회계사 검토 필요사항 자동 도출 (docs/08 §7)
# HALU-009 고위험·적극 절세·불확실 결론에 회계사 검토경고 누락 차단 (cap 60)

Given a generated ``ResearchLiteAnswer`` (channel ①/②/④ output) and the run's
scenario flags, this derives the list of ``ReviewItem`` a CPA reviewer must clear
BEFORE the answer can be approved (H1~H5). It is fully DETERMINISTIC (no LLM): the
items are read off the answer's own structure (certainty / abstention / risks /
spotted issues / applicable basis) plus the orchestration signals (unresolved
conflicts, failed agents, data limits).

Categories (docs/08 §7):
  * INTERPRETATION      — 사실인정·법적평가 필요(GT 불가) 결론
  * UNCERTAIN           — 보류/되물음(시점·근거 부족)
  * UNRESOLVED_CONFLICT — 미해소 소스 충돌 → 검토항목 승격(ORCH-004/HALU-005)
  * HIGH_RISK_AGGRESSIVE— 고위험/적극 절세 → 과세·방어논리 + 검토경고(필수, HALU-009)
  * DATA_LIMIT          — 자료 한계 / 에이전트 장애 누락(ORCH-006)
  * WEAK_BASIS          — 근거 약한 주장
  * TEMPORAL_ASSUMPTION — 시점 가정(applicable basis)

The high-risk/aggressive item carries the standard review WARNING; its absence on
a high-risk answer is what the harness checks for the MISSING_REVIEW_WARNING gate.
"""

from __future__ import annotations

from typing import Optional, Sequence

from contract.cluster_h_review import ReviewItem, ReviewItemCategory
from src.law_anchor import REVIEW_WARNING
from src.legal_research import ResearchLiteAnswer

# 적극 절세 가드레일(AGT-008): 고위험 검토항목은 과세논리·방어논리 양면을 모두 적시한다.
_AGGRESSIVE_GUARDRAIL = (
    "[적극 절세 가드레일] 과세논리(과세관청 입장·부인 가능성)와 방어논리(소명·증빙) "
    "양면을 함께 적시하고, Reviewer 승인 전에는 고객 전달본에 포함 금지(AGT-008/OUT-004)."
)


def _uncertain(answer: ResearchLiteAnswer) -> bool:
    return answer.abstained or answer.certainty.strip() in ("불확실", "보류", "추정")


def generate_review_items(
    *,
    answer: ResearchLiteAnswer,
    client_id: str,
    matter_id: Optional[str] = None,
    high_risk: bool = False,
    aggressive: bool = False,
    unresolved_conflicts: Sequence[str] = (),
    agent_gaps: Sequence[str] = (),
    data_limits: Sequence[str] = (),
    prefix: str = "ri",
) -> list[ReviewItem]:
    """Derive the reviewer check-list for one answer (HALU-008). Deterministic."""
    items: list[ReviewItem] = []
    n = 0

    def add(category: ReviewItemCategory, description: str, *, gate: str,
            severity: str = "MEDIUM", requires_warning: bool = False,
            source_ref: Optional[str] = None) -> None:
        nonlocal n
        items.append(
            ReviewItem(
                item_id=f"{prefix}_{n}",
                category=category,
                description=description,
                gate=gate,
                severity=severity,
                requires_warning=requires_warning,
                source_ref=source_ref,
                client_id=client_id,
                matter_id=matter_id,
            )
        )
        n += 1

    # 1) 해석(사실인정·법적평가) 결론 — GT 불가 영역은 회계사 판단(HALU-011)
    if answer.certainty.strip() in ("해석", "interpretation") or _uncertain(answer):
        add(
            ReviewItemCategory.INTERPRETATION,
            f"해석·사실판단 필요 결론({answer.certainty}): 사실인정·법적평가는 회계사 판단(HITL) — "
            f"계산엔진/생성기 단정 금지.",
            gate="H1",
            source_ref="legal-conclusion",
        )

    # 2) 시점 가정 — applicable basis(거래일/귀속/사업연도) 가정 명시(PROV-013)
    basis = answer.bundle.applicable_basis
    add(
        ReviewItemCategory.TEMPORAL_ASSUMPTION,
        f"적용시점 가정: {basis.as_of_date:%Y-%m-%d} ({basis.basis_kind.value}) 기준 시행일 버전 — "
        f"실제 거래일/귀속연도 확정 필요.",
        gate="H3",
        source_ref="applicable-basis",
    )

    # 3) 불확실/보류 결론 → 되물음(HALU-007)
    if _uncertain(answer):
        add(
            ReviewItemCategory.UNCERTAIN,
            "근거·시점 한계로 결론 보류(abstain) — 단정 대신 되물음/추가 확인 필요.",
            gate="H3",
            severity="HIGH",
            source_ref="abstention",
        )

    # 4) 근거 약한 주장 — 생성기가 flag 한 리스크 항목(HALU-006)
    for r in answer.risks:
        add(
            ReviewItemCategory.WEAK_BASIS,
            f"근거 확인 필요: {r}",
            gate="H2",
            source_ref="risk",
        )

    # 5) 고위험/적극 절세 → 과세·방어논리 + 검토경고(필수, HALU-009)
    if high_risk or aggressive:
        desc = REVIEW_WARNING
        if aggressive:
            desc = f"{REVIEW_WARNING}\n{_AGGRESSIVE_GUARDRAIL}"
        add(
            ReviewItemCategory.HIGH_RISK_AGGRESSIVE,
            desc,
            gate="H4",
            severity="HIGH",
            requires_warning=True,             # HALU-009 carrier
            source_ref="high-risk",
        )

    # 6) 미해소 소스 충돌 → 검토항목 승격(ORCH-004/HALU-005), 단정 금지
    for c in unresolved_conflicts:
        add(
            ReviewItemCategory.UNRESOLVED_CONFLICT,
            f"미해소 충돌(단정 금지·그대로 노출): {c}",
            gate="H3",
            severity="HIGH",
            source_ref="conflict",
        )

    # 7) 에이전트 장애 누락(graceful degrade, ORCH-006) + 자료 한계
    for g in agent_gaps:
        add(
            ReviewItemCategory.DATA_LIMIT,
            f"{g} 에이전트 장애로 해당 분석 누락 — 결론은 부분 결과이며 재시도/수동 보완 필요.",
            gate="H1",
            severity="HIGH",
            source_ref="agent-failure",
        )
    for d in data_limits:
        add(
            ReviewItemCategory.DATA_LIMIT,
            f"자료 한계: {d}",
            gate="H1",
            source_ref="data-limit",
        )

    return items


def has_high_risk_warning(items: Sequence[ReviewItem]) -> bool:
    """True iff a high-risk/aggressive review item carries the review WARNING
    (HALU-009). Used to trip MISSING_REVIEW_WARNING when it is absent."""
    return any(
        i.category is ReviewItemCategory.HIGH_RISK_AGGRESSIVE
        and i.requires_warning
        and REVIEW_WARNING in i.description
        for i in items
    )


def covered_categories(items: Sequence[ReviewItem]) -> set[str]:
    return {i.category.value for i in items}
