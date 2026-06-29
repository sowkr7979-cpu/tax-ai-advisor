"""slice ④ 충돌 케이스(3소스 종합) — 결정적 테스트 (실키/네트워크 불필요, fixture 재생).

핵심:
  - 결정테이블(rules.conflict_resolution): 권위 위계·시점 유효성·사실관계·채널 tie-break.
  - SynthesisEngine: claim 단위 ClaimAlignment + ConflictResolution + SynthesisOpinion,
    인용 상속(ORCH-012 신규 인용 0) + lineage 무결성(HALU-014).
  - EVAL-011 앙상블 4종(침묵·2v1·3way·법령부재) + EVAL-012(충돌 F1·정확보류·lineage 100%).
  - 하버스 정직성(anti-gaming): 충돌 평균/뭉갬 → conflict 0 + FABRICATED, 미해소 단정 → 차단,
    권위 위계 위반(구버전/하위 채택) → TEMPORAL/FABRICATED, lineage 추적불가 → NOT_REPRODUCIBLE,
    신규 인용 → FABRICATED, 소스 인용 날조 → FABRICATED, fixture 부재 → NOT_REPRODUCIBLE
    를 *동일 채점 경로*에서 적발.
"""

from __future__ import annotations

from datetime import date

import pytest

from contract.base import (
    AlignmentStatus,
    ConflictOutcome,
    SourceAnswerStatus,
    SourceType,
)
from contract.cluster_f_qa import Citation
from contract.cluster_i_eval import EvaluationCase, SynthesisScenario
from rules.conflict_resolution import SourcePosition, resolve_topic
from src.synthesis import SynthesisEngine, SynthesisResult
from tiw.eval.loader import load_hidden_cases, load_public_cases
from tiw.eval.runner import run_slice
from tiw.eval.slices.slice4_synthesis import run_case


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _case(case_id: str) -> EvaluationCase:
    for c in load_public_cases(4) + load_hidden_cases(4):
        if c.case_id == case_id:
            return c
    raise AssertionError(f"{case_id} not found")


def _pos(channel, authority, stance, *, status=SourceAnswerStatus.ANSWERED,
         ef=date(2024, 1, 1), et=None, dispositive=True, fact=True, version_based=False):
    st = SourceType.LAW_MCP if channel == "①" else (
        SourceType.INTERNAL_RAG if channel == "②" else SourceType.WEB)
    return SourcePosition(
        source_type=st, channel_label=channel, authority_label=authority, status=status,
        stance=stance, effective_from=ef, effective_to=et, dispositive=dispositive,
        fact_match=fact, version_based=version_based, source_answer_id=f"sa_{channel}",
        citation_id=f"cit_{channel}", claim_id=f"cl_{channel}",
    )


# --------------------------------------------------------------------------- #
# 결정테이블 (rules.conflict_resolution) — deterministic, no LLM
# --------------------------------------------------------------------------- #
def test_decision_table_law_overrides_web_authority():
    # 법률 vs 웹 불일치 → 법률 채택, 웹 강등 (권위 위계, 평균 금지).
    res = resolve_topic([_pos("①", "법률", "A"), _pos("③", "웹", "B")], date(2024, 1, 1))
    assert res.outcome is ConflictOutcome.AUTHORITY
    assert [p.channel_label for p in res.adopted] == ["①"]
    assert [p.channel_label for p in res.demoted] == ["③"]


def test_decision_table_temporal_picks_valid_version():
    # 같은 조문 다른 시행일 버전 → 적용시점 유효 버전 채택, 구버전 배제.
    cur = _pos("①", "법률", "기업업무추진비", ef=date(2024, 1, 1), version_based=True)
    old = _pos("②", "법률", "접대비", ef=date(2020, 1, 1), et=date(2024, 1, 1), version_based=True)
    res = resolve_topic([cur, old], date(2024, 1, 1))
    assert res.outcome is ConflictOutcome.TEMPORAL
    assert [p.channel_label for p in res.adopted] == ["①"]
    assert [p.channel_label for p in res.excluded] == ["②"]


