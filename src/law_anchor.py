"""src/law_anchor.py — slice ① SourceAnswer(LAW_MCP) builder (deterministic core).

# API-002/003/004 anchored answer · PROV-002/004/005 인용=버전객체+pinpoint+시점
# HALU-001 무근거 단정 금지 (every claim carries a version-object Citation)

Given a version-pinned ``ProvisionLookupResult`` (from a LawDataSource), this
builds the DETERMINISTIC part of a channel-① answer:
  * a ``SourceAnswer`` (source_type=LAW_MCP) that ANCHORS to the provision,
  * a ``Claim`` whose proposition is a provenance statement (NOT a legal
    conclusion), and
  * a ``Citation`` pointing at the ``ProvisionVersion`` (source_kind=
    PROVISION_VERSION) with pinpoint (source_locator=조문) + applicable_basis +
    a verbatim ``quote`` excerpt.

What this builder does NOT do (by design — PROMPT.md §4): it does NOT draft the
legal/세무 conclusion or the entailment-bearing reasoning. That requires the
LLM-judge / human-CPA pass (PENDING_JUDGE). The answer_text here is an anchored
provenance template, never a confident legal holding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from contract.base import ApplicableBasis, BasisKind, SourceKind, SourceType
from contract.cluster_d_provenance import ProvisionVersion, SourceSnapshot
from contract.cluster_f_qa import Citation, Claim, SourceAnswer
from src.ai.law_data_source import ProvisionLookupResult
from src.source_registry import SourceRegistry

# authority hierarchy (docs/02 §5): 법률 > 시행령 > 시행규칙/고시 ...
_AUTHORITY_RANK = {"법률": 1, "시행령": 2, "시행규칙": 3, "고시": 4, "예규": 5}

# Standard high-risk reviewer warning (HALU-009). Attached to high-risk answers
# at EVERY output stage; its absence on a high-risk answer trips the
# MISSING_REVIEW_WARNING hard gate (cap 60, docs/09 §2).
REVIEW_WARNING = (
    "[회계사 검토 필요] 본 답변은 법령 원문 앵커링(결정적 부분)만 제공합니다. "
    "사실관계 적용·법리 판단·시점 가정은 회계사(CPA) 검토·서명이 필요합니다."
)

_QUOTE_MAX = 280


@dataclass
class LawSourceAnswerBundle:
    """Everything slice ① emits for one law query (deterministic outputs)."""

    source_answer: SourceAnswer
    claim: Claim
    citation: Citation
    provision_version: ProvisionVersion
    snapshot: SourceSnapshot
    applicable_basis: ApplicableBasis
    review_warnings: list[str] = field(default_factory=list)

    @property
    def source_objects(self) -> list[object]:
        """Version objects to register for citation verification (P1-1)."""
        return [self.provision_version, self.snapshot]


def build_law_source_answer(
    *,
    lookup: ProvisionLookupResult,
    client_id: str,
    answer_run_id: str,
    source_answer_id: str,
    basis_kind: BasisKind = BasisKind.FISCAL_YEAR,
    source_type_label: str = "법률",
    matter_id: Optional[str] = None,
    high_risk: bool = False,
    registry: Optional[SourceRegistry] = None,
    answer_source_type: SourceType = SourceType.LAW_MCP,
    channel_label: str = "①",
) -> LawSourceAnswerBundle:
    pv = lookup.provision_version
    snap = lookup.snapshot

    basis = ApplicableBasis(
        basis_kind=basis_kind,
        as_of_date=lookup.as_of_date,
        matter_id=matter_id,
    )

    quote = pv.text.strip().replace("\n", " ")
    if len(quote) > _QUOTE_MAX:
        quote = quote[:_QUOTE_MAX] + "…"

    citation = Citation(
        citation_id=f"cit_{source_answer_id}_{pv.provision_version_id}",
        source_answer_id=source_answer_id,
        source_kind=SourceKind.PROVISION_VERSION,
        source_object_id=pv.provision_version_id,           # version object (no raw URL)
        claim_span="provenance-anchor",
        source_locator=f"{lookup.law_name} {lookup.article_label}",  # pinpoint (PROV-004)
        quote=quote,                                        # verbatim support excerpt
        applicable_basis=basis,                             # 시점 (PROV-005)
        support_type="DIRECT",
        authority_rank=_AUTHORITY_RANK.get(source_type_label, 5),
    )

    proposition = (
        f"{lookup.law_name} {lookup.article_label}({lookup.article_title})의 "
        f"{pv.effective_from:%Y-%m-%d} 시행 버전이 적용시점("
        f"{lookup.as_of_date:%Y-%m-%d}, {basis_kind.value}) 기준 유효 조문이다."
    )
    claim = Claim(
        claim_id=f"claim_{source_answer_id}",
        source_answer_id=source_answer_id,
        proposition=proposition,
        claim_span="provenance-anchor",
        citation_ids=[citation.citation_id],
    )

    warnings: list[str] = []
    promulgated_str = pv.promulgated_date.strftime("%Y-%m-%d") if pv.promulgated_date else "N/A"
    answer_text = (
        f"[법령 앵커 — 채널 {channel_label}] {proposition}\n"
        f"근거: {lookup.law_name} {lookup.article_label} "
        f"(시행 {pv.effective_from:%Y-%m-%d}, 공포 {promulgated_str})\n"
        f"※ 법리·사실적용 결론은 회계사/judge 검토 보류(PENDING_JUDGE)."
    )
    if high_risk:
        warnings.append(REVIEW_WARNING)
        answer_text = f"{REVIEW_WARNING}\n{answer_text}"

    source_answer = SourceAnswer(
        source_answer_id=source_answer_id,
        answer_run_id=answer_run_id,
        source_type=answer_source_type,
        answer_text=answer_text,
        retrieval_run_id=None,
        client_id=client_id,
        matter_id=matter_id,
    )

    bundle = LawSourceAnswerBundle(
        source_answer=source_answer,
        claim=claim,
        citation=citation,
        provision_version=pv,
        snapshot=snap,
        applicable_basis=basis,
        review_warnings=warnings,
    )

    # P1-B (codex): registry verification is MANDATORY at the citation boundary,
    # not only inside the eval harness. A citation that does not resolve to a
    # registered version source object (NOT_FOUND) or whose kind disagrees
    # (KIND_MISMATCH) is REFUSED here, so a non-eval consumer can never obtain an
    # unverifiable citation (registry bypass closed; fail-closed).
    #   * If an authoritative `registry` is supplied, the citation is verified
    #     against it AS-IS — a provision the caller never registered (미존재 조문)
    #     leaves the citation unresolved → reject.
    #   * Otherwise a local registry is built from THIS bundle's own version
    #     objects (structural self-consistency guard) and the citation verified.
    verify_registry = registry
    if verify_registry is None:
        verify_registry = SourceRegistry()
        verify_registry.register_all(bundle.source_objects)
    verify_registry.require_citation(bundle.citation)

    return bundle
