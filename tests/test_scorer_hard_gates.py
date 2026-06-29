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