def test_decision_table_unresolved_same_authority_contradiction():
    # 동급 권위(예규 vs 심판례) 모순 + 법률 비-dispositive → 단정 금지(보류).
    law = _pos("①", "법률", "불명확", dispositive=False)
    yegyu = _pos("②", "예규", "포함")
    simpan = _pos("③", "심판례", "불포함")
    res = resolve_topic([law, yegyu, simpan], date(2024, 1, 1))
    assert res.outcome is ConflictOutcome.UNRESOLVED_ABSTAIN
    assert res.abstained


def test_decision_table_fact_mismatch_excludes_ruling():
    # 사실관계 불일치 예규 원용 불가 → 배제 후 법률 채택(FACT_MISMATCH).
    law = _pos("①", "법률", "A")
    yegyu = _pos("②", "예규", "B", fact=False)
    res = resolve_topic([law, yegyu], date(2024, 1, 1))
    assert res.outcome is ConflictOutcome.FACT_MISMATCH
    assert [p.channel_label for p in res.adopted] == ["①"]
    assert [p.channel_label for p in res.excluded] == ["②"]


def test_decision_table_law_absent_non_authoritative_consensus():
    # ① 법령 부재(침묵), ②③ 합의 → 비권위적 합의(가이드·캡·HITL).
    silent = _pos("①", "법률", "", status=SourceAnswerStatus.SILENT)
    book = _pos("②", "실무서", "X")
    web = _pos("③", "웹", "X")
    res = resolve_topic([silent, book, web], date(2024, 1, 1))
    assert res.outcome is ConflictOutcome.NON_AUTHORITATIVE_CONSENSUS
    assert res.authority_deficit and res.abstained
    assert [p.channel_label for p in res.adopted] == ["②"]   # 채널 tie-break ②>③


def test_decision_table_agree_inherits_highest_channel():
    res = resolve_topic([_pos("①", "법률", "X"), _pos("③", "법률", "X")], date(2024, 1, 1))
    assert res.outcome is ConflictOutcome.AGREE
    assert [p.channel_label for p in res.adopted] == ["①"]    # ①>③ tie-break


# --------------------------------------------------------------------------- #
# 하버스 end-to-end (slice ④) — 4 앙상블 + ≥90
# --------------------------------------------------------------------------- #
def test_slice4_harness_passes_gate():
    report = run_slice(4)
    assert report.case_results
    assert report.public_count == 2 and report.hidden_count == 2
    assert not report.hard_gate_hit
    assert report.pending is False
    assert report.passed is True
    assert report.score >= 90
    for r in report.case_results:
        # F1 is [1.0] when a positive(CONFLICT) topic exists; ["N/A"] when there is
        # none (SILENT/LAW_ABSENT 합의) — no trivial 1.0 inflating the score (P2-2).
        assert r.metrics["conflict_f1"] in ([1.0], ["N/A"])
        assert r.metrics["conflict_dimension"] == 1.0
        assert r.metrics["lineage_integrity"] == "100%"
        assert r.metrics["measured"] is True
        assert r.metrics["judge_scored"] is True
        assert r.metrics["entailment"] == "2/2"
        assert r.metrics["new_citations_minted"] is False
        assert r.metrics["temporal_error"] is False
        scored = {s.dimension for s in r.dimension_scores if s.applicable and s.score is not None}
        assert {"legal_reasoning", "issue_spotting", "risk", "output",
                "conflict", "citation", "requirement", "ops"} <= scored
        # conflict(7) is the dimension that was N/A in ①②③ — now measured at 100.
        conflict_dim = next(s for s in r.dimension_scores if s.dimension == "conflict")
        assert conflict_dim.applicable and conflict_dim.score == 100.0


def test_slice4_all_four_ensemble_kinds_present():
    kinds = []
    for c in load_public_cases(4) + load_hidden_cases(4):
        for sc in c.synthesis_scenarios:
            kinds.append(sc.ensemble_kind.value)
    assert set(kinds) == {"SILENT", "CONFLICT_2V1", "CONFLICT_3WAY", "LAW_ABSENT"}


