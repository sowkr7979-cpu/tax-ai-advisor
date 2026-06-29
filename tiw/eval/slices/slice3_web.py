"""tiw/eval/slices/slice3_web.py — slice ③ harness (공식소스 Web run).

Drives the channel-③ web-research pipeline (``src.web_research``) against the gold
web cases and scores the dimensions it exercises:

  DETERMINISTIC:
    - search (9)      : official-domain recall — did discovery surface the gold
                        공식 출처(law.go.kr 등)?  (WEB-003)
    - citation (12)   : grounding(존재·버전·pinpoint·시점 + web 소스객체 provenance)
                        + (judge) entailment + 결정적 web-provenance 대조 (HALU-003)
    - requirement (6) : SourceSnapshot(발행기관·retrieved_at·content_hash) + 답변 +
                        applicable_basis (WEB-005)
    - ops (2)         : 재현성 (snapshot/provision 해시 replay)

  JUDGE (reused from slice ①):
    - legal_reasoning (20) · issue_spotting (10) · risk (11) · output (9) + entailment

  N/A (denominator 79): conflict (7) → slice ④ ; security (14) → 웹은 공유 L0(slice ⑥).

WEB-specific verification surfaced as metrics + gates:
    - source_policy   : 비공식(블로그·미러) 결과 결론 근거 0건 (WEB-002/004/007)
    - promotion       : 공식 원문만 권위 소스로 승격, 법령 원문 대조 (WEB-011)
    - WEB-012         : 최신성(freshness) ⟂ 적용시점 유효성(applicable_validity) 분리 저장
    - web-alone 차단  : 승격 없으면 abstain — 웹 단독 세무 단정 금지 (docs/06 §9)

HARD GATES (docs/09 §2):
  - NOT_REPRODUCIBLE (75) : tavily/gen/judge fixture 부재·해시 불일치·승격 실패 → fail-closed
  - TEMPORAL_ERROR  (55)  : grounding/승격 버전의 시행일이 gold 와 불일치
  - FABRICATED_CITATION(60): 인용 미등록 OR entailment 미지지 OR 비공식 소스 승격 OR
                            web-provenance 대조 실패 (날조 권위)
  - MISSING_REVIEW_WARNING(60): high-risk 질의에 회계사 검토경고 누락

``pipeline_factory`` / ``citation_tamper`` / ``llm_client`` / ``judge`` /
``inject_candidates`` are injectable ONLY so adversarial tests can feed a
blog-injected candidate set, a tampered citation, an empty-fixture client, a fake
judge, or a missing cross-check through this SAME scoring path and prove the
harness CATCHES it (anti-gaming evidence).
"""

from __future__ import annotations

from hashlib import sha256
from statistics import mean
from typing import Callable, Optional

from contract.base import SourceKind
from contract.cluster_d_provenance import ProvisionVersion, SourceSnapshot
from contract.cluster_f_qa import Citation
from contract.cluster_i_eval import EvaluationCase, RubricResult, TargetKind, WebQuery
from rules.hard_gates import DIMENSION_WEIGHTS
from src.ai.law_data_source import LawSourceError
from src.ai.llm_client import (
    LLMClient,
    LLMError,
    LLMNotReproducible,
    LLMUnavailable,
    default_llm_client,
)
from src.ai.tavily_client import WebSearchError, official_domain_of
from src.judge import Judge, JudgeError, JudgeVerdict, default_judge
from src.legal_research import ResearchGenerationError
from src.source_registry import SourceRegistry
from src.web_research import WebResearchPipeline, WebSourceAnswer
from tiw.eval.scorer import build_rubric_result

SLICE_NO = 3
PENDING_DIMS = ["legal_reasoning", "issue_spotting", "risk", "output"]

PipelineFactory = Callable[[], WebResearchPipeline]
CitationTamper = Callable[[Citation], Citation]


def _safe_mean(values: list[float], default: float = 1.0) -> float:
    return mean(values) if values else default


