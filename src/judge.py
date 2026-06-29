"""src/judge.py — LLM-judge for slice ① judgment dimensions (docs/09 §7).

Scores a generated ``ResearchLiteAnswer`` on the four JUDGE dimensions
(legal_reasoning 20 · issue_spotting 10 · risk 11 · output 9) and evaluates
**citation entailment** (does each cited provision excerpt actually support its
claim — HALU-003). The judge reads ``prompts/judge.md`` (strict rubric) and the
case's **gold expected issues** (independent gold, not the model's own list) so
issue-spotting is gold-anchored, not self-graded.

Citation entailment is verified DETERMINISTICALLY (``verify_entailment``), not by
trusting the judge's self-reported ``supported`` bool (codex P1-1). For each real
Citation the cited excerpt must be a verbatim substring of the provision AND the
claim's statutory anchors (조문 참조·조문제목 핵심어) must actually appear in the
provision text. The judge's own ``supported`` flag is AUXILIARY only — it can
corroborate but can never UPGRADE a deterministic miss (the final per-citation
verdict is ``deterministic ∧ judge``). Unsupported → FABRICATED_CITATION (cap 60).

Honesty contract (PROMPT.md §3): the judge is STRICT — "구현됨=만점" is forbidden;
unsupported assertions, ignored timing, and overconfidence are penalized. Dimension
scores MUST be exactly one of the frozen buckets 0/25/50/75/100 — an out-of-range
or off-bucket value is REFUSED (``JudgeError``), never silently snapped (codex P1-2).

Determinism: the call goes through ``LLMClient`` (replay by default). Prompt
construction is centralized so the recorded request key is stable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from rules.hard_gates import SCORE_BUCKETS
from src.ai.llm_client import LLMClient, LLMResponse, default_llm_client
from src.legal_research import ResearchLiteAnswer, _top_level_objects

_REPO_ROOT = Path(__file__).resolve().parents[1]
_JUDGE_PROMPT_PATH = _REPO_ROOT / "prompts" / "judge.md"
_SYNTH_JUDGE_PROMPT_PATH = _REPO_ROOT / "prompts" / "judge_synthesis.md"
_JUDGE_DIMS = ("legal_reasoning", "issue_spotting", "risk", "output")
_JUDGE_MAX_TOKENS = 6000
_PROVISION_MAX = 6000


class JudgeError(RuntimeError):
    """The judge output could not be parsed into a valid verdict (fail-closed)."""


@dataclass
class EntailmentCheck:
    claim: str
    supported: bool                         # FINAL verdict (deterministic ∧ judge)
    rationale: str = ""
    deterministic: Optional[bool] = None    # deterministic verification (primary)
    judge_supported: Optional[bool] = None  # judge self-report (auxiliary only)


@dataclass
class JudgeVerdict:
    fractions: dict[str, float]            # dim -> 0..1 (snapped bucket / 100)
    entailments: list[EntailmentCheck]
    missed_issues: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    rationale: str = ""
    llm: Optional[LLMResponse] = None

    @property
    def all_supported(self) -> bool:
        # Fail-closed: with NO entailment verdicts we cannot prove support → False.
        return bool(self.entailments) and all(e.supported for e in self.entailments)

    @property
    def buckets(self) -> dict[str, int]:
        return {d: round(self.fractions[d] * 100) for d in self.fractions}


def _exact_bucket_fraction(value) -> float:
    """Accept a judge score ONLY if it is EXACTLY one of the frozen buckets
    (0/25/50/75/100); otherwise fail-closed (codex P1-2).

    The old behaviour snapped any number to the nearest bucket — so an
    out-of-range 101 silently became a perfect 100, and an off-bucket 88 became
    75/100. That hides a malformed/over-generous judge. We now REFUSE anything
    that is not on the bucket grid (``JudgeError``); the caller leaves the
    dimension PENDING (never full marks)."""
    try:
        pct = float(value)
    except (TypeError, ValueError):
        raise JudgeError(f"non-numeric score: {value!r}")
    if pct not in {float(b) for b in SCORE_BUCKETS}:
        raise JudgeError(
            f"judge score {pct!r} is not a frozen bucket {SCORE_BUCKETS} — "
            f"refusing to snap (fail-closed)"
        )
    return pct / 100.0


# --------------------------------------------------------------------------- #
# Deterministic citation entailment (codex P1-1, HALU-003)
# --------------------------------------------------------------------------- #
_WS = re.compile(r"\s+")
_ARTICLE_RE = re.compile(r"제\d+조(?:의\d+)?")
_TRUNC_RE = re.compile(r"(?:…|\.\.\.)\s*$")          # truncation marker on a quote
_TITLE_RE = re.compile(r"^\s*제\d+조(?:의\d+)?\s*\(([^)]+)\)")


def _normalize(s: str) -> str:
    return _WS.sub(" ", s or "").strip()


def _provision_subject(provision_text: str) -> str:
    """The provision's distinctive SUBJECT term, parsed deterministically from its
    leading ``제N조(<제목>)`` header — the first title segment with a trailing 조사
    stripped (e.g. '기업업무추진비의 손금불산입' → '기업업무추진비', '접대비의 …' →
    '접대비'). This is the token that distinguishes one 시행일 버전/세목 from another;
    a claim that does not even name it is not anchored to THIS provision."""
    m = _TITLE_RE.match(_normalize(provision_text))
    if not m:
        return ""
    first = _normalize(m.group(1)).split(" ")[0]
    return first[:-1] if first.endswith("의") and len(first) > 2 else first


def verify_entailment(claim_text: str, quote: str, provision_text: str) -> EntailmentCheck:
    """DETERMINISTIC entailment of one citation: does the cited provision excerpt
    actually support the claim's statutory anchors (codex P1-1)? No LLM, no
    self-report — pure rule matching, so an unsupported citation is caught even if
    a (mis)generous judge calls it supported.

    A citation is deterministically SUPPORTED iff ALL hold (whitespace-normalized):
      C1  grounding   — the cited ``quote`` (minus its truncation marker) is a
                        verbatim substring of the provision text;
      C2  조문 참조    — every ``제N조`` the claim references appears in the provision
                        (a claim citing 제999조 against 제25조 본문 is unsupported);
      C3  제목 핵심어  — the provision's subject term is named by the claim (a claim
                        about '접대비' cited against the '기업업무추진비' 버전 fails).
    """
    claim_n = _normalize(claim_text)
    prov_n = _normalize(provision_text)
    quote_n = _TRUNC_RE.sub("", _normalize(quote)).strip()

    reasons: list[str] = []

    # C1 — the excerpt must genuinely come from the provision.
    if not quote_n or quote_n not in prov_n:
        reasons.append("인용 발췌가 조문 본문의 verbatim 부분문자열이 아님")

    # C2 — every article the claim asserts must exist in the provision.
    claim_articles = set(_ARTICLE_RE.findall(claim_n))
    prov_articles = set(_ARTICLE_RE.findall(prov_n))
    missing_articles = sorted(claim_articles - prov_articles)
    if missing_articles:
        reasons.append(f"claim의 조문 참조 {missing_articles}가 본문에 없음")

    # C3 — the provision's subject term must be named by the claim.
    subject = _provision_subject(prov_n)
    if subject and subject not in claim_n:
        reasons.append(f"조문 제목 핵심어 '{subject}'를 claim이 진술하지 않음(버전/세목 불일치)")

    supported = not reasons
    rationale = (
        "조문이 claim의 조문참조·제목 핵심어를 verbatim 발췌와 함께 지지함"
        if supported
        else "; ".join(reasons)
    )
    return EntailmentCheck(
        claim=claim_text[:160].strip(),
        supported=supported,
        rationale=rationale,
        deterministic=supported,
    )


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
    # robust to multiple JSON blocks (draft + final): take the LAST balanced
    # top-level object that parses (codex: reasoning models emit extra blocks).
    objs = _top_level_objects(text)
    if not objs:
        raise JudgeError("no JSON object in judge output")
    last_err: Optional[Exception] = None
    for obj in reversed(objs):
        try:
            return json.loads(obj)
        except json.JSONDecodeError as exc:
            last_err = exc
    raise JudgeError(f"invalid JSON in judge output: {last_err}")


def build_judge_prompt(
    *, question_text: str, answer: ResearchLiteAnswer, provision_quote: str,
    gold_issues: list[str],
) -> tuple[str, str]:
    """(system, user). Centralized so record/replay keys match."""
    system = _JUDGE_PROMPT_PATH.read_text(encoding="utf-8")
    body = provision_quote.strip()
    if len(body) > _PROVISION_MAX:
        body = body[:_PROVISION_MAX] + "…"
    pv = answer.provision_version
    prom = pv.promulgated_date.strftime("%Y-%m-%d") if pv.promulgated_date else "N/A"
    meta = (
        f"[검증된 메타데이터 — 앵커(버전 객체)] 시행일 {pv.effective_from:%Y-%m-%d}, "
        f"공포일 {prom}. 이 날짜는 ProvisionVersion/SourceSnapshot 으로 검증된 사실이다. "
        f"답변이 이 시행일·공포일을 진술해도 '본문 밖 단정'으로 감점하지 마라."
    )
    cite_lines = []
    for i, (claim, cit) in enumerate(
        [(answer.bundle.claim, answer.bundle.citation),
         (answer.conclusion_claim, answer.conclusion_citation)], start=1
    ):
        cite_lines.append(
            f"{i}) claim: {claim.proposition}\n   인용 발췌: {cit.quote}"
        )
    gold_block = "\n".join(f"- {g}" for g in gold_issues) if gold_issues else "(없음 — 본문에서 도출)"
    user = (
        f"[질문]\n{question_text}\n\n"
        f"{meta}\n\n"
        f"[채점 대상 답변]\n{answer.answer_text}\n\n"
        f"[인용 (claim ↔ 조문 발췌) — entailment 판정 대상]\n"
        + "\n".join(cite_lines)
        + f"\n\n[조문 본문 — entailment 판정 근거]\n{body}\n\n"
        f"[gold 기대쟁점 — issue_spotting 채점 기준]\n{gold_block}\n\n"
        f"위 엄격 루브릭으로 4개 차원과 entailment를 채점하고, 지정 JSON으로만 답하라."
    )
    return system, user


class Judge:
    """Strict LLM-judge over a replay/record LLM transport."""

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self.client = llm_client or default_llm_client()

    def score(
        self, *, question_text: str, answer: ResearchLiteAnswer, provision_quote: str,
        gold_issues: list[str], tag: str,
    ) -> JudgeVerdict:
        system, user = build_judge_prompt(
            question_text=question_text, answer=answer,
            provision_quote=provision_quote, gold_issues=gold_issues,
        )
        resp = self.client.complete(system=system, user=user, tag=tag,
                                    max_tokens=_JUDGE_MAX_TOKENS)
        data = _extract_json(resp.text)

        raw_scores = data.get("scores", {})
        if not isinstance(raw_scores, dict):
            raise JudgeError("judge 'scores' must be an object")
        fractions: dict[str, float] = {}
        for dim in _JUDGE_DIMS:
            if dim not in raw_scores:
                raise JudgeError(f"judge omitted dimension '{dim}'")
            fractions[dim] = _exact_bucket_fraction(raw_scores[dim])

        # -- DETERMINISTIC entailment over the REAL citations (codex P1-1) ----- #
        # Primary signal: rule-matched grounding of each cited excerpt to its
        # claim's statutory anchors. The judge's self-report is AUXILIARY only.
        det_checks = [
            verify_entailment(claim.proposition, cit.quote, provision_quote)
            for claim, cit in zip(answer.claims, answer.citations)
        ]
        if not det_checks:
            raise JudgeError("answer carries no citations to verify entailment for")

        # judge self-report (auxiliary corroboration — never an upgrade)
        judge_flags = [
            bool(e.get("supported", False))
            for e in (data.get("entailment", []) or [])
            if isinstance(e, dict)
        ]
        if not judge_flags:
            # fail-closed: a judge that returns no entailment verdict has not
            # engaged with grounding — treat as unproven (not silently supported).
            raise JudgeError("judge returned no entailment verdicts")
        judge_corroborates = all(judge_flags)

        entailments = [
            EntailmentCheck(
                claim=det.claim,
                supported=bool(det.deterministic and judge_corroborates),
                rationale=(
                    det.rationale
                    if det.deterministic
                    else f"[deterministic 미지지] {det.rationale}"
                ),
                deterministic=det.deterministic,
                judge_supported=judge_corroborates,
            )
            for det in det_checks
        ]

        return JudgeVerdict(
            fractions=fractions,
            entailments=entailments,
            missed_issues=[str(x).strip() for x in data.get("missed_issues", []) or []],
            unsupported_claims=[str(x).strip() for x in data.get("unsupported_claims", []) or []],
            rationale=str(data.get("rationale", "")).strip(),
            llm=resp,
        )


def default_judge(llm_client: Optional[LLMClient] = None) -> Judge:
    return Judge(llm_client=llm_client)


# --------------------------------------------------------------------------- #
# Synthesis judge (slice ④) — scores the SynthesisOpinion (channel ④)
# --------------------------------------------------------------------------- #
@dataclass
class EntailTarget:
    """One inherited claim↔citation pair to verify entailment for (deterministic)."""

    claim_text: str
    quote: str
    provision_text: str


def build_synthesis_judge_prompt(
    *, question_text: str, opinion_text: str, source_positions: str,
    resolution_summary: str, entail_targets: list[EntailTarget],
    provision_body: str, gold_issues: list[str],
) -> tuple[str, str]:
    """(system, user). Centralized so record/replay keys match (deterministic)."""
    system = _SYNTH_JUDGE_PROMPT_PATH.read_text(encoding="utf-8")
    body = (provision_body or "").strip()
    if len(body) > _PROVISION_MAX:
        body = body[:_PROVISION_MAX] + "…"
    cite_lines = [
        f"{i}) claim: {t.claim_text}\n   상속 인용 발췌: {t.quote}"
        for i, t in enumerate(entail_targets, start=1)
    ] or ["(표시된 종합 결론 인용 없음 — 보류 종합)"]
    gold_block = "\n".join(f"- {g}" for g in gold_issues) if gold_issues else "(없음 — 본문에서 도출)"
    user = (
        f"[질문]\n{question_text}\n\n"
        f"[3소스 독립 입장]\n{source_positions}\n\n"
        f"[충돌 해소(결정테이블 결과 — 결정적)]\n{resolution_summary}\n\n"
        f"[채점 대상 종합의견]\n{opinion_text}\n\n"
        f"[상속 인용 (claim ↔ 조문 발췌) — entailment 판정 대상]\n"
        + "\n".join(cite_lines)
        + f"\n\n[권위(채택) 조문 본문 — entailment 판정 근거]\n{body}\n\n"
        f"[gold 기대쟁점 — issue_spotting 채점 기준]\n{gold_block}\n\n"
        f"위 엄격 루브릭으로 4개 차원과 entailment를 채점하고, 지정 JSON으로만 답하라."
    )
    return system, user


class SynthesisJudge:
    """Strict LLM-judge over the SynthesisOpinion (channel ④). Reuses the bucket /
    JSON / deterministic-entailment machinery of ``Judge`` (codex P1-1)."""

    def __init__(self, llm_client: Optional[LLMClient] = None) -> None:
        self.client = llm_client or default_llm_client()

    def score(
        self, *, question_text: str, opinion_text: str, source_positions: str,
        resolution_summary: str, entail_targets: list[EntailTarget],
        provision_body: str, gold_issues: list[str], tag: str,
    ) -> JudgeVerdict:
        system, user = build_synthesis_judge_prompt(
            question_text=question_text, opinion_text=opinion_text,
            source_positions=source_positions, resolution_summary=resolution_summary,
            entail_targets=entail_targets, provision_body=provision_body,
            gold_issues=gold_issues,
        )
        resp = self.client.complete(system=system, user=user, tag=tag,
                                    max_tokens=_JUDGE_MAX_TOKENS)
        data = _extract_json(resp.text)

        raw_scores = data.get("scores", {})
        if not isinstance(raw_scores, dict):
            raise JudgeError("judge 'scores' must be an object")
        fractions: dict[str, float] = {}
        for dim in _JUDGE_DIMS:
            if dim not in raw_scores:
                raise JudgeError(f"judge omitted dimension '{dim}'")
            fractions[dim] = _exact_bucket_fraction(raw_scores[dim])

        # DETERMINISTIC entailment over the inherited claim↔citation pairs (codex
        # P1-1). The judge self-report is AUXILIARY (never an upgrade).
        det_checks = [
            verify_entailment(t.claim_text, t.quote, t.provision_text)
            for t in entail_targets
        ]
        if not det_checks:
            raise JudgeError("synthesis carries no inherited citations to verify entailment for")

        judge_flags = [
            bool(e.get("supported", False))
            for e in (data.get("entailment", []) or [])
            if isinstance(e, dict)
        ]
        if not judge_flags:
            raise JudgeError("judge returned no entailment verdicts")
        judge_corroborates = all(judge_flags)

        entailments = [
            EntailmentCheck(
                claim=det.claim,
                supported=bool(det.deterministic and judge_corroborates),
                rationale=(det.rationale if det.deterministic
                           else f"[deterministic 미지지] {det.rationale}"),
                deterministic=det.deterministic,
                judge_supported=judge_corroborates,
            )
            for det in det_checks
        ]
        return JudgeVerdict(
            fractions=fractions,
            entailments=entailments,
            missed_issues=[str(x).strip() for x in data.get("missed_issues", []) or []],
            unsupported_claims=[str(x).strip() for x in data.get("unsupported_claims", []) or []],
            rationale=str(data.get("rationale", "")).strip(),
            llm=resp,
        )


def default_synthesis_judge(llm_client: Optional[LLMClient] = None) -> SynthesisJudge:
    return SynthesisJudge(llm_client=llm_client)