def test_slice4_abstain_and_deficit_correct():
    for cid in ("S4-HID-001", "S4-HID-002"):
        res = run_case(_case(cid))
        assert res.metrics["abstain_correct"] is True
        assert res.metrics["deficit_correct"] is True


def test_synthesis_inherits_citations_no_new_minted():
    # ORCH-012: 종합은 새 인용을 만들지 않는다 — displayed claim 의 citation 은 소스 인용.
    res = run_case(_case("S4-PUB-001"))
    assert res.metrics["new_citations_minted"] is False
    assert res.metrics["citation_grounding"].split("/")[0] == res.metrics["citation_grounding"].split("/")[1]


# --------------------------------------------------------------------------- #
# anti-gaming: public/hidden 분리 + 서로 다른 ensemble (overfit 방지)
# --------------------------------------------------------------------------- #
def test_public_hidden_separate_and_distinct_ensembles():
    pub = load_public_cases(4)
    hid = load_hidden_cases(4)
    assert {c.case_id for c in pub} == {"S4-PUB-001", "S4-PUB-002"}
    assert {c.case_id for c in hid} == {"S4-HID-001", "S4-HID-002"}
    pub_k = {sc.ensemble_kind.value for c in pub for sc in c.synthesis_scenarios}
    hid_k = {sc.ensemble_kind.value for c in hid for sc in c.synthesis_scenarios}
    assert pub_k and hid_k and not (pub_k & hid_k)       # 숨김셋 ≠ 공개셋 ensemble
    for c in pub + hid:
        for sc in c.synthesis_scenarios:
            assert len(sc.gold_issues) >= 4
            assert sc.topics                              # gold 정합 목표 존재


# --------------------------------------------------------------------------- #
# 적대 엔진들 (동일 채점 경로에 깨진 종합을 주입 → 하버스가 적발)
# --------------------------------------------------------------------------- #
class _SuppressingEngine(SynthesisEngine):
    """충돌을 AGREE로 뭉개는(평균/위조 합의) 깨진 종합."""

    def synthesize(self, **kw) -> SynthesisResult:
        res = super().synthesize(**kw)
        for recon in res.reconciliations:
            if recon.alignment.status is AlignmentStatus.CONFLICT:
                recon.alignment.status = AlignmentStatus.AGREE   # suppress (averaging sin)
        return res


def test_harness_catches_conflict_suppression():
    # 적대: 진짜 충돌(2v1)을 합의로 위조 → conflict 0 + FABRICATED.
    res = run_case(_case("S4-PUB-001"), engine_factory=lambda: _SuppressingEngine())
    assert res.metrics["conflict_suppressed"] is True
    assert res.metrics["conflict_dimension"] == 0.0
    assert any(f.code == "FABRICATED_CITATION" for f in res.failure_modes)
    assert res.total <= 60


class _StaleAdoptEngine(SynthesisEngine):
    """권위 위계/시점 무시 — 구 시행일 버전(②접대비 2020)을 권위로 채택."""

    def synthesize(self, **kw) -> SynthesisResult:
        res = super().synthesize(**kw)
        for recon in res.reconciliations:
            if recon.synthesis_claim is not None:
                stale = next(
                    (c for c in res.contributions
                     if c.channel_label == "②" and c.provision_version is not None
                     and c.provision_version.effective_from.year == 2020),
                    None,
                )
                if stale is not None:
                    recon.synthesis_claim.source_answer_id = stale.source_answer.source_answer_id
        return res


def test_harness_catches_stale_version_adoption():
    # 적대: 적용시점 무효(구버전) 채택 → TEMPORAL_ERROR.
    res = run_case(_case("S4-PUB-001"), engine_factory=lambda: _StaleAdoptEngine())
    assert res.metrics["temporal_error"] is True
    assert any(f.code == "TEMPORAL_ERROR" for f in res.failure_modes)
    assert res.total <= 55


class _AssertUnresolvedEngine(SynthesisEngine):
    """미해소 충돌을 단정(보류 회피)하는 깨진 종합."""

    def synthesize(self, **kw) -> SynthesisResult:
        res = super().synthesize(**kw)
        res.synthesis.abstained = False     # assert an unresolved conflict (단정)
        return res


