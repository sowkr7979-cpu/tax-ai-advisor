"""src/legal_research.py — slice ① Research-lite answer generator (docs/08 §1).

This is the ACTUAL channel-① TIW answer: given a version-pinned provision (from
``src.law_anchor.build_law_source_answer``), it asks the LLM to draft a legal
answer **grounded in that single provision**, then assembles a defensible,
version-cited ``ResearchLiteAnswer``:

  * a legal-conclusion ``Claim`` carrying a ``Citation`` to the SAME retrieved
    ``ProvisionVersion`` (no fabrication — the citation always points at the
    registered version object, never at something the model named), and
  * a high-risk / uncertain reviewer warning (HALU-009) when the conclusion is
    assertive or the model flags ``needs_review``.

Grounding guards (HALU-001/003):
  * The model may NOT introduce another provision/ruling/precedent — the citation
    is built deterministically to the retrieved pv.
  * ``support_quote`` is accepted only if it is a verbatim substring (whitespace-
    normalized) of the provision text; otherwise it falls back to the anchor
    quote. A non-grounded quote can therefore never enter a citation.

Determinism: the LLM call goes through ``LLMClient`` (replay by default). Prompt
construction is centralized in ``build_generation_prompt`` so the recorded
request key is identical between record and replay.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from contract.base import BasisKind, ConfidentialityLevel, SourceKind, SourceType
from contract.cluster_d_provenance import ProvisionVersion, SourceSnapshot
from contract.cluster_f_qa import Citation, Claim, SourceAnswer
from src.ai.law_data_source import ProvisionLookupResult
from src.ai.llm_client import LLMClient, LLMResponse, default_llm_client
from src.law_anchor import REVIEW_WARNING, LawSourceAnswerBundle, build_law_source_answer
from src.source_registry import SourceRegistry

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GEN_PROMPT_PATH = _REPO_ROOT / "prompts" / "generate_research.md"
_QUOTE_MAX = 280
_GEN_MAX_TOKENS = 8000


class ResearchGenerationError(RuntimeError):
    """The model output could not be parsed into a grounded Research-lite answer."""


class ConfidentialitySendError(RuntimeError):
    """L3/L4 (client-identifying) context must NOT be sent to the external LLM
    (codex P2-2, docs/01 §8 / API-005). Channel ① sends only L0 PUBLIC statute
    text + the user's legal question — never client material. This is the
    enforced send-boundary guard the llm_client docstring delegates to callers."""


@dataclass
class ResearchLiteAnswer:
    """The full channel-① answer for one law query (deterministic anchor + LLM法리)."""

    bundle: LawSourceAnswerBundle
    legal_conclusion: str
    certainty: str
    reasoning: str
    limits_deadlines: str
    filing_impact: str
    risks: list[str]
    spotted_issues: list[str]
    needs_review: bool
    abstained: bool
    answer_text: str
    conclusion_claim: Claim
    conclusion_citation: Citation
    review_warnings: list[str] = field(default_factory=list)
    llm: Optional[LLMResponse] = None

    @property
    def provision_version(self) -> ProvisionVersion:
        return self.bundle.provision_version

    @property
    def snapshot(self) -> SourceSnapshot:
        return self.bundle.snapshot

    @property
    def source_answer(self) -> SourceAnswer:
        return self.bundle.source_answer

    @property
    def claims(self) -> list[Claim]:
        return [self.bundle.claim, self.conclusion_claim]

    @property
    def citations(self) -> list[Citation]:
        return [self.bundle.citation, self.conclusion_citation]


# --------------------------------------------------------------------------- #
# Prompt construction (centralized → stable replay key)
# --------------------------------------------------------------------------- #
def _system_prompt() -> str:
    return _GEN_PROMPT_PATH.read_text(encoding="utf-8")


def build_generation_prompt(lookup: ProvisionLookupResult, question_text: str) -> tuple[str, str]:
    """(system, user). Deterministic given the (replayed) provision + question —
    NOTE: does NOT depend on high_risk (the reviewer warning is attached
    deterministically post-generation), so the fixture key is stable across risk
    flags."""
    pv = lookup.provision_version
    prom = pv.promulgated_date.strftime("%Y-%m-%d") if pv.promulgated_date else "N/A"
    user = (
        f"[질문]\n{question_text}\n\n"
        f"[회수된 조문 — 이 본문에만 근거하라]\n"
        f"법령: {lookup.law_name}\n"
        f"조문: {lookup.article_label} ({lookup.article_title})\n"
        f"시행일: {pv.effective_from:%Y-%m-%d} / 공포일: {prom}\n"
        f"본문:\n{pv.text}\n\n"
        f"위 조문 본문에만 근거해, 지정된 JSON 스키마로만 답하라."
    )
    return _system_prompt(), user


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ResearchGenerationError("no JSON object in model output")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ResearchGenerationError(f"invalid JSON in model output: {exc}") from exc


_WS = re.compile(r"\s+")


def _normalize(s: str) -> str:
    return _WS.sub(" ", s or "").strip()


def _grounded_quote(model_quote: str, provision_text: str, fallback: str) -> str:
    """Accept the model's support_quote ONLY if it is a verbatim (whitespace-
    normalized) substring of the provision text; else fall back to the anchor
    quote. Prevents quote fabrication at the citation boundary (HALU-003)."""
    mq = _normalize(model_quote)
    if mq and mq in _normalize(provision_text):
        return mq if len(mq) <= _QUOTE_MAX else mq[:_QUOTE_MAX] + "…"
    return fallback


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if value:
        return [str(value).strip()]
    return []


# --------------------------------------------------------------------------- #
# Generator
# --------------------------------------------------------------------------- #
def generate_research_answer(
    *,
    lookup: ProvisionLookupResult,
    question_text: str,
    client_id: str,
    answer_run_id: str,
    source_answer_id: str,
    source_type_label: str = "법률",
    high_risk: bool = False,
    confidentiality_level: ConfidentialityLevel = ConfidentialityLevel.L0_PUBLIC,
    llm_client: Optional[LLMClient] = None,
    registry: Optional[SourceRegistry] = None,
    answer_source_type: SourceType = SourceType.LAW_MCP,
    channel_label: str = "①",
    retrieval_run_id: Optional[str] = None,
    basis_kind: BasisKind = BasisKind.FISCAL_YEAR,
) -> ResearchLiteAnswer:
    # 0) confidentiality send-boundary guard (codex P2-2, docs/01 §8 / API-005):
    # block BEFORE any external-LLM send. The Anthropic default path is NOT
    # zero-retention, so L3/L4 (client-identifying) context may never be routed
    # through it. Channel ① is L0 公開법령 only; anything client-scoped fails closed.
    if confidentiality_level.is_client_scoped:
        raise ConfidentialitySendError(
            f"기밀등급 {confidentiality_level.value}(L3/L4)는 외부 LLM(채널 ①) 송신 차단 — "
            f"slice ① 은 L0 공개법령만 허용 (docs/01 §8, API-005)."
        )

    client = llm_client or default_llm_client()

    # 1) deterministic anchor (provenance claim + citation + registration/verify)
    bundle = build_law_source_answer(
        lookup=lookup,
        client_id=client_id,
        answer_run_id=answer_run_id,
        source_answer_id=source_answer_id,
        source_type_label=source_type_label,
        basis_kind=basis_kind,
        high_risk=False,            # warning is attached below per needs_review/high_risk
        registry=registry,
        answer_source_type=answer_source_type,
        channel_label=channel_label,
    )
    pv = bundle.provision_version
    if retrieval_run_id is not None:
        # link the answer to its RetrievalRun (RAG-013 / SEC-007 reproducibility)
        bundle.source_answer.retrieval_run_id = retrieval_run_id

    # 2) LLM legal reasoning, grounded in the provision text
    system, user = build_generation_prompt(lookup, question_text)
    resp = client.complete(system=system, user=user, tag=f"gen_{source_answer_id}",
                           max_tokens=_GEN_MAX_TOKENS)
    data = _extract_json(resp.text)

    legal_conclusion = str(data.get("legal_conclusion", "")).strip()
    if not legal_conclusion:
        raise ResearchGenerationError("model produced no legal_conclusion")
    certainty = str(data.get("certainty", "해석")).strip() or "해석"
    reasoning = str(data.get("reasoning", "")).strip()
    limits_deadlines = str(data.get("limits_deadlines", "")).strip()
    filing_impact = str(data.get("filing_impact", "")).strip()
    risks = _as_list(data.get("risks"))
    spotted_issues = _as_list(data.get("issues"))
    needs_review = bool(data.get("needs_review", True))
    abstained = bool(data.get("abstained", False))

    # 3) grounded legal-conclusion citation → SAME retrieved pv (no fabrication)
    quote = _grounded_quote(str(data.get("support_quote", "")), pv.text, bundle.citation.quote)
    conclusion_citation = Citation(
        citation_id=f"cit_{source_answer_id}_concl",
        source_answer_id=source_answer_id,
        source_kind=SourceKind.PROVISION_VERSION,
        source_object_id=pv.provision_version_id,
        claim_span="legal-conclusion",
        source_locator=bundle.citation.source_locator,
        quote=quote,
        applicable_basis=bundle.applicable_basis,
        support_type="DIRECT",
        authority_rank=bundle.citation.authority_rank,
    )
    # registry boundary (codex P1-B): the conclusion citation must also resolve to
    # a registered version object — fail-closed if not.
    verify_registry = registry
    if verify_registry is None:
        verify_registry = SourceRegistry()
        verify_registry.register_all(bundle.source_objects)
    verify_registry.require_citation(conclusion_citation)

    conclusion_claim = Claim(
        claim_id=f"claim_{source_answer_id}_concl",
        source_answer_id=source_answer_id,
        proposition=legal_conclusion,
        claim_span="legal-conclusion",
        citation_ids=[conclusion_citation.citation_id],
    )

    # 4) compose the user-facing answer text + reviewer warning (HALU-009)
    warnings: list[str] = list(bundle.review_warnings)
    parts = [
        f"[법령 앵커 — 채널 {channel_label}] {bundle.claim.proposition}",
        f"근거 조문: {lookup.law_name} {lookup.article_label} "
        f"(시행 {pv.effective_from:%Y-%m-%d})",
        f"■ 법리 결론 ({certainty}): {legal_conclusion}",
    ]
    if reasoning:
        parts.append(f"■ 적용 논리(규칙→사실): {reasoning}")
    if limits_deadlines:
        parts.append(f"■ 한도·기한: {limits_deadlines}")
    if filing_impact:
        parts.append(f"■ 신고 영향: {filing_impact}")
    if risks:
        parts.append("■ 리스크·통제: " + " / ".join(risks))
    if spotted_issues:
        parts.append("■ 검토 쟁점: " + " / ".join(spotted_issues))
    if abstained:
        parts.append("※ 시점/근거 한계로 일부 결론은 보류(되물음 필요).")
    if high_risk or needs_review:
        if REVIEW_WARNING not in warnings:
            warnings.append(REVIEW_WARNING)
        parts.insert(0, REVIEW_WARNING)
    answer_text = "\n".join(parts)

    # keep the SourceAnswer.answer_text in sync with the rendered answer
    bundle.source_answer.answer_text = answer_text

    return ResearchLiteAnswer(
        bundle=bundle,
        legal_conclusion=legal_conclusion,
        certainty=certainty,
        reasoning=reasoning,
        limits_deadlines=limits_deadlines,
        filing_impact=filing_impact,
        risks=risks,
        spotted_issues=spotted_issues,
        needs_review=needs_review,
        abstained=abstained,
        answer_text=answer_text,
        conclusion_claim=conclusion_claim,
        conclusion_citation=conclusion_citation,
        review_warnings=warnings,
        llm=resp,
    )
