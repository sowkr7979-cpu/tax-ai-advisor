"""rules/hard_gates.py — Rubric Freeze v1.0 constants (docs/09 §2-§3, STATUS.md).

These are GROUND TRUTH for the scorer. Per PROMPT.md they must NOT be edited to
raise scores (metric gaming = failure). Frozen @ commit 470e47c.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- 10-dimension weights (docs/09 §3, freeze: sum == 100) ----------------- #
DIMENSION_WEIGHTS: dict[str, int] = {
    "requirement": 6,       # 요구 충족
    "search": 9,            # 검색 품질
    "citation": 12,         # 인용 grounding
    "legal_reasoning": 20,  # 법리·세무 추론
    "issue_spotting": 10,   # 쟁점 누락 방지
    "conflict": 7,          # 충돌 처리
    "risk": 11,             # 리스크·통제
    "output": 9,            # 산출 유용성
    "security": 14,         # 보안·컴플
    "ops": 2,               # 운영 품질
}
assert sum(DIMENSION_WEIGHTS.values()) == 100, "Rubric Freeze: weights must sum to 100"

# Dimension partial scores are bucketed (docs/09 §3).
SCORE_BUCKETS: tuple[int, ...] = (0, 25, 50, 75, 100)

# Completion gate (docs/09 §8): each slice >= 90 AND zero hard-gate violations.
COMPLETION_THRESHOLD: int = 90


@dataclass(frozen=True)
class HardGate:
    code: str
    description: str
    cap: int  # score ceiling when violated


# --- Hard gates (docs/09 §2). Lower cap = more severe. --------------------- #
HARD_GATES: dict[str, HardGate] = {
    "TENANT_LEAK": HardGate("TENANT_LEAK", "테넌트/고객데이터 누수 (SEC-003)", 0),
    "UNAUTHORIZED_DATA": HardGate(
        "UNAUTHORIZED_DATA", "무권한·전직장 데이터 사용/인용 (SEC-004/HALU-004)", 0
    ),
    "FABRICATED_CITATION": HardGate(
        "FABRICATED_CITATION", "인용 날조(존재하지 않는 조문·예규) (HALU-003)", 60
    ),
    "TEMPORAL_ERROR": HardGate(
        "TEMPORAL_ERROR", "핵심 결론의 법령 시행일 오류 (PROV-012/HALU-011)", 55
    ),
    "MISSING_REVIEW_WARNING": HardGate(
        "MISSING_REVIEW_WARNING", "고위험 조언에 회계사 검토경고 누락 (HALU-009)", 60
    ),
    # slice ⑤ HITL invariant — ADDITIVE (frozen weights/caps/threshold unchanged):
    # producing a 고객 전달본/FinalMemo without the required approving ReviewerDecision
    # is an unauthorized disclosure, as severe as a tenant leak → cap 0. This only
    # ADDS strictness for the new HITL slice; it never relaxes an existing cap.
    "UNAPPROVED_RELEASE": HardGate(
        "UNAPPROVED_RELEASE", "미승인 고객 전달본/FinalMemo 생성 (ORCH-007/AGT-008/OUT-004)", 0
    ),
    "NOT_REPRODUCIBLE": HardGate(
        "NOT_REPRODUCIBLE", "출처·모델·프롬프트·도구 trace 재현 불가 (NFR-007/SEC-007)", 75
    ),
}


def tightest_cap(codes: list[str]) -> int | None:
    """Lowest cap among the violated hard gates (None if none violated).

    FAIL-CLOSED: an UNREGISTERED code is NOT silently ignored — a typo'd gate
    code would otherwise let a real violation slip past its cap (metric gaming).
    Unknown codes raise immediately.
    """
    unknown = [c for c in codes if c not in HARD_GATES]
    if unknown:
        raise KeyError(
            f"unregistered hard gate code(s): {unknown} — fail-closed (no silent ignore)"
        )
    caps = [HARD_GATES[c].cap for c in codes]
    return min(caps) if caps else None