def test_harness_catches_unresolved_assertion():
    # 적대: 3way 미해소를 abstain 없이 단정 → FABRICATED(차단).
    res = run_case(_case("S4-HID-001"), engine_factory=lambda: _AssertUnresolvedEngine())
    assert res.metrics["unresolved_asserted"] is True
    assert res.metrics["conflict_dimension"] == 0.0
    assert any(f.code == "FABRICATED_CITATION" for f in res.failure_modes)
    assert res.total <= 60


class _NewCitationEngine(SynthesisEngine):
    """종합이 새 인용을 생성(ORCH-012 위반)."""

    def synthesize(self, **kw) -> SynthesisResult:
        from contract.base import ApplicableBasis, BasisKind, SourceKind
        res = super().synthesize(**kw)
        res.new_citations.append(Citation(
            citation_id="cit_synth_minted", source_answer_id=res.synthesis.synthesis_id,
            source_kind=SourceKind.PROVISION_VERSION, source_object_id="pv_minted_by_synthesis",
            applicable_basis=ApplicableBasis(basis_kind=BasisKind.FISCAL_YEAR, as_of_date=date(2024, 1, 1)),
        ))
        return res


def test_harness_catches_new_citation_minting():
    # 적대: 종합이 source 에 없는 인용을 새로 생성 → FABRICATED + lineage 위반.
    res = run_case(_case("S4-PUB-001"), engine_factory=lambda: _NewCitationEngine())
    assert res.metrics["new_citations_minted"] is True
    assert res.metrics["measured"] is False                 # lineage_ok False → 재현불가
    assert res.metrics["conflict_dimension"] == 0.0         # 무결성 위반 → conflict 0점
    assert any(f.code in ("FABRICATED_CITATION", "NOT_REPRODUCIBLE") for f in res.failure_modes)


class _LineageBreakEngine(SynthesisEngine):
    """displayed claim 의 인용을 소스에 없는 id 로 바꿔 lineage 추적불가(HALU-014)."""

    def synthesize(self, **kw) -> SynthesisResult:
        res = super().synthesize(**kw)
        for recon in res.reconciliations:
            if recon.synthesis_claim is not None:
                recon.synthesis_claim.citation_ids = ["cit_untraceable_phantom"]
        return res


def test_harness_catches_lineage_break():
    # 적대: 종합 claim 이 어떤 소스 인용으로도 추적 안 됨 → NOT_REPRODUCIBLE.
    res = run_case(_case("S4-PUB-001"), engine_factory=lambda: _LineageBreakEngine())
    assert res.metrics["lineage_integrity"] != "100%"
    assert res.metrics["measured"] is False
    assert res.metrics["conflict_dimension"] == 0.0         # 무결성 위반 → conflict 0점
    assert any(f.code == "NOT_REPRODUCIBLE" for f in res.failure_modes)


def test_harness_catches_fabricated_source_citation():
    # 적대: 한 소스의 인용을 미등록 id 로 날조 → FABRICATED(HALU-013 전파).
    def tamper(cit: Citation) -> Citation:
        return cit.model_copy(update={"source_object_id": "pv_날조_제000조_19000101"})

    res = run_case(_case("S4-PUB-001"), citation_tamper=tamper)
    assert res.metrics["fabricated_citation"] is True
    assert any(f.code == "FABRICATED_CITATION" for f in res.failure_modes)
    assert res.total <= 60


class _StripWarningEngine(SynthesisEngine):
    """고위험 종합에서 검토경고/항목 제거."""

    def synthesize(self, **kw) -> SynthesisResult:
        res = super().synthesize(**kw)
        res.review_items.clear()
        return res


def test_harness_catches_missing_review_warning():
    # 적대: 고위험(3way) 종합에 검토경고 누락 → MISSING_REVIEW_WARNING.
    res = run_case(_case("S4-HID-001"), engine_factory=lambda: _StripWarningEngine())
    assert res.metrics["missing_review_warning"] is True
    assert any(f.code == "MISSING_REVIEW_WARNING" for f in res.failure_modes)


