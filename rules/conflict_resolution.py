"""rules/conflict_resolution.py — deterministic conflict-resolution decision table.

# HALU-012 충돌 해소는 LLM 재량이 아니라 rules/ 의 결정 규칙 + 결과 로그 (docs/08 §5-1)
# docs/04 §4 모델 변경: 50/30/20 가중 폐기 — 평균/다수결 금지, 충돌은 표면화
# docs/02 §5 권위 위계: 법률 > 시행령 > 시행규칙 > 예규·판례·심판례 > 실무서 > 웹

The synthesis NEVER averages or majority-votes conflicting source positions. For
each aligned topic it applies THIS table (inputs: ``authority_rank · 시점 유효성 ·
사실관계 동일성 · source_type``) and logs the outcome (reproducible/auditable):

  | 상황                          | 결정                                            |
  |-------------------------------|-------------------------------------------------|
  | 같은 조문 다른 시행일 버전    | 적용시점 유효 버전 채택, 타 버전 배제 (TEMPORAL) |
  | 법률 vs 웹/실무서 불일치      | 법률 채택, 웹/실무서 강등 (AUTHORITY)            |
  | 사실관계 불일치 예규 원용     | 원용 불가 → 배제 → 검토항목 (FACT_MISMATCH)      |
  | 해소 불가(권위·시점 동급)     | 단정 금지 → 보류 (UNRESOLVED_ABSTAIN)            |
  | ①법령 부재, ②③ 합의          | 비권위적 합의 → 가이드·캡·HITL (NON_AUTH_CONS.)  |

Channel order ①>②>③ is a TIE-BREAK ONLY (pick which AGREEING source's citation to
inherit) — never a substantive ground to resolve a contradiction (docs/04 §4-2-1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from contract.base import ConflictOutcome, SourceAnswerStatus, SourceType

# 권위 위계 (docs/02 §5) — lower rank = higher authority.
AUTHORITY_RANK: dict[str, int] = {
    "법률": 1,
    "시행령": 2,
    "시행규칙": 3,
    "고시": 4,
    "예규": 5,
    "판례": 5,
    "심판례": 5,
    "실무서": 6,
    "웹": 7,
}
_INTERPRETIVE = {"예규", "판례", "심판례"}

# Channel tie-break order ①>②>③ (docs/04 §4-2-1) — ONLY to pick a representative
# among AGREEING sources, never to decide a contradiction.
CHANNEL_ORDER: dict[str, int] = {"①": 1, "②": 2, "③": 3}


def authority_rank_of(label: str) -> int:
    return AUTHORITY_RANK.get(label, 9)


@dataclass
class SourcePosition:
    """One source's position on an aligned topic (the decision-table input row)."""

    source_type: SourceType
    channel_label: str                  # ①|②|③
    authority_label: str
    status: SourceAnswerStatus
    stance: str                         # normalized position; "" when SILENT
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None  # exclusive; None = open window
    dispositive: bool = True            # 조문 문언이 그 쟁점을 직접 규율하는가
    fact_match: bool = True             # 예규 사실관계 동일성
    version_based: bool = False         # 충돌이 동일조문·다른시행일 버전에서 옴
    source_answer_id: str = ""
    citation_id: Optional[str] = None
    claim_id: Optional[str] = None
    temporally_valid_cache: bool = True   # filled by resolve_topic (for inputs log)

    @property
    def authority_rank(self) -> int:
        return authority_rank_of(self.authority_label)

    @property
    def is_interpretive(self) -> bool:
        return self.authority_label in _INTERPRETIVE

    @property
    def answered(self) -> bool:
        return self.status is SourceAnswerStatus.ANSWERED

    def temporally_valid(self, as_of: date) -> bool:
        """적용시점 유효성 (PROV-012): the grounding version's window covers as_of."""
        if self.effective_from is None:
            return True
        return self.effective_from <= as_of and (
            self.effective_to is None or as_of < self.effective_to
        )


@dataclass
class ResolutionResult:
    outcome: ConflictOutcome
    adopted: list[SourcePosition] = field(default_factory=list)
    excluded: list[SourcePosition] = field(default_factory=list)   # 시점/사실 배제
    demoted: list[SourcePosition] = field(default_factory=list)    # 참고로 강등
    silent: list[SourcePosition] = field(default_factory=list)
    rule_applied: str = ""
    authority_deficit: bool = False     # ① 법률 권위 소스 부재
    rationale: str = ""

    @property
    def abstained(self) -> bool:
        return self.outcome in (
            ConflictOutcome.UNRESOLVED_ABSTAIN,
            ConflictOutcome.NON_AUTHORITATIVE_CONSENSUS,
        )

    @property
    def inputs(self) -> dict:
        """ConflictResolution.inputs payload (HALU-012 — 재현·감사)."""
        return {
            "authority_ranks": {p.channel_label: p.authority_rank for p in self._all},
            "temporal_validity": {p.channel_label: p.temporally_valid_cache for p in self._all},
            "fact_match": {p.channel_label: p.fact_match for p in self._all},
            "source_types": {p.channel_label: p.source_type.value for p in self._all},
            "stances": {p.channel_label: (p.stance or "SILENT") for p in self._all},
        }

    @property
    def _all(self) -> list[SourcePosition]:
        return [*self.adopted, *self.demoted, *self.excluded, *self.silent]


