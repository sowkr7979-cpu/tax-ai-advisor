"""src/synthesis.py — channel-④ Synthesis engine (3소스 종합, docs/04 §4 · docs/08 §5).

Takes up to 3 INDEPENDENT, complete ``SourceAnswer`` contributions (① LAW_MCP /
② INTERNAL_RAG / ③ WEB — each from the shared SourceAnswer generators
``src.law_anchor`` / ``src.legal_research``) and produces, at CLAIM level:

  * ``ClaimAlignment``      — AGREE / CONFLICT / SILENT per atomic topic (ORCH-011)
  * ``ConflictResolution``  — the deterministic decision-table outcome + inputs log
                              (HALU-012, ``rules.conflict_resolution`` — NOT prompt)
  * ``SynthesisOpinion``    — INHERITS source citations (creates NONE — ORCH-012);
                              unresolved conflict / 법령부재 → abstain + 검토항목

CORE RULES (절대):
  * NO weighted average / majority vote — a real conflict is SURFACED, never merged
    (docs/04 §4 모델 변경; HALU-005).
  * Authority hierarchy 법률>시행령>…>실무서>웹 + 시점 유효성 + 사실관계 동일성 decide;
    channel ①>②>③ is a TIE-BREAK only (docs/04 §4-2-1).
  * lineage 무결성 (HALU-014): every DISPLAYED synthesis claim is traceable to a
    source ``Citation`` (inherited) — an untraceable claim is a violation.
  * 인용 날조가 한 소스에 있으면 그 소스 60캡 + 종합에 경고 전파 (HALU-013).

This engine is PURE/deterministic (no LLM, no randomness). The primary source's
LLM legal reasoning is generated UPSTREAM (``src.legal_research``) and passed in;
the engine only RECONCILES — so the conflict logic replays identically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from contract.base import (
    AlignmentStatus,
    ConflictOutcome,
    SourceAnswerStatus,
    SourceType,
)
from contract.cluster_d_provenance import ProvisionVersion
from contract.cluster_f_qa import (
    Citation,
    Claim,
    ClaimAlignment,
    ConfidenceScore,
    ConflictFlag,
    ConflictResolution,
    SourceAnswer,
    SynthesisOpinion,
)
from rules.conflict_resolution import ResolutionResult, SourcePosition, resolve_topic
from src.legal_research import ResearchLiteAnswer

# Confidence cap when ① 법령 권위 소스가 부재(비권위적 합의) — 실무 가이드 한정.
_AUTHORITY_DEFICIT_CAP = 0.6
# Confidence cap when a conflict is left unresolved (abstain).
_UNRESOLVED_CAP = 0.4

SYNTHESIS_REVIEW_WARNING = (
    "[회계사 검토 필요] 본 종합의견은 3소스(①법령·②내부·③웹) 독립답변을 권위 위계·"
    "시점 유효성 기준으로 정합한 결과입니다. 미해소 충돌·시점 가정·법령부재 항목은 "
    "단정하지 않으며 회계사(CPA) 검토·서명이 필요합니다."
)


# --------------------------------------------------------------------------- #
# Inputs: one channel's independent contribution
# --------------------------------------------------------------------------- #
@dataclass
class SourceContribution:
    """One channel's INDEPENDENT complete answer fed to the synthesis."""

    source_type: SourceType
    channel_label: str                          # ①|②|③
    authority_label: str
    status: SourceAnswerStatus
    source_answer: SourceAnswer
    topic_key: str
    stance: str
    dispositive: bool = True
    fact_match: bool = True
    version_based: bool = False
    provision_version: Optional[ProvisionVersion] = None
    claims: list[Claim] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    research: Optional[ResearchLiteAnswer] = None   # primary source's LLM 법리
    is_primary: bool = False
    fabricated: bool = False                        # HALU-013: 인용 검증 실패(레지스트리/entailment)

    @property
    def answered(self) -> bool:
        return self.status is SourceAnswerStatus.ANSWERED

    @property
    def primary_citation(self) -> Optional[Citation]:
        # the legal-conclusion citation if present (primary), else the anchor citation
        return self.citations[-1] if self.citations else None

    @property
    def primary_claim(self) -> Optional[Claim]:
        return self.claims[-1] if self.claims else None


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
@dataclass
class TopicReconciliation:
    topic_key: str
    alignment: ClaimAlignment
    resolution: Optional[ConflictResolution]
    result: ResolutionResult
    conflict_flag: Optional[ConflictFlag]
    synthesis_claim: Optional[Claim]            # displayed synthesis conclusion (None=abstain)
    inherited_citation_ids: list[str] = field(default_factory=list)
    adopted_provision: Optional[ProvisionVersion] = None