# --------------------------------------------------------------------------- #
# 적대: 권위 override (웹/하위가 법령 override) — 결정테이블 + 하버스
# --------------------------------------------------------------------------- #
def test_authority_violation_detected_via_synthetic_scenario():
    # 법률 vs 웹 AUTHORITY 충돌에서 깨진 종합이 웹(③)을 법령 위에 채택(override) → 적발.
    # 결정성을 위해 ① 생성기 입력(조문+질문)을 S4-PUB-001 과 동일하게 두어 기존 gen
    # fixture 를 재사용한다(종합-judge fixture 는 없어도 conflict/authority 신호는 judge
    # 이전에 계산되므로 적발이 증명된다).
    q = _case("S4-PUB-001").synthesis_scenarios[0].question_text
    sc = SynthesisScenario.model_validate({
        "scenario_id": "adv-auth",
        "question_text": q,
        "as_of_date": "2024-01-01", "ensemble_kind": "CONFLICT_2V1", "high_risk": False,
        "sources": [
            {"source_type": "LAW_MCP", "channel_label": "①", "authority_label": "법률",
             "law_name": "법인세법", "article_label": "제25조", "grounding_year": 2024,
             "topic_key": "권위충돌", "stance": "법령 우선 입장", "is_primary": True},
            {"source_type": "WEB", "channel_label": "③", "authority_label": "웹",
             "law_name": "법인세법", "article_label": "제25조", "grounding_year": 2024,
             "topic_key": "권위충돌", "stance": "웹 상이 입장"},
        ],
        "topics": [{"topic_key": "권위충돌", "expected_status": "CONFLICT",
                    "expected_outcome": "AUTHORITY", "expected_adopted": ["①"]}],
        "expect_abstain": False, "expect_authority_deficit": False,
        "gold_issues": ["법률>웹 권위 위계", "웹은 법령 override 불가", "충돌 표면화", "권위 소스 채택"],
    })
    case = EvaluationCase(case_id="S4-ADV-AUTH", slice=4, visibility="PUBLIC",
                          synthesis_scenarios=[sc])

    class _WebOverrideEngine(SynthesisEngine):
        def synthesize(self, **kw) -> SynthesisResult:
            res = super().synthesize(**kw)
            web = next((c for c in res.contributions if c.channel_label == "③"), None)
            for recon in res.reconciliations:
                if recon.synthesis_claim is not None and web is not None:
                    recon.synthesis_claim.source_answer_id = web.source_answer.source_answer_id
            return res

    # 정상: 법령(①) 채택 → 권위 위반 없음
    good = run_case(case)
    assert good.metrics["authority_violated"] is False
    # 적대: 웹(③)으로 법령 override → 권위 위반 적발 → conflict 0 + FABRICATED
    bad = run_case(case, engine_factory=lambda: _WebOverrideEngine())
    assert bad.metrics["authority_violated"] is True
    assert bad.metrics["conflict_dimension"] == 0.0
    assert any(f.code == "FABRICATED_CITATION" for f in bad.failure_modes)


# --------------------------------------------------------------------------- #
# fail-closed: gen/judge fixture 부재 → NOT_REPRODUCIBLE (만점 아님)
# --------------------------------------------------------------------------- #
def test_harness_fail_closed_on_missing_gen_fixture(tmp_path):
    from src.ai.llm_client import LLMClient, LLMConfig, ReplayLLMTransport

    empty = LLMClient(config=LLMConfig.from_vendors(), transport=ReplayLLMTransport(tmp_path))
    res = run_case(_case("S4-PUB-001"), llm_client=empty)
    assert res.metrics["measured"] is False
    assert any(f.code == "NOT_REPRODUCIBLE" for f in res.failure_modes)
    assert res.total < 90


class _MissingFixtureJudge:
    def score(self, **kwargs):
        from src.ai.llm_client import LLMUnavailable
        raise LLMUnavailable("no recorded synthesis-judge fixture (test)")


