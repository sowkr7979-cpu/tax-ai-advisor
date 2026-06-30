"""tiw/eval/slices/slice7_multitax_transparency.py — slice ⑦ harness (다세목·투명성).

slice ⑦ = 사용자 승인 v1.1 기능 확장 3종(변경①②③). DETERMINISTIC 으로 측정한다
(판단 차원·gold 정답 불필요 — slice ⑥ 처럼 *구조·정합* 속성을 코드로 검증):

  - requirement (6): **변경① ORCH-015** 다세목 매핑 — 법인세 외 세목(소득세/퇴직소득)이
        자기 세법으로 라우팅, 미등록 쟁점은 fail-closed(None). 실제 오케스트레이터가 13목차
        패키지를 산출.
  - citation    (12): **변경③ OUT-008/HALU-015** §10 추론 트레이스 + law-tracing 의 *정합* —
        모든 law_trace 행·추론단계 인용이 실제 패키지 인용으로 backed(날조/stale 0).
  - output      (9): **변경② OUT-007 + 변경③ §10** 투명성 — §8 채널별 독립결과(①②③ 전부) +
        §10 추론도식(steps+law_trace) + 13목차 완비(reviewer 가 사고과정/채널을 직접 봄).
  - ops         (2): 오케스트레이터 + 패키지 검증이 예외 없이 완주.

Hard gates (frozen, rules/hard_gates.py):
  - §10 trace 가 패키지에 없는 인용(조문/pinpoint)을 들면(사후 서사/날조) → FABRICATED_CITATION (cap 60).
  - 오케스트레이터가 산출에 실패하면 → NOT_REPRODUCIBLE (cap 75).

ANTI-GAMING: 다른 판단 차원(법리·쟁점·리스크·충돌·검색·보안)은 slice ①~⑥ 가 행사하므로
slice ⑦ 에서는 N/A(scorer 가 분모에서 제외) — 행사 안 한 차원을 만점으로 크레딧하지 않는다.
`package_factory` 는 **적대적 테스트가 *날조* 패키지를 같은 채점 경로에 흘려 FABRICATED_CITATION
이 실제로 트립됨을 증명**하기 위한 주입점이다(운영 코드는 override 안 함).

NOTE(정직성): 현재 slice ⑦ 은 *결정적 구조 속성* 만 채점하는 **public** 측정이다. 판단 품질
(세무 적합성)·hidden freeze CPA 케이스는 docs/09 §10 절차대로 사용자(회계사) 시드·검증이
선행되어야 하며(미시드 — STATUS.md), 그 전까지 이 점수는 *결정적 소계* 로 읽어야 한다.
"""

from __future__ import annotations

from statistics import mean
from typing import Callable, Optional

from contract.cluster_i_eval import EvaluationCase, RubricResult, TargetKind, Visibility
from rules.tax_law_mapping import law_name_for, load_mapping
from tiw.eval.scorer import build_rubric_result

SLICE_NO = 7
_CASE_ID = "S7-PUB-001"

# (pkg, ) 를 만드는 factory — 기본은 실제 오케스트레이터(replay 데모). 적대적 테스트만 override.
PackageFactory = Callable[[], object]


def _real_package():
    """실제 §4-1 오케스트레이터(replay 데모 A제조 법인세) → DraftPackageData."""
    from src.orchestrator import DEFAULT_COMPANY_FIXTURE, CompanyProfile, Orchestrator

    company = CompanyProfile.from_fixture(DEFAULT_COMPANY_FIXTURE)
    result = Orchestrator(mode="replay").run(
        company=company, question=company.default_question, write_docx=False,
    )
    return result.package


def _known_locators(pkg) -> tuple[set, set]:
    """패키지의 *실제* 인용 pinpoint 집합 + (법령명,조문) 쌍(빈 locator 매칭용)."""
    actual = {c.source_locator for c in pkg.citations if c.source_locator}
    chan = {loc for cr in pkg.channel_results for loc in cr.citation_locators}
    pairs = set()
    for c in pkg.citations:
        toks = (c.source_locator or "").split()
        if len(toks) >= 2:
            pairs.add((toks[0], toks[-1]))
    return (actual | chan), pairs


def _trace_fully_backed(pkg) -> bool:
    """§10 trace 의 모든 law_trace 행·추론단계 인용이 실제 패키지 인용으로 backed 인가
    (날조/stale 0). draft.validate 와 동일 규칙을 *독립 채점 경로* 에서 재검증한다."""
    rt = pkg.reasoning_trace
    if rt is None:
        return False
    known, pairs = _known_locators(pkg)
    for e in rt.law_trace:
        ok = (e.locator in known) if e.locator else ((e.law_name, e.article) in pairs)
        if not ok:
            return False
    for s in rt.steps:
        if any(loc not in known for loc in s.citation_locators):
            return False
    return True


