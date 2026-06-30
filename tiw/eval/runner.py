"""tiw/eval/runner.py — slice aggregation + registry (docs/09 §8 completion gate).

Headline slice score = MIN over case totals (conservative: one leaking case fails
the slice — averaging a failure away would be gaming). Mean is reported too for
transparency. A slice PASSES iff score >= 90 AND no hard-gate hit (PROMPT.md §5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from contract.cluster_i_eval import RubricResult, Visibility
from rules.hard_gates import COMPLETION_THRESHOLD
from tiw.eval.loader import load_hidden_cases, load_public_cases
from tiw.eval.slices import (
    slice1_law_anchor,
    slice2_rag,
    slice3_web,
    slice4_synthesis,
    slice5_hitl,
    slice6_isolation,
    slice7_multitax_transparency,
)


@dataclass
class SliceReport:
    slice_no: int
    name: str
    case_results: list[RubricResult] = field(default_factory=list)
    score: float = 0.0          # headline = min(case totals)
    mean_total: float = 0.0
    hard_gate_hit: bool = False
    pending: bool = False        # any dimension awaiting judge/CPA (PROMPT.md §0)
    threshold: int = COMPLETION_THRESHOLD

    @property
    def passed(self) -> bool:
        # A slice with PENDING_JUDGE dimensions can NEVER be a ≥90 completion:
        # the judge-scored dimensions (법리 등) are explicitly withheld, so the
        # slice is INCOMPLETE — not a pass. This is fail-closed for completion
        # and strictly to the implementer's DISadvantage (anti-gaming safe).
        return (not self.hard_gate_hit) and self.score >= self.threshold and not self.pending

    # Headline separation (codex P2-B): `score` is the judge-free min over case
    # deterministic subtotals. While `pending` it is NOT a completion score.
    @property
    def deterministic_subtotal(self) -> float:
        """Judge-free headline = min over case deterministic subtotals (== score)."""
        return self.score

    @property
    def completion_score(self) -> Optional[float]:
        """Completion headline — ``None`` while any dimension is PENDING_JUDGE
        (the slice is INCOMPLETE, so there is no completion score to report)."""
        return None if self.pending else self.score

    @property
    def pending_dimensions(self) -> list[str]:
        seen: list[str] = []
        for r in self.case_results:
            for d in r.pending_dimensions:
                if d not in seen:
                    seen.append(d)
        return seen

    @property
    def public_count(self) -> int:
        return sum(1 for r in self.case_results if r.visibility == Visibility.PUBLIC)

    @property
    def hidden_count(self) -> int:
        return sum(1 for r in self.case_results if r.visibility == Visibility.HIDDEN)


# slice_no -> (display name, callable(cases) -> list[RubricResult])
_REGISTRY = {
    1: ("법령MCP 앵커 답변", slice1_law_anchor.run_cases),
    2: ("citation 검증 RAG", slice2_rag.run_cases),
    3: ("공식소스 Web run", slice3_web.run_cases),
    4: ("충돌 케이스(3소스 종합)", slice4_synthesis.run_cases),
    5: ("CPA HITL 워크플로", slice5_hitl.run_cases),
    6: ("테넌트 격리", slice6_isolation.run_cases),
    7: ("다세목·투명성", slice7_multitax_transparency.run_cases),
}


def implemented_slices() -> list[int]:
    return sorted(_REGISTRY)


def run_slice(slice_no: int) -> SliceReport:
    if slice_no not in _REGISTRY:
        raise ValueError(
            f"slice {slice_no} not implemented yet. Implemented: {implemented_slices()}"
        )
    name, runner = _REGISTRY[slice_no]
    # hidden + public loaded via SEPARATE loaders (anti-gaming, docs/09 §6)
    cases = load_public_cases(slice_no) + load_hidden_cases(slice_no)
    results = runner(cases)

    if not results:
        return SliceReport(slice_no=slice_no, name=name, case_results=[], score=0.0)

    totals = [r.total for r in results]
    return SliceReport(
        slice_no=slice_no,
        name=name,
        case_results=results,
        score=round(min(totals), 2),
        mean_total=round(sum(totals) / len(totals), 2),
        hard_gate_hit=any(r.hard_gate_hit for r in results),
        pending=any(r.has_pending for r in results),
    )


def run_all() -> list[SliceReport]:
    return [run_slice(n) for n in implemented_slices()]
