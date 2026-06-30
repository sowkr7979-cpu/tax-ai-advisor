"""tests/test_slice7_harness.py — slice ⑦ 하버스 정직성 검증.

slice ⑦(다세목·투명성)이 (a) 실제 산출에서 3 기능을 채점하고, (b) *같은 채점 경로* 에
날조 패키지를 흘리면 하드게이트로 적발함을 증명한다(slice ⑥ 의 leaky-store 패턴).
"""
from __future__ import annotations

import dataclasses

from src.draft import LawTraceEntry, ReasoningStep, ReasoningTrace
from src.draft_demo import build_demo_draft_package
from tiw.eval.slices.slice7_multitax_transparency import run_cases


def test_slice7_pending_until_noncorporate_pipeline_recorded():
    """정직성(codex): slice⑦ 은 비-법인세(소득세) 파이프라인이 *실제 패키지를 산출* 할 때만
    requirement 가 채점된다. 현 replay 는 소득세 fixture 미녹화 → ROUTING_ONLY(소득세법
    라우팅만 확인) → requirement PENDING → 슬라이스 ≥90 불가(registry 만으로 false-pass 금지).
    결정적 차원(citation/output/ops)은 정상 채점, 하드게이트 0."""
    [r] = run_cases([])
    assert r.has_pending
    assert "requirement" in r.pending_dimensions
    assert not r.hard_gate_hit
    assert str(r.metrics.get("income_tax_pipeline", "")).startswith("ROUTING_ONLY")
    dims = {s.dimension: s.score for s in r.dimension_scores if s.applicable and s.score is not None}
    assert dims.get("citation") == 100      # §10 trace backed(날조/stale 0)
    assert dims.get("output") == 100        # §8 채널 + §10 도식 + 13목차
    assert dims.get("ops") == 100


def test_slice7_harness_catches_fabricated_trace():
    """적대적: 날조 law_trace(패키지에 없는 인용) 패키지를 같은 채점 경로에 흘리면
    FABRICATED_CITATION 트립 → cap 60(만점 불가). '측정 못 함 = 통과' 금지 증명."""
    def _fabricated_package():
        data, _, _ = build_demo_draft_package()
        rt = data.reasoning_trace
        fake = LawTraceEntry(
            issue="날조 쟁점", law_name="소득세법", article="제999조", as_of="2026-01-01",
            basis_kind="사업연도", locator="소득세법 제999조(패키지에 없음)", quote_excerpt="x",
        )
        return dataclasses.replace(
            data, reasoning_trace=ReasoningTrace(steps=rt.steps, law_trace=rt.law_trace + [fake]),
        )

    [r] = run_cases([], package_factory=_fabricated_package)
    codes = {f.code for f in r.failure_modes}
    assert "FABRICATED_CITATION" in codes
    assert r.hard_gate_hit
    assert r.total <= 60  # 하드게이트 cap


def test_slice7_harness_catches_fabricated_step_citation():
    """적대적: 추론단계가 패키지에 없는 인용 pinpoint 를 들면도 FABRICATED_CITATION 적발."""
    def _bad_step_package():
        data, _, _ = build_demo_draft_package()
        rt = data.reasoning_trace
        bad = ReasoningStep(99, "SYNTHESIS", "날조 단계",
                            citation_locators=["법인세법 제777조(없음)"])
        return dataclasses.replace(
            data, reasoning_trace=ReasoningTrace(steps=rt.steps + [bad], law_trace=rt.law_trace),
        )

    [r] = run_cases([], package_factory=_bad_step_package)
    assert "FABRICATED_CITATION" in {f.code for f in r.failure_modes}
    assert r.total <= 60


def test_slice7_harness_trips_not_reproducible_on_failure():
    """적대적: 산출 자체가 실패(예외)하면 NOT_REPRODUCIBLE → cap 75('측정 못 함=만점' 금지)."""
    def _broken():
        raise RuntimeError("오케스트레이터 산출 실패 시뮬")

    [r] = run_cases([], package_factory=_broken)
    assert "NOT_REPRODUCIBLE" in {f.code for f in r.failure_modes}
    assert r.total <= 75