def _evaluate(package_factory: Optional[PackageFactory] = None) -> RubricResult:
    from src.draft import REQUIRED_SECTIONS

    hard: list[str] = []
    metrics: dict = {}

    # -- 변경① ORCH-015 다세목 매핑(requirement) — 오케스트레이터와 독립 결정적 ----- #
    mapping = load_mapping()
    n_tax_types = len({m.tax_type for m in mapping.values()})
    multitax_ok = (
        law_name_for("기업업무추진비") == "법인세법"        # 법인세 쟁점 → 법인세법
        and law_name_for("퇴직소득구분") == "소득세법"      # 비-법인세 세목 등록·라우팅
        and law_name_for("__미등록쟁점__") is None          # 미등록 → fail-closed(None)
        and n_tax_types >= 2                               # 최소 2 세목(법인세 외 1)
    )
    metrics["tax_types"] = n_tax_types
    metrics["multitax_routing_ok"] = multitax_ok

    # -- 실제 오케스트레이터 산출(ops/output/citation) ----------------------------- #
    completed = True
    pkg = None
    try:
        pkg = (package_factory or _real_package)()
    except Exception as exc:  # noqa: BLE001 — 산출 실패는 ops 실패(재현 불가), 만점 금지
        completed = False
        hard.append("NOT_REPRODUCIBLE")
        metrics["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"

    channels_ok = trace_present = backed = sections_ok = False
    if completed and pkg is not None:
        chans = {cr.channel for cr in pkg.channel_results}
        channels_ok = chans == {"①", "②", "③"}                       # OUT-007 3채널 전부
        rt = pkg.reasoning_trace
        trace_present = rt is not None and bool(rt.steps) and bool(rt.law_trace)
        backed = _trace_fully_backed(pkg)                              # OUT-008 날조/stale 0
        sections_ok = len(REQUIRED_SECTIONS) == 13                     # 13목차
        metrics.update(
            channels=sorted(chans),
            trace_steps=len(rt.steps) if rt else 0,
            law_trace=len(rt.law_trace) if rt else 0,
            trace_backed=backed,
            sections=len(REQUIRED_SECTIONS),
        )
        # 사후 서사/날조 trace → 인용 날조 하드게이트(cap 60). 정직성 위반은 만점 불가.
        if rt is not None and not backed:
            hard.append("FABRICATED_CITATION")

    # -- 차원 fractions(0..1) — 행사하는 차원만(나머지는 N/A) ---------------------- #
    requirement_frac = mean([
        1.0 if multitax_ok else 0.0,
        1.0 if (completed and sections_ok) else 0.0,
    ])
    citation_frac = 1.0 if (trace_present and backed) else (0.5 if trace_present else 0.0)
    output_frac = mean([
        1.0 if channels_ok else 0.0,
        1.0 if trace_present else 0.0,
        1.0 if sections_ok else 0.0,
    ])
    ops_frac = 1.0 if completed else 0.0

    return build_rubric_result(
        case_id=_CASE_ID,
        slice_no=SLICE_NO,
        target_id=_CASE_ID,
        visibility=Visibility.PUBLIC,
        target_kind=TargetKind.SLICE,
        dim_fractions={
            "requirement": requirement_frac,
            "citation": citation_frac,
            "output": output_frac,
            "ops": ops_frac,
        },
        dim_details={
            "requirement": f"multitax_ok={multitax_ok} tax_types={n_tax_types} "
            f"13목차={sections_ok}",
            "citation": f"trace_backed={backed} (날조/stale 0 = OUT-008/HALU-015)",
            "output": f"channels={channels_ok} trace={trace_present} sections={sections_ok}",
            "ops": f"completed={completed}",
        },
        hard_gate_codes=hard,
        metrics={
            **metrics,
            # 점수 투명성(codex P1-3 패턴): 분모(행사 차원)와 미행사 차원을 명시.
            "scope_note": "slice⑦ 결정적 구조 채점(requirement6+citation12+output9+ops2=29 분모). "
            "판단차원(법리/쟁점/리스크/충돌/검색/보안)은 ①~⑥ 행사 → N/A. "
            "hidden freeze CPA 케이스 미시드(docs/09 §10) — 결정적 소계로 해석.",
        },
    )


def run_cases(cases: list[EvaluationCase], package_factory: Optional[PackageFactory] = None,
              ) -> list[RubricResult]:
    """slice ⑦ 채점. gold 파일 의존 없이 *자체 결정적 케이스* 로 3 기능을 측정한다
    (tests/golden 에 S7 케이스 없음 — 빈 ``cases`` 는 무시). ``package_factory`` 주입 시
    적대적 패키지를 같은 채점 경로에 흘려 하드게이트 적발을 증명한다."""
    return [_evaluate(package_factory=package_factory)]
