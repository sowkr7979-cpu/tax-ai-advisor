"""src/strategy.py — Strategy Agent (선택지 생성, 설계서 §3-5 · §4-2 ★Strategy).

Given one issue + its 종합의견(SynthesisOpinion) + 리스크 + the version-pinned
provision it is grounded in, this LLM agent produces the **보수/중립/적극 3종
선택지**(`StrategyOption`) of the 선택지 비교표 (§3-5):

  예상 세부담 · 세무 리스크(과세논리) · 방어 가능성(방어논리) · 필요 증빙 · 회계사 검토 포인트.

CORE INVARIANTS (절대):
  * **인용 날조 금지 (HALU-001/003)** — the LLM fills only the qualitative cells; the
    Citation is bound DETERMINISTICALLY to the RETRIEVED ``ProvisionVersion``
    (회수된 버전 객체에 한정). Each option's citation is verified against a
    ``SourceRegistry`` (존재/kind 정합) — an unregistered/fabricated id is refused
    (``CitationVerificationError``). The model never mints a citation id.
  * **grounding (HALU-003)** — each option's ``support_quote`` must be a verbatim
    substring of the provision text; the deterministic ``verify_entailment`` re-checks
    grounding (the model's self-report is never trusted to upgrade a miss).
  * **적극 가드레일 (HALU-009)** — the 적극 option always carries a guardrail / review
    warning; its absence is repaired (fail-closed) so a high-risk option can never be
    surfaced without the escalation note.

Determinism: the LLM call goes through ``LLMClient`` (replay by default); the prompt
is centralized (``build_strategy_prompt``) so the recorded request key is stable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from contract.cluster_d_provenance import ProvisionVersion
from contract.cluster_f_qa import Citation
from src.ai.law_data_source import ProvisionLookupResult
from src.ai.llm_client import LLMClient, LLMResponse, default_llm_client
from src.draft import StrategyOption
from src.judge import verify_entailment
from src.law_anchor import REVIEW_WARNING
from src.legal_research import _top_level_objects  # shared robust JSON extraction
from src.source_registry import SourceRegistry

_REPO_ROOT = Path(__file__).resolve().parents[1]
_STRATEGY_PROMPT_PATH = _REPO_ROOT / "prompts" / "strategy.md"
_STRATEGY_MAX_TOKENS = 8000
_QUOTE_MAX = 280

# 적극 절세 가드레일(AGT-008/HALU-009) — 적극 선택지에 항상 부착(누락 시 fail-closed 복구).
AGGRESSIVE_GUARDRAIL = (
    "[적극 절세 가드레일·검토경고] 적극적 처리는 세무조사 시 손금 부인 가능성·가산세 노출이 "
    "크다. 과세논리(과세관청 입장)와 방어논리(소명·증빙)를 함께 적시하고, Reviewer(회계사) "
    "승인(H4·H5) 전에는 고객 전달본에 포함하지 않는다(AGT-008/OUT-004)."
)

_ORDER = {"보수": 0, "중립": 1, "적극": 2}
_REQUIRED_KEYS = ("보수", "중립", "적극")


class StrategyGenerationError(RuntimeError):
    """The model output could not be parsed into 3 grounded strategy options."""


@dataclass
class StrategyResult:
    """The Strategy Agent output for one issue (선택지 비교표 한 묶음)."""

    options: list[StrategyOption]
    citation_id: str                    # the version-object citation every option inherits
    review_warning: str
    entailment_supported: bool          # deterministic grounding of options to the 조문
    high_risk: bool = True
    llm: Optional[LLMResponse] = field(default=None)

    @property
    def has_all_three(self) -> bool:
        return {o.option_key for o in self.options} >= set(_REQUIRED_KEYS)


# --------------------------------------------------------------------------- #
# Prompt construction (centralized → stable replay key)
# --------------------------------------------------------------------------- #
def _system_prompt() -> str:
    return _STRATEGY_PROMPT_PATH.read_text(encoding="utf-8")


def build_strategy_prompt(
    *, lookup: ProvisionLookupResult, issue: str, synthesis_opinion: str,
    risks: list[str],
) -> tuple[str, str]:
    """(system, user). Deterministic given (provision, issue, 종합의견, risks) so the
    recorded request key is identical between record and replay."""
    pv = lookup.provision_version
    risk_block = "\n".join(f"- {r}" for r in risks) if risks else "(특이 리스크 미식별)"
    user = (
        f"[쟁점]\n{issue}\n\n"
        f"[회수된 조문 — 이 본문에만 근거하라]\n"
        f"법령: {lookup.law_name}\n"
        f"조문: {lookup.article_label} ({lookup.article_title})\n"
        f"시행일: {pv.effective_from:%Y-%m-%d}\n"
        f"본문:\n{pv.text}\n\n"
        f"[종합의견(3소스 종합 — 참고)]\n{synthesis_opinion}\n\n"
        f"[식별된 리스크]\n{risk_block}\n\n"
        f"위 조문 본문·종합의견에 근거해 보수/중립/적극 3종 선택지를 지정된 JSON 스키마로만 생성하라."
    )
    return _system_prompt(), user


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
    objs = _top_level_objects(text)
    if not objs:
        raise StrategyGenerationError("no JSON object in strategy model output")
    last_err: Optional[Exception] = None
    for obj in reversed(objs):
        try:
            return json.loads(obj)
        except json.JSONDecodeError as exc:
            last_err = exc
    raise StrategyGenerationError(f"invalid JSON in strategy output: {last_err}")


_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", s or "").strip()


def _grounded_quote(model_quote: str, provision_text: str, fallback: str) -> str:
    mq = _norm(model_quote)
    if mq and mq in _norm(provision_text):
        return mq if len(mq) <= _QUOTE_MAX else mq[:_QUOTE_MAX] + "…"
    return fallback


def _cell(value: object, fallback: str) -> str:
    s = str(value or "").strip()
    return s if s else fallback


# --------------------------------------------------------------------------- #
# Strategy Agent
# --------------------------------------------------------------------------- #
class StrategyAgent:
    """Generates the 보수/중립/적극 선택지 for one issue (LLM over replay/record)."""

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self.client = llm_client or default_llm_client()

    def generate(
        self,
        *,
        lookup: ProvisionLookupResult,
        issue: str,
        synthesis_opinion: str,
        risks: list[str],
        citation: Citation,
        registry: SourceRegistry,
        anchor_quote: str = "",
        high_risk: bool = True,
        tag: str = "strategy",
    ) -> StrategyResult:
        """Produce 3 options grounded in ``lookup``'s provision. ``citation`` is the
        version-object Citation every option INHERITS (회수된 버전 객체에 한정) — it is
        verified against ``registry`` so a fabricated/unregistered citation is refused."""
        # citation날조 차단(HALU-003 G2): the inherited citation must resolve to a
        # registered version source object BEFORE we attach it to any option.
        registry.require_citation(citation)

        pv: ProvisionVersion = lookup.provision_version
        fallback_quote = anchor_quote.strip() or (citation.quote or "").strip()

        system, user = build_strategy_prompt(
            lookup=lookup, issue=issue, synthesis_opinion=synthesis_opinion, risks=risks,
        )
        resp = self.client.complete(system=system, user=user, tag=tag,
                                    max_tokens=_STRATEGY_MAX_TOKENS)
        data = _extract_json(resp.text)

        raw_options = data.get("options")
        if not isinstance(raw_options, list) or not raw_options:
            raise StrategyGenerationError("strategy output has no 'options' array")

        by_key: dict[str, dict] = {}
        for o in raw_options:
            if isinstance(o, dict) and str(o.get("option_key", "")).strip() in _REQUIRED_KEYS:
                by_key[str(o["option_key"]).strip()] = o
        missing = [k for k in _REQUIRED_KEYS if k not in by_key]
        if missing:
            raise StrategyGenerationError(
                f"strategy output missing required option(s) {missing} (보수/중립/적극 필수)"
            )

        options: list[StrategyOption] = []
        entail_ok = True
        for key in _REQUIRED_KEYS:
            o = by_key[key]
            quote = _grounded_quote(str(o.get("support_quote", "")), pv.text, fallback_quote)
            # 적극 가드레일(HALU-009): always present — repaired fail-closed if omitted.
            cpa_point = _cell(o.get("cpa_review_point"), "회계사 검토 필요")
            if key == "적극":
                guard = _norm(str(o.get("guardrail", ""))) or AGGRESSIVE_GUARDRAIL
                cpa_point = f"{cpa_point} · {guard}"
            tax_risk = _cell(o.get("tax_risk"), "리스크 — 회계사 검토 필요(과세논리)")
            defensibility = _cell(o.get("defensibility"), "방어 가능성 — 회계사 검토 필요(방어논리)")
            opt = StrategyOption(
                option_key=key,
                label=_cell(o.get("label"), f"{key}적 처리"),
                expected_tax_burden=_cell(o.get("expected_tax_burden"), "검토 필요"),
                tax_risk=tax_risk,
                defensibility=defensibility,
                required_evidence=_cell(o.get("required_evidence"), "기본 자료·증빙"),
                cpa_review_point=cpa_point,
                citation_ids=[citation.citation_id],   # INHERITED version object — never minted
            )
            options.append(opt)

            # deterministic grounding (HALU-003): the option's qualitative claim must be
            # anchored to the 조문 — verbatim quote ⊂ provision AND the provision subject
            # named. The 보수/중립/적극 labels are advisory, so a per-option miss only
            # lowers ``entailment_supported`` (it does not fabricate); the citation
            # itself is already registry-verified above.
            check = verify_entailment(
                f"{opt.label}: {opt.tax_risk} / {opt.defensibility}", quote, pv.text
            )
            entail_ok = entail_ok and bool(check.deterministic)

        options.sort(key=lambda o: _ORDER.get(o.option_key, 9))
        return StrategyResult(
            options=options,
            citation_id=citation.citation_id,
            review_warning=REVIEW_WARNING,
            entailment_supported=entail_ok,
            high_risk=high_risk,
            llm=resp,
        )


def default_strategy_agent(llm_client: Optional[LLMClient] = None) -> StrategyAgent:
    return StrategyAgent(llm_client=llm_client)