@dataclass
class SynthesisResult:
    synthesis: SynthesisOpinion
    contributions: list[SourceContribution]
    reconciliations: list[TopicReconciliation]
    confidence_scores: list[ConfidenceScore]
    lineage: dict[str, tuple[str, str]]         # synth_claim_id -> (source_answer_id, citation_id)
    review_items: list[str]
    new_citations: list[Citation]               # MUST be empty (ORCH-012 violation otherwise)
    fabricated_source_ids: list[str] = field(default_factory=list)  # HALU-013 전파
    primary_research: Optional[ResearchLiteAnswer] = None
    adopted_provision: Optional[ProvisionVersion] = None

    # --- convenience for the harness ------------------------------------- #
    @property
    def abstained(self) -> bool:
        return self.synthesis.abstained

    @property
    def authority_deficit(self) -> bool:
        return bool(self.synthesis.authority_deficit)

    @property
    def displayed_claims(self) -> list[Claim]:
        return [r.synthesis_claim for r in self.reconciliations if r.synthesis_claim is not None]

    @property
    def all_source_citations(self) -> list[Citation]:
        seen: dict[str, Citation] = {}
        for c in self.contributions:
            for cit in c.citations:
                seen[cit.citation_id] = cit
        return list(seen.values())

    @property
    def all_source_answer_ids(self) -> set[str]:
        return {c.source_answer.source_answer_id for c in self.contributions}

    @property
    def all_source_citation_ids(self) -> set[str]:
        return {cit.citation_id for c in self.contributions for cit in c.citations}

    def untraceable_claims(self) -> list[Claim]:
        """HALU-014 + codex P1-1: displayed synthesis claims that break lineage 무결성.

        Two ways a displayed conclusion is untraceable:
          (a) ID 무결성 — its citation/source ids do not trace back to a SOURCE
              citation/answer (phantom id, new mint);
          (b) 내용 무결성 — its TEXT is not entailed by the ADOPTED source's
              provision. Existence-only checks let a synthesis claim INHERIT a real
              citation id while asserting something the 조문 never supports (과장).
              We re-verify the displayed claim against the adopted 조문 본문 with the
              SAME deterministic ``verify_entailment`` the judge uses.

        Empty = lineage 무결성 100% (id + 내용 모두 실제로 지지될 때만)."""
        from src.judge import verify_entailment  # lazy — avoid import cycle

        bad: list[Claim] = []
        src_cit_ids = self.all_source_citation_ids
        src_ans_ids = self.all_source_answer_ids
        cit_by_id: dict[str, Citation] = {
            cit.citation_id: cit for c in self.contributions for cit in c.citations
        }
        recon_by_claim: dict[str, TopicReconciliation] = {
            r.synthesis_claim.claim_id: r
            for r in self.reconciliations
            if r.synthesis_claim is not None
        }
        for cl in self.displayed_claims:
            traced = self.lineage.get(cl.claim_id)
            cits_ok = bool(cl.citation_ids) and all(cid in src_cit_ids for cid in cl.citation_ids)
            if traced is None or traced[1] not in src_cit_ids or traced[0] not in src_ans_ids or not cits_ok:
                bad.append(cl)
                continue
            # (b) 내용 무결성: the displayed claim must be ENTAILED by the adopted 조문,
            # not merely cite an existing id. Unsupported → lineage violation.
            recon = recon_by_claim.get(cl.claim_id)
            if recon is not None and recon.adopted_provision is not None:
                quote = next(
                    (cit_by_id[cid].quote for cid in cl.citation_ids
                     if cid in cit_by_id and cit_by_id[cid].quote),
                    "",
                )
                check = verify_entailment(cl.proposition, quote, recon.adopted_provision.text)
                if not check.supported:
                    bad.append(cl)
        return bad