def run_case(
    case: EvaluationCase,
    pipeline_factory: Optional[PipelineFactory] = None,
    citation_tamper: Optional[CitationTamper] = None,
    llm_client: Optional[LLMClient] = None,
    judge: Optional[Judge] = None,
    inject_candidates: Optional[list] = None,
) -> RubricResult:
    client = llm_client or default_llm_client()
    jdg = judge or default_judge(client)
    pipeline = (pipeline_factory or WebResearchPipeline)()

    queries: list[WebQuery] = list(case.web_queries)
    n = len(queries)

    recall_hits = recall_total = 0
    cit_passed = cit_total = 0
    basis_present = answer_produced = snapshot_ok = 0
    promoted_ok = 0
    abstain_ok = 0                     # expect_promote=False queries that correctly abstained
    unofficial_promoted = False        # WEB-004: a non-official source became authority
    web_alone = False                  # docs/06 §9: conclusion without promotion
    reproducible = True
    completed = True
    temporal_error = False
    fabricated = False
    missing_warning = False

    # judge accumulators
    judge_ran = 0
    judge_fracs: dict[str, list[float]] = {d: [] for d in PENDING_DIMS}
    entail_pass = entail_total = 0
    web_prov_pass = web_prov_total = 0
    llm_in = llm_out = 0
    llm_cost = 0.0
    judge_model = "n/a"

    # WEB-012: keep the two scores SEPARATE in metrics (최신성 ⟂ 적용시점)
    freshness_scores: list[float] = []
    applicable_scores: list[float] = []

    for q in queries:
        reg = SourceRegistry()
        try:
            web: WebSourceAnswer = pipeline.run(
                question_text=q.question_text, law_name=q.law_name,
                article_label=q.article_label, as_of_date=q.as_of_date, issue=q.issue,
                tax_type=q.tax_type, high_risk=q.high_risk, basis_kind=q.basis_kind,
                source_answer_id=f"sa_{case.case_id}_{q.query_id}",
                answer_run_id=f"ar_{case.case_id}_{q.query_id}",
                llm_client=client, registry=reg, extra_candidates=inject_candidates,
            )
        except (WebSearchError, LawSourceError, ResearchGenerationError, LLMError):
            # fail-closed: missing/tampered tavily/gen fixture, law cross-check, or
            # missing LLM fixture → case unmeasurable (→ NOT_REPRODUCIBLE).
            completed = False
            continue

        # -- search recall: gold official domains surfaced among official candidates #
        official_domains = {
            official_domain_of(c.result.url)
            for c in web.scored_candidates
            if c.officiality > 0 and official_domain_of(c.result.url)
        }
        for dom in q.gold_official_domains:
            recall_total += 1
            recall_hits += int(dom in official_domains)

        # -- WEB-002/004/007: no NON-official source may be promoted as authority --- #
        if web.promoted is not None and official_domain_of(web.promoted.snapshot.url) is None:
            unofficial_promoted = True

        # -- WEB-012: store the two scores separately (per promoted/best candidate) - #
        ref = web.promoted.candidate if web.promoted is not None else (
            web.scored_candidates[0] if web.scored_candidates else None
        )
        if ref is not None:
            freshness_scores.append(ref.freshness)
            applicable_scores.append(ref.applicable_validity)

        # -- promotion / web-alone (docs/06 §9) ----------------------------------- #
        if q.expect_promote:
            if web.abstained or web.promoted is None or web.research is None:
                # expected a promotable official source but got none → fail-closed
                reproducible = False
                continue
            promoted_ok += 1
        else:
            # adversarial / web-단독 시나리오: MUST abstain (no web-alone 단정, docs/06 §9).
            # A correct abstain is the PASS path here; a non-abstaining conclusion is
            # the web-alone 단정 violation (codex P1: score a correct abstain honestly).
            if web.abstained and web.promoted is None:
                abstain_ok += 1
            else:
                web_alone = True
            continue

        # promotion succeeded → score the answer
        research = web.research
        pv = web.promoted.provision_version
        if sha256(pv.text.encode("utf-8")).hexdigest() != pv.hash:
            reproducible = False

        # provenance (requirement, WEB-005): full SourceSnapshot
        snap = web.promoted.snapshot
        snapshot_ok += int(bool(snap.official and snap.content_hash and snap.publisher
                                and snap.url and snap.retrieved_at))
        basis_present += int(research.bundle.applicable_basis is not None
                             and web.web_citation is not None
                             and web.web_citation.applicable_basis is not None)
        answer_produced += int(bool(web.answer_text))
        if q.high_risk and not web.review_warnings:
            missing_warning = True

        # -- temporal correctness of the promoted/grounded version (PROV-012) ----- #
        g = q.gold_law
        title = web.promoted.lookup.article_title or ""
        text = pv.text or ""
        if (
            web.promoted.lookup.article_label != g.article_label
            or pv.effective_from != g.expected_effective_from
            or g.title_contains not in (title + text)
        ):
            temporal_error = True

        # -- citation grounding (deterministic) ----------------------------------- #
        reg.register_all(web.source_objects)
        # research pv citations (anchor + conclusion): existence·version·pinpoint·시점
        for citation in (research.bundle.citation, research.conclusion_citation):
            citation = citation_tamper(citation) if citation_tamper else citation
            verification = reg.verify_citation(citation)
            if verification.is_fabrication:
                fabricated = True
            registered = reg.get(citation.source_kind, citation.source_object_id)
            existence = verification.ok
            version_ok = (
                citation.source_kind is SourceKind.PROVISION_VERSION
                and isinstance(registered, ProvisionVersion)
            )
            pinpoint_ok = bool(citation.source_locator) and g.article_label in (
                citation.source_locator or ""
            )
            temporal_ok = pv.effective_from <= q.as_of_date and (
                pv.effective_to is None or q.as_of_date < pv.effective_to
            )
            cit_total += 4
            cit_passed += int(existence) + int(version_ok) + int(pinpoint_ok) + int(temporal_ok)

        # web provenance citation (SOURCE_SNAPSHOT): existence·kind·official·대조 -- #
        web_cit = citation_tamper(web.web_citation) if citation_tamper else web.web_citation
        web_ver = reg.verify_citation(web_cit)
        if web_ver.is_fabrication:
            fabricated = True
        registered = reg.get(web_cit.source_kind, web_cit.source_object_id)
        official_ok = isinstance(registered, SourceSnapshot) and registered.official
        cit_total += 4
        cit_passed += (
            int(web_ver.ok)
            + int(web_cit.source_kind is SourceKind.SOURCE_SNAPSHOT)
            + int(official_ok)
            + int(bool(web_cit.applicable_basis is not None))
        )

        # web-provenance 대조 (deterministic, judge-independent, codex P0-2): the
        # cited excerpt must be a verbatim substring of BOTH (a) the OFFICIAL web
        # snapshot content — proving the web source actually carries it — AND (b) the
        # authoritative ① provision text — proving 법령 원문 대조. Verified against the
        # (possibly tampered) citation actually emitted; a 회수 밖 날조 quote fails both.
        web_prov_total += 1
        import re as _re

        def _norm(s: str) -> str:
            return _re.sub(r"\s+", " ", s or "")

        wq = _norm((web_cit.quote or "").rstrip("…").strip())
        official_content = _norm(web.promoted.official_content)
        prov_ok = (
            bool(wq)
            and wq in official_content        # web 출처가 실제로 그 문구를 담음
            and wq in _norm(pv.text)          # 법령 원문(①)과 일치 — 대조
            and official_ok
        )
        web_prov_pass += int(prov_ok)
        if not prov_ok:
            fabricated = True

        # -- JUDGE (reuse slice ①) ------------------------------------------------ #
        try:
            verdict: JudgeVerdict = jdg.score(
                question_text=q.question_text, answer=research,
                provision_quote=pv.text, gold_issues=list(q.gold_issues),
                tag=f"judge_{case.case_id}_{q.query_id}",
            )
            for d in PENDING_DIMS:
                judge_fracs[d].append(verdict.fractions[d])
            entail_pass += sum(1 for e in verdict.entailments if e.supported)
            entail_total += len(verdict.entailments)
            judge_ran += 1
            if research.llm:
                llm_in += research.llm.input_tokens
                llm_out += research.llm.output_tokens
                llm_cost += research.llm.cost_usd
            if verdict.llm:
                llm_in += verdict.llm.input_tokens
                llm_out += verdict.llm.output_tokens
                llm_cost += verdict.llm.cost_usd
                judge_model = verdict.llm.model
        except (LLMUnavailable, LLMNotReproducible):
            # missing/tampered judge fixture = reproducibility failure (fail-closed)
            reproducible = False
        except (LLMError, ResearchGenerationError, JudgeError):
            pass    # judge ran but invalid → dims stay PENDING (never full marks)

    # FAIL-CLOSED: every gold query must reach its EXPECTED outcome — a promote-and-
    # ground (expect_promote=True) OR a correct abstain (expect_promote=False) — and
    # replay its hash. (codex P1: a correctly-abstaining adversarial case is the PASS
    # path, not NOT_REPRODUCIBLE.)
    expect_promotions = sum(1 for q in queries if q.expect_promote)
    expect_abstains = n - expect_promotions
    measured = (
        n > 0 and completed and reproducible
        and promoted_ok == expect_promotions and abstain_ok == expect_abstains
    )
    # judge is scored only when every PROMOTED query was judged (abstain cases carry
    # no legal answer to judge — a slice with any abstain case stays judge-incomplete).
    judge_scored = (
        expect_promotions > 0 and judge_ran == expect_promotions and measured
        and expect_abstains == 0
    )

    entailment_unsupported = False
    if judge_scored:
        cit_passed += entail_pass
        cit_total += entail_total
        if entail_pass < entail_total:
            entailment_unsupported = True

    web_prov_unsupported = web_prov_total > 0 and web_prov_pass < web_prov_total

    # -- dimension fractions -------------------------------------------------- #
    search_frac = (recall_hits / recall_total) if recall_total else 0.0
    citation_frac = (cit_passed / cit_total) if cit_total else 0.0
    requirement_frac = _safe_mean([
        (basis_present / n) if n else 0.0,
        (answer_produced / n) if n else 0.0,
        (snapshot_ok / n) if n else 0.0,
    ])
    ops_frac = 1.0 if measured else 0.0

    if not measured:
        search_frac = citation_frac = requirement_frac = 0.0

    dim_fractions = {
        "requirement": requirement_frac,
        "search": search_frac,
        "citation": citation_frac,
        "ops": ops_frac,
    }
    pending = list(PENDING_DIMS)
    judge_buckets: dict[str, int] = {}
    if judge_scored:
        for d in PENDING_DIMS:
            dim_fractions[d] = _safe_mean(judge_fracs[d], default=0.0)
            judge_buckets[d] = round(dim_fractions[d] * 100)
        pending = []

    # -- hard gates ----------------------------------------------------------- #
    hard_gate_codes: list[str] = []
    if not measured:
        hard_gate_codes.append("NOT_REPRODUCIBLE")        # cap 75
    if temporal_error:
        hard_gate_codes.append("TEMPORAL_ERROR")          # cap 55
    if (fabricated or entailment_unsupported or web_prov_unsupported
            or unofficial_promoted or web_alone):
        hard_gate_codes.append("FABRICATED_CITATION")     # cap 60 (날조 권위/web단독)
    if missing_warning:
        hard_gate_codes.append("MISSING_REVIEW_WARNING")  # cap 60

    entailment_metric = f"{entail_pass}/{entail_total}" if judge_scored else "PENDING_JUDGE"
    na_dims = ["conflict", "security"]
    applicable_denominator = 100 - sum(DIMENSION_WEIGHTS[d] for d in na_dims)
    scope_note = (
        f"점수는 적용 차원 재정규화(분모 {applicable_denominator}점)입니다 — "
        f"conflict({DIMENSION_WEIGHTS['conflict']})·security({DIMENSION_WEIGHTS['security']})는 "
        f"이 slice에서 N/A(분모 제외; 충돌은 slice④·웹은 공유 L0 보안은 slice⑥)."
    )

    metrics = {
        "recall": round(search_frac, 3),
        "official_recall": f"{recall_hits}/{recall_total}",
        "promoted": f"{promoted_ok}/{expect_promotions}",
        "source_policy_unofficial_promoted": unofficial_promoted,
        "web_alone_conclusion": web_alone,
        "citation_grounding": f"{cit_passed}/{cit_total}",
        "entailment": entailment_metric,
        "web_provenance": f"{web_prov_pass}/{web_prov_total}",
        # WEB-012: 두 점수 독립 기록 (최신성 ⟂ 적용시점)
        "freshness_scores": [round(s, 3) for s in freshness_scores],
        "applicable_validity_scores": [round(s, 3) for s in applicable_scores],
        "web012_scores_separated": True,
        "temporal_error": temporal_error,
        "fabricated_citation": (fabricated or entailment_unsupported or web_prov_unsupported
                                or unofficial_promoted or web_alone),
        "missing_review_warning": missing_warning,
        "reproducible": reproducible,
        "snapshot_provenance": f"{snapshot_ok}/{n}",
        "measured": measured,
        "judge_scored": judge_scored,
        "judge_ran": f"{judge_ran}/{n}",
        "judge_scores": judge_buckets,
        "judge_model": judge_model,
        "llm_tokens": f"{llm_in}in/{llm_out}out",
        "llm_cost_usd": round(llm_cost, 6),
        "pending_judge_dims": pending or "none(scored)",
        "na_dimensions": na_dims,
        "applicable_denominator": applicable_denominator,
        "scope_note": scope_note,
    }

    return build_rubric_result(
        case_id=case.case_id,
        slice_no=SLICE_NO,
        target_id=case.case_id,
        visibility=case.visibility,
        target_kind=TargetKind.SLICE,
        dim_fractions=dim_fractions,
        dim_details={
            "requirement": f"basis={basis_present}/{n} answer={answer_produced}/{n} "
            f"snapshot={snapshot_ok}/{n}",
            "search": f"official_recall={search_frac:.2f} ({recall_hits}/{recall_total})",
            "citation": f"grounding+entailment={cit_passed}/{cit_total} "
            f"(judge_entailment={entailment_metric} web_provenance={web_prov_pass}/{web_prov_total})",
            "ops": f"measured={measured} reproducible={reproducible} promoted={promoted_ok}/{expect_promotions}",
            "legal_reasoning": f"judge bucket={judge_buckets.get('legal_reasoning')}"
            if judge_scored else "PENDING_JUDGE — judge/CPA 미연결 (보류)",
            "issue_spotting": f"judge bucket={judge_buckets.get('issue_spotting')}"
            if judge_scored else "PENDING_JUDGE — judge/CPA 미연결 (보류)",
            "risk": f"judge bucket={judge_buckets.get('risk')}"
            if judge_scored else "PENDING_JUDGE — judge/CPA 미연결 (보류)",
            "output": f"judge bucket={judge_buckets.get('output')}"
            if judge_scored else "PENDING_JUDGE — judge/CPA 미연결 (보류)",
        },
        hard_gate_codes=hard_gate_codes,
        metrics=metrics,
        pending_dimensions=pending,
    )


def run_cases(
    cases: list[EvaluationCase],
    pipeline_factory: Optional[PipelineFactory] = None,
    citation_tamper: Optional[CitationTamper] = None,
    llm_client: Optional[LLMClient] = None,
    judge: Optional[Judge] = None,
    inject_candidates: Optional[list] = None,
) -> list[RubricResult]:
    return [
        run_case(c, pipeline_factory=pipeline_factory, citation_tamper=citation_tamper,
                 llm_client=llm_client, judge=judge, inject_candidates=inject_candidates)
        for c in cases
    ]
