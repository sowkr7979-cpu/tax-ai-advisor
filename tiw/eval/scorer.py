"""tiw/eval/scorer.py — honest rubric scorer (docs/09 §2-§3).

Centralizes ALL scoring math so it cannot be quietly gamed by a slice:
  - dimension fractions (0..1) are snapped to the frozen buckets 0/25/50/75/100;
  - the slice's total is the WEIGHTED mean over its APPLICABLE dimensions,
    renormalized to 0..100 (an infra slice like ⑥ is judged only on the
    deterministic dimensions it actually exercises — requirement/search/
    security/ops — never credited for legal-reasoning it doesn't perform);
  - hard-gate codes impose the frozen caps (docs/09 §2); the tightest wins.

The scorer NEVER invents credit. If a dimension is not exercised it is N/A
(score=None), excluded from the denominator, and reported as such.
"""

from __future__ import annotations

from contract.cluster_i_eval import FailureMode, RubricResult, Score, TargetKind, Visibility
from rules.hard_gates import (
    DIMENSION_WEIGHTS,
    HARD_GATES,
    SCORE_BUCKETS,
    tightest_cap,
)


def snap_to_bucket(fraction: float) -> int:
    """Snap a 0..1 fraction to the nearest frozen rubric bucket (docs/09 §3)."""
    pct = max(0.0, min(1.0, fraction)) * 100.0
    return min(SCORE_BUCKETS, key=lambda b: (abs(b - pct), b))


def build_rubric_result(
    *,
    case_id: str,
    slice_no: int,
    target_id: str,
    visibility: Visibility,
    dim_fractions: dict[str, float],
    dim_details: dict[str, str] | None = None,
    hard_gate_codes: list[str],
    metrics: dict | None = None,
    target_kind: TargetKind = TargetKind.SLICE,
) -> RubricResult:
    dim_details = dim_details or {}
    scores: list[Score] = []
    applicable_weight = 0
    weighted_sum = 0.0

    for dim, weight in DIMENSION_WEIGHTS.items():
        if dim in dim_fractions:
            bucket = snap_to_bucket(dim_fractions[dim])
            scores.append(
                Score(
                    dimension=dim,
                    weight=weight,
                    score=float(bucket),
                    applicable=True,
                    detail=dim_details.get(dim),
                )
            )
            applicable_weight += weight
            weighted_sum += bucket * weight
        else:
            scores.append(
                Score(
                    dimension=dim,
                    weight=weight,
                    score=None,
                    applicable=False,
                    detail="N/A — not exercised by this slice",
                )
            )

    raw_total = (weighted_sum / applicable_weight) if applicable_weight else 0.0

    # tightest_cap is fail-closed: it RAISES on any unregistered code, so an
    # unknown/typo'd gate can never be silently dropped to dodge its cap.
    cap = tightest_cap(hard_gate_codes)
    total = min(raw_total, float(cap)) if cap is not None else raw_total

    failure_modes = [
        FailureMode(
            code=HARD_GATES[c].code,
            description=HARD_GATES[c].description,
            hard_gate=True,
            cap=HARD_GATES[c].cap,
        )
        for c in hard_gate_codes
    ]

    return RubricResult(
        case_id=case_id,
        slice=slice_no,
        target_kind=target_kind,
        target_id=target_id,
        visibility=visibility,
        dimension_scores=scores,
        failure_modes=failure_modes,
        cap=cap,
        raw_total=round(raw_total, 2),
        total=round(total, 2),
        metrics=metrics or {},
    )