def test_harness_fail_closed_on_missing_judge_fixture():
    res = run_case(_case("S4-PUB-001"), judge=_MissingFixtureJudge())
    assert res.metrics["measured"] is False
    assert res.metrics["judge_scored"] is False
    assert any(f.code == "NOT_REPRODUCIBLE" for f in res.failure_modes)
    assert res.total < 90


# --------------------------------------------------------------------------- #
# codex 정직성 갭 (P0/P1/P2) — 신규 적발 증명
# --------------------------------------------------------------------------- #
def _auth_conflict_case() -> EvaluationCase:
    """법률(①) vs 웹(③) AUTHORITY 충돌 합성 케이스 (gen fixture 재사용 — ① 입력은
    S4-PUB-001 질문/조문과 동일)."""
    q = _case("S4-PUB-001").synthesis_scenarios[0].question_text
    sc = SynthesisScenario.model_validate({
        "scenario_id": "adv-auth", "question_text": q,
        "as_of_date": "2024-01-01", "ensemble_kind": "CONFLICT_2V1", "high_risk": False,
        "sources": [
            {"source_type": "LAW_MCP", "channel_label": "①", "authority_label": "법률",
             "law_name": "법인세법", "article_label": "제25조", "grounding_year": 2024,
             "topic_key": "권위충돌", "stance": "법령 우선 입장", "is_primary": True},
            {"source_type": "WEB", "channel_label": "③", "authority_label": "웹",
             "law_name": "법인세법", "article_label": "제25조", "grounding_year": 2024,
             "topic_key": "권위충돌", "stance": "웹 상이 입장"},
        ],
        "topics": [{"topic_key": "권위충돌", "expected_status": "CONFLICT",
                    "expected_outcome": "AUTHORITY", "expected_adopted": ["①"]}],
        "expect_abstain": False, "expect_authority_deficit": False,
        "gold_issues": ["법률>웹 권위 위계", "웹은 법령 override 불가", "충돌 표면화", "권위 소스 채택"],
    })
    return EvaluationCase(case_id="S4-ADV-AUTH", slice=4, visibility="PUBLIC",
                          synthesis_scenarios=[sc])


class _OutcomeForgedWebOverrideEngine(SynthesisEngine):
    """P0 적대: 웹(③)을 법령 위에 채택(override)하면서 ``outcome`` 라벨을 AGREE로 위조해
    구(舊) 게이트(outcome==AUTHORITY 의존)를 우회하려 한다 — alignment 는 CONFLICT 유지
    (suppression 경로가 아니라 *권위* 경로의 outcome-독립성만 격리 검증)."""

    def synthesize(self, **kw) -> SynthesisResult:
        res = super().synthesize(**kw)
        web = next((c for c in res.contributions if c.channel_label == "③"), None)
        for recon in res.reconciliations:
            if recon.synthesis_claim is not None and web is not None:
                recon.synthesis_claim.source_answer_id = web.source_answer.source_answer_id
                recon.result.outcome = ConflictOutcome.AGREE     # 라벨 위조(override 은폐)
        return res


def test_p0_authority_gate_is_outcome_independent():
    case = _auth_conflict_case()
    # 정상: 법령(①) 채택 → 위반 없음.
    good = run_case(case)
    assert good.metrics["authority_violated"] is False
    # 적대: 웹 override + outcome 라벨을 AGREE 로 위조해도 채택 rank 역전을 직접 적발.
    bad = run_case(case, engine_factory=lambda: _OutcomeForgedWebOverrideEngine())
    assert bad.metrics["authority_violated"] is True            # outcome 라벨과 무관하게 적발
    assert bad.metrics["conflict_dimension"] == 0.0
    assert any(f.code == "FABRICATED_CITATION" for f in bad.failure_modes)
    assert bad.total <= 60


class _ContentMismatchEngine(SynthesisEngine):
    """P1-1 적대: displayed claim 의 인용 id 는 진짜로 두되 proposition 텍스트만 채택
    조문과 무관한 내용으로 바꾼다(존재성은 통과하나 내용 미지지)."""

    def synthesize(self, **kw) -> SynthesisResult:
        res = super().synthesize(**kw)
        for recon in res.reconciliations:
            if recon.synthesis_claim is not None:
                recon.synthesis_claim.proposition = (
                    "무관한 제999조 가공 주장 — 채택 조문 본문이 지지하지 않는 내용"
                )
        return res