class SynthesisEngine:
    """Deterministic claim-level reconciliation of independent source answers."""

    POLICY_VERSION = "synth-v1"

    def synthesize(
        self,
        *,
        contributions: list[SourceContribution],
        as_of_date: date,
        answer_run_id: str,
        synthesis_id: str,
        client_id: str = "client_eval",
        high_risk: bool = False,
        primary_research: Optional[ResearchLiteAnswer] = None,
    ) -> SynthesisResult:
        # ORCH-008: 1 ≤ SourceAnswer ≤ 3, source_type 유일 (완결 run 불변식).
        if not (1 <= len(contributions) <= 3):
            raise ValueError("ORCH-008: a synthesis run carries 1..3 source answers")
        types = [c.source_type for c in contributions]
        if len(set(types)) != len(types):
            raise ValueError("ORCH-008: source_type must be UNIQUE per run (no channel dup)")

        # HALU-013: a fabricated citation in a source caps that source 60 + 종합 경고.
        fabricated_source_ids: list[str] = [
            c.source_answer.source_answer_id for c in contributions if c.fabricated
        ]

        # group by topic + close temporal windows for version-based conflicts ---- #
        by_topic: dict[str, list[SourceContribution]] = {}
        for c in contributions:
            by_topic.setdefault(c.topic_key, []).append(c)

        reconciliations: list[TopicReconciliation] = []
        lineage: dict[str, tuple[str, str]] = {}
        any_abstain = False
        any_conflict = False
        deficit = False

        for topic_key, group in by_topic.items():
            positions = self._positions(group, as_of_date)
            result = resolve_topic(positions, as_of_date)
            recon = self._reconcile_topic(
                topic_key=topic_key, group=group, result=result,
                synthesis_id=synthesis_id, lineage=lineage,
            )
            reconciliations.append(recon)
            if recon.alignment.status is AlignmentStatus.CONFLICT:
                any_conflict = True
            if result.abstained:
                any_abstain = True
            if result.authority_deficit:
                deficit = True

        # SynthesisOpinion (ORCH-008②: 완결 run 은 정확히 1개; 보류도 1개) ------- #
        review_items = self._review_items(
            reconciliations, high_risk=high_risk, deficit=deficit,
            fabricated_source_ids=fabricated_source_ids,
        )
        confidence_cap: Optional[float] = None
        if any_abstain and not deficit:
            confidence_cap = _UNRESOLVED_CAP
        elif deficit:
            confidence_cap = _AUTHORITY_DEFICIT_CAP

        opinion_text = self._opinion_text(
            contributions, reconciliations, primary_research=primary_research,
            abstained=any_abstain, deficit=deficit, review_items=review_items,
            high_risk=high_risk,
        )

        synthesis = SynthesisOpinion(
            synthesis_id=synthesis_id,
            answer_run_id=answer_run_id,
            client_id=client_id,
            source_answer_ids=[c.source_answer.source_answer_id for c in contributions],
            policy_version=self.POLICY_VERSION,
            opinion_text=opinion_text,
            abstained=any_abstain,
            authority_deficit=("①법령 원문 근거 미확보(비권위적 합의)" if deficit else None),
            confidence_cap=confidence_cap,
        )

        confidence_scores = self._confidence(
            synthesis_id=synthesis_id, abstained=any_abstain, deficit=deficit,
            any_conflict=any_conflict, contributions=contributions,
        )

        adopted_pv = self._adopted_provision(reconciliations)

        return SynthesisResult(
            synthesis=synthesis,
            contributions=contributions,
            reconciliations=reconciliations,
            confidence_scores=confidence_scores,
            lineage=lineage,
            review_items=review_items,
            new_citations=[],                         # engine inherits — mints NONE (ORCH-012)
            fabricated_source_ids=fabricated_source_ids,
            primary_research=primary_research,
            adopted_provision=adopted_pv,
        )

    # -- positions -------------------------------------------------------- #
    def _positions(self, group: list[SourceContribution], as_of: date) -> list[SourcePosition]:
        # close temporal windows: for version-based conflicts on the same article,
        # an earlier version's window ends at the next version's effective_from.
        efs = sorted({
            c.provision_version.effective_from
            for c in group
            if c.version_based and c.provision_version is not None
        })
        nxt = {efs[i]: efs[i + 1] for i in range(len(efs) - 1)} if len(efs) >= 2 else {}

        positions: list[SourcePosition] = []
        for c in group:
            pv = c.provision_version
            eff_from = pv.effective_from if pv else None
            eff_to = pv.effective_to if pv else None
            if c.version_based and eff_from in nxt and (eff_to is None or eff_to > nxt[eff_from]):
                eff_to = nxt[eff_from]
            positions.append(SourcePosition(
                source_type=c.source_type,
                channel_label=c.channel_label,
                authority_label=c.authority_label,
                status=c.status,
                stance=c.stance if c.answered else "",
                effective_from=eff_from,
                effective_to=eff_to,
                dispositive=c.dispositive,
                fact_match=c.fact_match,
                version_based=c.version_based,
                source_answer_id=c.source_answer.source_answer_id,
                citation_id=(c.primary_citation.citation_id if c.primary_citation else None),
                claim_id=(c.primary_claim.claim_id if c.primary_claim else None),
            ))
        return positions

    # -- per-topic reconciliation ----------------------------------------- #
    def _reconcile_topic(
        self, *, topic_key: str, group: list[SourceContribution],
        result: ResolutionResult, synthesis_id: str, lineage: dict[str, tuple[str, str]],
    ) -> TopicReconciliation:
        by_channel = {c.channel_label: c for c in group}
        answered = [c for c in group if c.answered]
        silent = [c for c in group if not c.answered]
        stances = {c.stance for c in answered}

        # alignment status (ORCH-011)
        if len(answered) <= 1 and not silent:
            status = AlignmentStatus.AGREE
        elif not answered:
            status = AlignmentStatus.SILENT
        elif len(stances) > 1:
            status = AlignmentStatus.CONFLICT
        elif silent:
            status = AlignmentStatus.AGREE      # 합의 + 침묵 소스(커버리지 갭)
        else:
            status = AlignmentStatus.AGREE

        claim_ids = [c.primary_claim.claim_id for c in group if c.primary_claim is not None]

        resolution: Optional[ConflictResolution] = None
        conflict_flag: Optional[ConflictFlag] = None
        alignment_id = f"align_{synthesis_id}_{topic_key}"

        is_conflict = status is AlignmentStatus.CONFLICT
        if is_conflict or result.outcome is not ConflictOutcome.AGREE:
            resolution = ConflictResolution(
                resolution_id=f"res_{synthesis_id}_{topic_key}",
                inputs=result.inputs,
                rule_applied=result.rule_applied,
                outcome=result.outcome.value,
            )

        alignment = ClaimAlignment(
            alignment_id=alignment_id,
            synthesis_id=synthesis_id,
            claim_ids=claim_ids,
            status=status,
            resolution_id=(resolution.resolution_id if resolution else None),
        )

        if is_conflict:
            conflict_flag = ConflictFlag(
                flag_id=f"flag_{synthesis_id}_{topic_key}",
                synthesis_id=synthesis_id,
                claim_alignment_id=alignment_id,
                sources=[c.source_type for c in answered],
                description=(
                    f"[{topic_key}] 소스 충돌 표면화(평균 금지): "
                    + " / ".join(f"{c.channel_label}{c.source_type.value}='{c.stance}'" for c in answered)
                    + f" → {result.outcome.value}: {result.rule_applied}"
                ),
                escalated_to_review=result.abstained,
            )

        # build the displayed synthesis claim — ONLY when resolved to an adopted
        # source (inherits that source's citation; NO new citation — ORCH-012).
        # A DISPLAYED synthesis claim is built only when a source is adopted — it
        # INHERITS that source's citation (creates NONE — ORCH-012). For a
        # 비권위적 합의(법령부재) the claim is a NON-authoritative guide (abstained).
        _ADOPTING = {
            ConflictOutcome.AGREE: "종합 결론",
            ConflictOutcome.TEMPORAL: "종합 결론(적용시점 유효 버전)",
            ConflictOutcome.AUTHORITY: "종합 결론(권위 위계)",
            ConflictOutcome.FACT_MISMATCH: "종합 결론(예규 원용 조정)",
            ConflictOutcome.NON_AUTHORITATIVE_CONSENSUS: "비권위 실무 가이드(법령부재·보류)",
        }
        synthesis_claim: Optional[Claim] = None
        inherited_ids: list[str] = []
        adopted_pv: Optional[ProvisionVersion] = None
        if result.outcome in _ADOPTING and result.adopted:
            adopted_pos = result.adopted[0]
            adopted = by_channel.get(adopted_pos.channel_label)
            if adopted is not None:
                adopted_pv = adopted.provision_version
            # fail-closed (codex P2-1): an adopted source with an EMPTY inherited
            # citation list cannot ground a displayed conclusion — build NO synthesis
            # claim (abstain-like) instead of indexing ``inherited_ids[0]`` (which
            # would raise on an empty list). No exception, no ungrounded claim.
            if (adopted is not None and adopted.primary_claim is not None
                    and adopted.primary_claim.citation_ids):
                src_claim = adopted.primary_claim
                inherited_ids = list(src_claim.citation_ids)
                synthesis_claim = Claim(
                    claim_id=f"synth_{synthesis_id}_{topic_key}",
                    source_answer_id=adopted.source_answer.source_answer_id,
                    proposition=(
                        f"[{_ADOPTING[result.outcome]} — {result.outcome.value}] "
                        f"{src_claim.proposition} (채택 채널 "
                        f"{adopted.channel_label}{adopted.source_type.value}, "
                        f"근거 상속: {','.join(inherited_ids)})"
                    ),
                    claim_span="synthesis-conclusion",
                    citation_ids=inherited_ids,         # INHERITED — never minted
                )
                # lineage (HALU-014): trace to the source answer + its citation
                lineage[synthesis_claim.claim_id] = (
                    adopted.source_answer.source_answer_id, inherited_ids[0],
                )

        return TopicReconciliation(
            topic_key=topic_key, alignment=alignment, resolution=resolution,
            result=result, conflict_flag=conflict_flag, synthesis_claim=synthesis_claim,
            inherited_citation_ids=inherited_ids, adopted_provision=adopted_pv,
        )

    # -- review items (HALU-008 → ORCH-004) ------------------------------- #
    def _review_items(
        self, recons: list[TopicReconciliation], *, high_risk: bool, deficit: bool,
        fabricated_source_ids: list[str],
    ) -> list[str]:
        items: list[str] = []
        for r in recons:
            res = r.result
            if res.outcome is ConflictOutcome.UNRESOLVED_ABSTAIN:
                items.append(
                    f"[미해소 충돌 · escalation H3(고위험)/H2 — {r.topic_key}] 권위·시점 동급으로 "
                    f"단정 불가 → 소스별 입장(예규 vs 심판례)을 그대로 노출하고 회계사가 사실관계에 "
                    f"맞춰 우열 판단. 다음 단계: 적용 사실관계 특정 → 유사 예규/판례 추가 조사 → "
                    f"보수적 처리 + 사전 질의(예규) 검토 ({res.rationale})."
                )
            elif res.outcome is ConflictOutcome.NON_AUTHORITATIVE_CONSENSUS:
                items.append(
                    f"[법령 원문 부재 · escalation H4(고위험)→HITL — {r.topic_key}] 실무·웹 합의는 "
                    f"법령을 대체하지 못함 → 법적 결론 보류, 실무 가이드로만 사용, confidence 캡 적용. "
                    f"다음 단계: 관련 시행령/예규 추가 확인 → 법령 근거 확보 전까지 보수적 처리 → "
                    f"회계사 검토·서명."
                )
            elif res.outcome is ConflictOutcome.TEMPORAL and res.excluded:
                items.append(
                    f"[구버전 배제 · 시점 가정 — {r.topic_key}] 일부 소스가 구 시행일 버전 기준이라 "
                    f"적용시점 유효 버전으로 대체. 다음 단계: 내부 실무서/템플릿의 구 명칭·인용을 "
                    f"현행 버전으로 갱신하고, 대상 사업연도 시행일 가정을 명시."
                )
            elif res.outcome is ConflictOutcome.FACT_MISMATCH and res.excluded:
                items.append(
                    f"[예규 원용 불가 · 사실관계 — {r.topic_key}] 사실관계 불일치 예규 원용 배제. "
                    f"다음 단계: 사실관계 동일성 재검토 후 원용 가부 확정."
                )
        if fabricated_source_ids:
            items.append(
                f"[인용 날조 경고 전파 — HALU-013] 소스 {fabricated_source_ids} 인용 검증 실패 → "
                f"해당 소스 결론 신뢰 불가·종합 반영 제외(소스 60 캡)."
            )
        if high_risk:
            items.append(SYNTHESIS_REVIEW_WARNING)
        return items

    # -- opinion text ----------------------------------------------------- #
    def _opinion_text(
        self, contributions: list[SourceContribution],
        recons: list[TopicReconciliation], *, primary_research, abstained: bool,
        deficit: bool, review_items: list[str], high_risk: bool,
    ) -> str:
        lines: list[str] = ["[종합의견 — 채널 ④ 3소스 종합]"]
        if high_risk:
            lines.insert(0, SYNTHESIS_REVIEW_WARNING)
        lines.append("■ 소스별 독립 입장:")
        for c in contributions:
            if c.answered:
                lines.append(
                    f"  - {c.channel_label} {c.source_type.value}({c.authority_label}): "
                    f"'{c.stance}'"
                )
            else:
                lines.append(
                    f"  - {c.channel_label} {c.source_type.value}: 침묵(SILENT) — 커버리지 갭"
                )
        lines.append("■ claim 단위 정합/충돌 해소(평균 금지·권위 위계·시점):")
        for r in recons:
            lines.append(
                f"  - [{r.topic_key}] {r.alignment.status.value} → {r.result.outcome.value}: "
                f"{r.result.rule_applied}"
            )

        # surface the权위 소스(primary)의 substantive 법리 — 규칙→사실·한도·기한·신고영향
        pr = primary_research
        if pr is not None and not abstained:
            lines.append("■ 종합 결론(권위 소스 상속 — 새 인용 생성 없음):")
            lines.append(f"  {pr.legal_conclusion}")
            if pr.reasoning:
                lines.append(f"  · 적용 논리(규칙→사실): {pr.reasoning}")
            if pr.limits_deadlines:
                lines.append(f"  · 한도·기한: {pr.limits_deadlines}")
            if pr.filing_impact:
                lines.append(f"  · 신고 영향: {pr.filing_impact}")
        elif pr is not None and abstained:
            # 보류해도 권위 소스의 분석은 보여준다(방어가능성+유용성 양립, docs/08 §5)
            label = "①법령 문언 분석(권위 소스)" if not deficit else "②실무 가이드(비권위·법령부재)"
            lines.append(f"■ 권위/주요 소스 입장 — {label}:")
            lines.append(f"  {pr.legal_conclusion}")
            if pr.reasoning:
                lines.append(f"  · 분석: {pr.reasoning}")
            if pr.limits_deadlines:
                lines.append(f"  · 한도·기한: {pr.limits_deadlines}")

        if abstained:
            if deficit:
                lines.append(
                    "■ 결론(보류): 법령 원문 근거 미확보 — 법적 결론은 보류하고 위 내용은 "
                    "실무 가이드로만 제시(법적결론↔실무가이드 구분, confidence 캡, 고위험 HITL)."
                )
            else:
                lines.append(
                    "■ 결론(보류): 권위·시점 동급의 미해소 충돌로 종합 단정 보류 — 소스별 입장을 "
                    "그대로 노출하고 회계사가 사실관계에 맞춰 우열 판단(다수결/평균 금지)."
                )

        # consolidated 리스크·통제 (권위 소스 risks + 종합 단계 리스크)
        risk_lines: list[str] = list(pr.risks) if (pr is not None and pr.risks) else []
        if any(r.result.outcome is ConflictOutcome.TEMPORAL and r.result.excluded for r in recons):
            risk_lines.append("구 시행일 버전 인용 잔존 시 한도 오산정·가산세 노출 → 인용 갱신 통제")
        if abstained and not deficit:
            risk_lines.append("미해소 충돌을 단정하면 과신 위험 → 보류 + 사실관계 기반 재검토")
        if deficit:
            risk_lines.append("법령 근거 없이 실무 합의를 단정하면 권위 부재 위험 → 가이드 한정·법령 확인")
        if risk_lines:
            lines.append("■ 리스크·통제: " + " / ".join(risk_lines))

        if review_items:
            lines.append("■ 회계사 검토 필요사항(다음 단계 — actionable):")
            lines.extend(f"  · {it}" for it in review_items)
        return "\n".join(lines)

    # -- confidence (HALU-006 분리 저장) ---------------------------------- #
    def _confidence(
        self, *, synthesis_id: str, abstained: bool, deficit: bool, any_conflict: bool,
        contributions: list[SourceContribution],
    ) -> list[ConfidenceScore]:
        scores: list[ConfidenceScore] = []
        for c in contributions:
            scores.append(ConfidenceScore(
                target_kind="SOURCE_ANSWER", target_id=c.source_answer.source_answer_id,
                retrieval_confidence=(1.0 if c.answered else 0.0),
                generation_confidence=(1.0 if (c.answered and c.research is not None) else None),
                abstained=not c.answered,
                reason=("answered" if c.answered else "SILENT"),
            ))
        gen_conf = 0.0 if abstained else (0.6 if deficit else 1.0)
        scores.append(ConfidenceScore(
            target_kind="SYNTHESIS", target_id=synthesis_id,
            retrieval_confidence=(0.5 if deficit else 1.0),
            generation_confidence=gen_conf,
            abstained=abstained,
            reason=(
                "법령부재(비권위 합의)" if deficit else
                "미해소 충돌 보류" if abstained else
                "충돌 해소(결정테이블)" if any_conflict else "합의"
            ),
        ))
        return scores

    def _adopted_provision(self, recons: list[TopicReconciliation]) -> Optional[ProvisionVersion]:
        for r in recons:
            if r.adopted_provision is not None:
                return r.adopted_provision        # authoritative anchor (temporal check + judge)
        return None


def default_synthesis_engine() -> SynthesisEngine:
    return SynthesisEngine()