def _pick_by_channel(positions: list[SourcePosition]) -> SourcePosition:
    """Tie-break among EQUIVALENT (agreeing) positions: highest channel ①>②>③."""
    return min(positions, key=lambda p: (CHANNEL_ORDER.get(p.channel_label, 9), p.source_answer_id))


def resolve_topic(positions: list[SourcePosition], as_of: date) -> ResolutionResult:
    """Apply the deterministic decision table to one topic's source positions.

    Pure + reproducible (no LLM, no randomness). The caller logs the
    ``ResolutionResult`` as a ``ConflictResolution`` (HALU-012)."""
    # cache temporal validity onto each position for the inputs log
    for p in positions:
        p.temporally_valid_cache = p.temporally_valid(as_of)

    answered = [p for p in positions if p.answered]
    silent = [p for p in positions if not p.answered]

    if not answered:
        return ResolutionResult(
            outcome=ConflictOutcome.UNRESOLVED_ABSTAIN, silent=silent,
            rule_applied="모든 소스 침묵/오류 — 근거 없음", authority_deficit=True,
            rationale="응답 소스 0 — 종합 보류",
        )

    law_present = any(p.authority_label == "법률" for p in answered)
    stances = {p.stance for p in answered}

    # ---- AGREE (or 비권위적 합의) ------------------------------------------ #
    if len(stances) == 1:
        adopt = _pick_by_channel(answered)
        deficit = not law_present
        others = [p for p in answered if p is not adopt]
        if deficit:
            # ①법령 부재, ②③ 합의 → 비권위적 합의(실무 가이드·confidence 캡·HITL)
            return ResolutionResult(
                outcome=ConflictOutcome.NON_AUTHORITATIVE_CONSENSUS,
                adopted=[adopt], demoted=others, silent=silent,
                rule_applied="①법령 부재 + ②③ 합의 → 비권위적 합의(가이드 한정)",
                authority_deficit=True,
                rationale="법령 원문 근거 미확보 — 실무/웹 합의는 법령을 대체하지 못함",
            )
        return ResolutionResult(
            outcome=ConflictOutcome.AGREE, adopted=[adopt], demoted=others, silent=silent,
            rule_applied="전 응답 소스 합치 → 합의(권위 채널 인용 상속, 채널 tie-break)",
            authority_deficit=False, rationale="응답 소스 입장 일치",
        )

    # ---- CONFLICT (stances differ) ---------------------------------------- #
    # 1) 같은 조문 다른 시행일 버전 → 적용시점 유효 버전 채택 (TEMPORAL)
    if answered and all(getattr(p, "version_based", False) for p in answered):
        valid = [p for p in answered if p.temporally_valid(as_of)]
        invalid = [p for p in answered if not p.temporally_valid(as_of)]
        if valid and len({p.stance for p in valid}) == 1:
            adopt = _pick_by_channel(valid)
            demoted = [p for p in valid if p is not adopt]
            return ResolutionResult(
                outcome=ConflictOutcome.TEMPORAL, adopted=[adopt],
                excluded=invalid, demoted=demoted, silent=silent,
                rule_applied="같은 조문 다른 시행일 버전 → 적용시점 유효 버전 채택, 구버전 배제",
                authority_deficit=not law_present,
                rationale=f"as_of={as_of} 유효 버전 채택, {len(invalid)}건 구버전 배제",
            )

    # 2) 사실관계 불일치 예규 원용 불가 → 배제 (FACT_MISMATCH)
    fact_excluded = [p for p in answered if p.is_interpretive and not p.fact_match]
    usable = [p for p in answered if p not in fact_excluded]

    # 3) 권위 위계: 시점 유효 + dispositive 한 것 중 최상위 권위 단일 → 채택 (AUTHORITY)
    candidates = [p for p in usable if p.temporally_valid(as_of) and p.dispositive]
    if candidates:
        top_rank = min(p.authority_rank for p in candidates)
        top = [p for p in candidates if p.authority_rank == top_rank]
        if len({p.stance for p in top}) == 1:
            adopt = _pick_by_channel(top)
            others = [p for p in answered if p is not adopt and p not in fact_excluded]
            outcome = ConflictOutcome.FACT_MISMATCH if fact_excluded else ConflictOutcome.AUTHORITY
            rule = (
                "사실관계 불일치 예규 배제 + 권위 위계 채택"
                if fact_excluded else
                "권위 위계(법률>…>웹)로 최상위 권위 채택, 하위 강등(평균 금지)"
            )
            return ResolutionResult(
                outcome=outcome, adopted=[adopt], excluded=fact_excluded,
                demoted=others, silent=silent, rule_applied=rule,
                authority_deficit=not law_present,
                rationale=f"최상위 권위 '{adopt.authority_label}' 단일 입장 채택",
            )

    # 4) 해소 불가(권위·시점 동급 또는 최상위 비-dispositive) → 단정 금지 → 보류
    return ResolutionResult(
        outcome=ConflictOutcome.UNRESOLVED_ABSTAIN, silent=silent,
        demoted=answered, rule_applied="권위·시점 동급 충돌(또는 최상위 비규정) → 단정 금지",
        authority_deficit=not law_present,
        rationale="결정테이블로 우열 판정 불가 — 소스별 입장 표시 + 회계사 검토 보류",
    )
