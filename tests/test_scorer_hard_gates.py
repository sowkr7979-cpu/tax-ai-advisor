"""P2-2 미등록 hard gate code는 조용히 무시되지 않고 fail-closed(예외)여야 한다.

오타난 게이트 code가 silently dropped 되면 실제 위반이 cap을 회피할 수 있다.
"""

from __future__ import annotations

import pytest

from contract.cluster_i_eval import Visibility
from rules.hard_gates import tightest_cap
from tiw.eval.scorer import build_rubric_result


def test_tightest_cap_rejects_unregistered_code():
    with pytest.raises(KeyError):
        tightest_cap(["TENANT_LEAK", "TYPO_GATE"])  # 미등록 code → 예외


def test_tightest_cap_known_codes_ok():
    # 등록된 code만 있으면 정상적으로 최저 cap 반환(회귀 방지).
    assert tightest_cap(["NOT_REPRODUCIBLE", "TENANT_LEAK"]) == 0
    assert tightest_cap([]) is None


def test_build_rubric_result_rejects_unknown_gate():
    # 동일 채점 경로(build_rubric_result)에서도 미등록 code는 통과 못 한다.
    with pytest.raises(KeyError):
        build_rubric_result(
            case_id="x",
            slice_no=6,
            target_id="x",
            visibility=Visibility.PUBLIC,
            dim_fractions={"security": 1.0},
            hard_gate_codes=["NOPE"],
        )


# --- PENDING_JUDGE: 보류 차원은 만점도 N/A도 아니다 (slice ① 요건) -------- #
def _pending_result():
    return build_rubric_result(
        case_id="p",
        slice_no=1,
        target_id="p",
        visibility=Visibility.PUBLIC,
        dim_fractions={"search": 1.0, "citation": 1.0},
        hard_gate_codes=[],
        pending_dimensions=["legal_reasoning", "risk"],
    )


def test_pending_dim_recorded_applicable_but_unscored():
    res = _pending_result()
    by = {s.dimension: s for s in res.dimension_scores}
    # PENDING: applicable=True 인데 score=None (만점 처리 금지)
    assert by["legal_reasoning"].applicable is True and by["legal_reasoning"].score is None
    assert "PENDING" in (by["legal_reasoning"].detail or "")
    # N/A(예: conflict): applicable=False
    assert by["conflict"].applicable is False
    assert res.has_pending and res.pending_dimensions == ["legal_reasoning", "risk"]


def test_pending_dim_excluded_from_total():
    # 보류 차원은 가중합 분모/분자에 들어가지 않는다(채점 수학 불변).
    res = _pending_result()
    assert res.raw_total == 100.0  # search/citation 만점만 반영, legal_reasoning 미반영


# --- P2-B: pending 결과의 완료점수 vs 결정적 소계 분리 (직렬화) ---------- #
def test_pending_headline_separated_in_serialization():
    res = _pending_result()  # legal_reasoning/risk 보류
    assert res.has_pending
    # 결정적 소계 = total, 완료점수 = None(보류) — 객체 필드/직렬화 모두에서 구분.
    assert res.deterministic_subtotal == res.total
    assert res.completion_score is None
    dumped = res.model_dump(mode="json")
    assert dumped["deterministic_subtotal"] == res.total
    assert dumped["completion_score"] is None


def test_completion_score_present_when_not_pending():
    res = build_rubric_result(
        case_id="d", slice_no=6, target_id="d", visibility=Visibility.PUBLIC,
        dim_fractions={"security": 1.0}, hard_gate_codes=[],
    )
    assert not res.has_pending
    # 보류 차원 없으면 완료점수 = 결정적 소계 = total.
    assert res.completion_score == res.total
    assert res.deterministic_subtotal == res.total
    dumped = res.model_dump(mode="json")
    assert dumped["completion_score"] == res.total


def test_pending_overlap_and_unknown_rejected():
    with pytest.raises(ValueError):
        build_rubric_result(
            case_id="x", slice_no=1, target_id="x", visibility=Visibility.PUBLIC,
            dim_fractions={"search": 1.0}, hard_gate_codes=[],
            pending_dimensions=["search"],  # scored+pending 동시 금지
        )
    with pytest.raises(KeyError):
        build_rubric_result(
            case_id="x", slice_no=1, target_id="x", visibility=Visibility.PUBLIC,
            dim_fractions={"search": 1.0}, hard_gate_codes=[],
            pending_dimensions=["NOT_A_DIM"],  # 미등록 차원 거부
        )