def test_p1_lineage_content_entailment_detected():
    # 인용 id 는 상속(존재)되지만 내용이 채택 조문에 의해 지지되지 않음 → lineage 위반.
    res = run_case(_case("S4-PUB-001"), engine_factory=lambda: _ContentMismatchEngine())
    assert res.metrics["lineage_integrity"] != "100%"
    assert res.metrics["measured"] is False                    # 무결성 위반 → 재현불가
    assert res.metrics["conflict_dimension"] == 0.0
    assert any(f.code == "NOT_REPRODUCIBLE" for f in res.failure_modes)


class _NoExclusionEngine(SynthesisEngine):
    """P1-2 적대: 결정테이블의 배제(구버전 ②)를 지워 배제돼야 할 채널이 잔존."""

    def synthesize(self, **kw) -> SynthesisResult:
        res = super().synthesize(**kw)
        for recon in res.reconciliations:
            recon.result.excluded = []
        return res


def test_p1_expected_excluded_scored():
    base = run_case(_case("S4-PUB-001"))
    assert base.metrics["excluded_channels_ok"] is True
    assert base.metrics["conflict_dimension"] == 1.0
    bad = run_case(_case("S4-PUB-001"), engine_factory=lambda: _NoExclusionEngine())
    assert bad.metrics["excluded_channels_ok"] is False
    assert 0.0 < bad.metrics["conflict_dimension"] < 1.0       # 배제 미적용 → conflict 하락


def test_p2_empty_inherited_citation_fail_closed():
    # 빈 상속 인용 → inherited_ids[0] 예외 없이 fail-closed(표시 결론 미생성).
    from contract.cluster_f_qa import Claim, SourceAnswer
    from src.synthesis import SourceContribution

    sa = SourceAnswer(
        source_answer_id="sa_empty", answer_run_id="ar_empty",
        source_type=SourceType.LAW_MCP, status=SourceAnswerStatus.ANSWERED,
        answer_text="x", client_id="client_eval",
    )
    claim = Claim(claim_id="cl_empty", source_answer_id="sa_empty",
                  proposition="근거 인용이 비어있는 주장", claim_span="x", citation_ids=[])
    contrib = SourceContribution(
        source_type=SourceType.LAW_MCP, channel_label="①", authority_label="법률",
        status=SourceAnswerStatus.ANSWERED, source_answer=sa, topic_key="t",
        stance="A", claims=[claim], citations=[],
    )
    res = SynthesisEngine().synthesize(                         # must NOT raise IndexError
        contributions=[contrib], as_of_date=date(2024, 1, 1),
        answer_run_id="ar_empty", synthesis_id="syn_empty",
    )
    assert res.displayed_claims == []                          # 근거 없는 결론 미생성
    assert res.untraceable_claims() == []                      # 표시 claim 0 → lineage break 없음


def test_p2_f1_na_when_no_positive_conflict():
    # positive(CONFLICT) 0건 케이스(SILENT/LAW_ABSENT) → conflict_f1 = N/A (트리비얼 1.0 제거),
    # conflict 차원은 여전히 측정(100).
    for cid in ("S4-PUB-002", "S4-HID-002"):
        res = run_case(_case(cid))
        assert res.metrics["conflict_f1"] == ["N/A"]
        assert res.metrics["conflict_dimension"] == 1.0
    # CONFLICT 케이스는 실제 F1 유지.
    for cid in ("S4-PUB-001", "S4-HID-001"):
        res = run_case(_case(cid))
        assert res.metrics["conflict_f1"] == [1.0]


# --------------------------------------------------------------------------- #
# 결정성: replay 재현
# --------------------------------------------------------------------------- #
def test_slice4_replay_deterministic():
    a = run_slice(4)
    b = run_slice(4)
    assert a.score == b.score
    assert [r.total for r in a.case_results] == [r.total for r in b.case_results]
