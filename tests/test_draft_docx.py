"""Draft Agent — DOCX 검토패키지 결정적 테스트 (OUT-002/003/004/006).

핵심:
  - OUT-002/006 : 12목차 필수섹션을 모두 가진 DOCX 생성(누락 → 생성 실패).
  - OUT-003     : 무인용 단정 금지 — 리스크·쟁점메모는 인용 동반(미인용 → 차단).
  - OUT-004     : 고객 전달본은 승인 proof(ReleaseAuthorization, slice⑤ HITL) 없이
                  생성 불가 + 내부 전략메모(7)·검토항목(10) 제외.
  - 결정성      : 동일 입력 → 동일 DOCX 구조/본문(×N replay 일관).
  - 연계        : 인용=버전객체 Citation(slice①~④), 검토항목=slice⑤ review_items.

모두 오프라인(법령 fixture replay) — 실키/네트워크/LLM 불필요(flaky 0).
"""

from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path

import pytest

from contract.base import ApplicableBasis, BasisKind, ScopeType, SourceKind
from contract.cluster_a_tenancy import RoleAssignment, RoleName
from contract.cluster_f_qa import Citation
from contract.cluster_h_review import GateType, ReleaseAuthorization, ReviewItemCategory
from src.draft import (
    REQUIRED_SECTIONS,
    CitationView,
    DraftValidationError,
    OpportunityItem,
    RiskItem,
    StrategyOption,
    UnapprovedClientDraftError,
    build_client_deliverable_docx,
    build_review_package_docx,
    draft_package_to_fixture,
    validate_draft_package,
)
from src.draft_demo import build_demo_draft_package, build_frontend_fixture
from src.hitl import HitlWorkflow


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _docx_paragraphs(path: Path) -> list[str]:
    from docx import Document

    doc = Document(str(path))
    return [p.text for p in doc.paragraphs]


def _docx_headings(path: Path) -> list[str]:
    from docx import Document

    doc = Document(str(path))
    return [p.text for p in doc.paragraphs if p.style.name == "Heading 1"]


def _approved_proof(client_id: str, matter_id: str, *, high_risk: bool) -> ReleaseAuthorization:
    """slice⑤ HITL 로 H4(고위험)+H5 승인 → ReleaseAuthorization proof."""
    roles = {"r_cpa": RoleName.CPA, "r_rev": RoleName.REVIEWER}
    ras = [
        RoleAssignment(assignment_id="ra_cpa", user_id="u_cpa", role_id="r_cpa",
                       scope_type=ScopeType.MATTER, scope_id=matter_id, client_id=client_id),
        RoleAssignment(assignment_id="ra_rev", user_id="u_rev", role_id="r_rev",
                       scope_type=ScopeType.MATTER, scope_id=matter_id, client_id=client_id),
    ]
    wf = HitlWorkflow(client_id=client_id, matter_id=matter_id, draft_id="d_amfg",
                      role_assignments=ras, roles=roles)
    gates = [GateType.H4_HIGH_RISK, GateType.H5_APPROVAL] if high_risk else [GateType.H5_APPROVAL]
    for g in gates:
        wf.trigger(g)
        wf.decide(g, approver_user_id="u_rev", approved=True)
    return wf.produce_final_memo(high_risk=high_risk).release_proof


# --------------------------------------------------------------------------- #
# OUT-002/006 — 12목차 필수섹션
# --------------------------------------------------------------------------- #
def test_review_package_has_all_13_sections(tmp_path):
    data, titles, articles = build_demo_draft_package()
    out = build_review_package_docx(
        data, tmp_path / "pkg.docx", titles=titles, articles=articles
    )
    assert out.exists() and out.stat().st_size > 0
    headings = _docx_headings(out)
    assert headings == REQUIRED_SECTIONS  # 13 섹션, 정확한 순서
    assert len(REQUIRED_SECTIONS) == 13
    assert "8. 출처 채널별 독립 결과" in headings           # OUT-007 §8
    assert "10. 법령 추적 경로 + 추론 과정 도식" in headings  # OUT-008 §10


def test_missing_section_data_fails_closed():
    """OUT-006: 필수섹션 페이로드 누락(추가요청 자료 비움) → 생성 실패."""
    data, _, _ = build_demo_draft_package()
    broken = dataclasses.replace(data, additional_requests=[])
    with pytest.raises(DraftValidationError):
        validate_draft_package(broken)


def test_strategy_table_requires_three_options():
    """6. 비교표는 보수/중립/적극 3종 필수(§3-5)."""
    data, _, _ = build_demo_draft_package()
    only_two = dataclasses.replace(
        data, strategy_options=[o for o in data.strategy_options if o.option_key != "적극"]
    )
    with pytest.raises(DraftValidationError):
        validate_draft_package(only_two)


def test_out007_incomplete_channel_coverage_fails():
    """OUT-007(codex 적발): §8 은 3채널(①②③) 모두 표시 필수 — 채널 누락(부분 커버리지)은
    SILENT 로 남기지 않고 빼면 정직성 위반 → fail-closed. ③웹 누락 시 거부."""
    data, _, _ = build_demo_draft_package()
    missing_web = dataclasses.replace(
        data, channel_results=[cr for cr in data.channel_results if cr.channel != "③"]
    )
    with pytest.raises(DraftValidationError):
        validate_draft_package(missing_web)


def test_out007_silent_channel_is_accepted():
    """답 못한 채널은 *생략하지 않고* SILENT 로 present 하면 통과 — 검증 요건은 '채널 표시'
    이지 'ANSWERED' 가 아니다(정직 표기)."""
    from src.draft import ChannelResult
    data, _, _ = build_demo_draft_package()
    silent_web = ChannelResult(
        channel="③", source_label="③공식웹", status="SILENT", answered=False,
        answer_excerpt="(승격 가능한 공식근거 없음 — 커버리지 갭)", citation_locators=[],
    )
    with_silent = dataclasses.replace(
        data,
        channel_results=[cr for cr in data.channel_results if cr.channel != "③"] + [silent_web],
    )
    validate_draft_package(with_silent)  # must not raise (③ 가 SILENT 로 present)


def test_out008_fabricated_law_trace_is_rejected():
    """HALU-015(codex): §10 law-tracing 이 패키지에 없는 인용(조문/pinpoint)을 들면 —
    사후 서사·날조/stale — fail-closed. 존재만으로는 부족(실제 인용 정합 필수)."""
    from src.draft import LawTraceEntry, ReasoningTrace
    data, _, _ = build_demo_draft_package()
    rt = data.reasoning_trace
    fake = LawTraceEntry(
        issue="날조 쟁점", law_name="법인세법", article="제999조", as_of="2026-01-01",
        basis_kind="사업연도", locator="법인세법 제999조(존재하지 않음)", quote_excerpt="날조 인용",
    )
    bad = dataclasses.replace(
        data, reasoning_trace=ReasoningTrace(steps=rt.steps, law_trace=rt.law_trace + [fake]),
    )
    with pytest.raises(DraftValidationError):
        validate_draft_package(bad)


def test_out008_fabricated_step_citation_is_rejected():
    """추론 단계가 패키지에 없는 인용 pinpoint 를 들면 fail-closed(날조 차단)."""
    from src.draft import ReasoningStep, ReasoningTrace
    data, _, _ = build_demo_draft_package()
    rt = data.reasoning_trace
    bad_step = ReasoningStep(99, "SYNTHESIS", "날조 종합 단계",
                             citation_locators=["법인세법 제777조(없음)"])
    bad = dataclasses.replace(
        data, reasoning_trace=ReasoningTrace(steps=rt.steps + [bad_step], law_trace=rt.law_trace),
    )
    with pytest.raises(DraftValidationError):
        validate_draft_package(bad)


def test_out008_empty_locator_unbacked_law_trace_is_rejected():
    """HALU-015(codex 후속): locator 가 비어 있어도 (법령명,조문)이 패키지 인용과 매칭 안 되면
    거부 — 빈 locator 로 검증을 우회하던 미backed 날조행 차단."""
    from src.draft import LawTraceEntry, ReasoningTrace
    data, _, _ = build_demo_draft_package()
    rt = data.reasoning_trace
    fake_empty = LawTraceEntry(
        issue="빈 locator 날조", law_name="소득세법", article="제22조", as_of="2026-01-01",
        basis_kind="사업연도", locator="", quote_excerpt="패키지에 없는 소득세법 인용(빈 locator)",
    )
    bad = dataclasses.replace(
        data, reasoning_trace=ReasoningTrace(steps=rt.steps, law_trace=rt.law_trace + [fake_empty]),
    )
    with pytest.raises(DraftValidationError):
        validate_draft_package(bad)


def test_out008_stale_nonempty_locator_law_trace_is_rejected():
    """HALU-015(codex 후속): 비어있지 않은 locator 가 패키지 인용 문자열과 불일치(stale/오기)면
    — (법령명,조문) 쌍이 패키지에 있더라도 — 거부. pair fallback 은 빈 locator 에만 적용."""
    from src.draft import LawTraceEntry, ReasoningTrace
    data, _, _ = build_demo_draft_package()
    rt = data.reasoning_trace
    # (법인세법, 제25조)는 패키지에 존재하나 locator 문자열은 stale/오기(known_loc 에 없음)
    stale = LawTraceEntry(
        issue="stale locator", law_name="법인세법", article="제25조", as_of="2026-01-01",
        basis_kind="사업연도", locator="법인세법 제25조 [STALE 2020 버전 오기]",
        quote_excerpt="stale 인용 문자열",
    )
    bad = dataclasses.replace(
        data, reasoning_trace=ReasoningTrace(steps=rt.steps, law_trace=rt.law_trace + [stale]),
    )
    with pytest.raises(DraftValidationError):
        validate_draft_package(bad)


# --------------------------------------------------------------------------- #
# OUT-003 — 무인용 단정 금지
# --------------------------------------------------------------------------- #
def test_uncited_risk_is_rejected():
    data, _, _ = build_demo_draft_package()
    uncited = dataclasses.replace(
        data,
        risks=[RiskItem("무근거 단정", "인용 없는 법적 주장", citation_ids=[], severity="HIGH")],
    )
    with pytest.raises(DraftValidationError):
        validate_draft_package(uncited)


def test_unresolved_citation_reference_is_rejected():
    data, _, _ = build_demo_draft_package()
    dangling = dataclasses.replace(
        data,
        risks=[RiskItem("댕글링 인용", "존재하지 않는 근거 참조",
                        citation_ids=["cit_does_not_exist"], severity="HIGH")],
    )
    with pytest.raises(DraftValidationError):
        validate_draft_package(dangling)


def test_cited_claim_without_source_objects_is_rejected():
    """OUT-003 (codex stop-gate): source_objects(버전 소스객체)로 만든 SourceRegistry가
    없으면 인용을 검증할 수 없으므로, citation_index에만 존재하는 날조 인용이라도 통과시키지
    않는다(fail-closed). registry None → 검증 skip 이던 우회 경로 차단."""
    data, _, _ = build_demo_draft_package()
    assert data.source_objects, "데모는 버전 소스객체를 가져야 한다"
    # source_objects 제거 → registry None: 예전엔 인덱스 존재만 보고 통과(날조 우회)
    stripped = dataclasses.replace(data, source_objects=[])
    with pytest.raises(DraftValidationError):
        validate_draft_package(stripped)


def test_citations_and_review_items_present_in_docx(tmp_path):
    data, titles, articles = build_demo_draft_package()
    out = build_review_package_docx(data, tmp_path / "pkg.docx", titles=titles, articles=articles)
    text = "\n".join(_docx_paragraphs(out))
    # 8. 법령 근거: 버전객체 인용 + 공개 법령 링크
    assert "제25조" in text and "기업업무추진비" in text
    assert "https://www.law.go.kr/법령/법인세법/제25조" in text
    assert data.citations and all(c.applicable_basis is not None for c in data.citations)
    # 10. 회계사 검토 필요사항: slice⑤ review_items
    assert "회계사 검토 필요사항" in text
    assert any(it.requires_warning for it in data.review_items)
    assert "검토경고" in text  # HALU-009 carrier 표기


def test_citation_link_derives_law_name_from_locator_not_hardcoded_corporate():
    """변경①(다세목): 비-법인세 인용의 §9 근거 링크는 실제 locator 의 법령명으로 생성돼야 한다.

    과거 ``CitationView.from_citation`` 의 ``law_name`` 기본값이 '법인세법' 으로 하드코딩돼
    소득세법 인용의 링크가 ``…/법령/법인세법/제22조`` 로 잘못 향했다(codex 적발). 오프라인 법령
    replay 의 실제 버전객체로 소득세법 제22조 인용을 만들어 링크가 소득세법으로 가는지 검증한다."""
    from dataclasses import replace

    from src.ai.law_data_source import default_law_source
    from src.law_anchor import build_law_source_answer

    law = default_law_source()
    lk = replace(law.lookup_provision("소득세법", "제22조", date(2024, 1, 1)),
                 as_of_date=date(2026, 1, 1))
    bundle = build_law_source_answer(
        lookup=lk, client_id="client_retire", answer_run_id="ar_t",
        source_answer_id="sa_t_c22", source_type_label="법률", matter_id="matter_t")
    cv = CitationView.from_citation(bundle.citation, title="퇴직소득", article_label="제22조")
    assert cv.href == "https://www.law.go.kr/법령/소득세법/제22조"
    assert "법인세법" not in cv.href
    # 법인세법 인용(데모)은 그대로 법인세법 링크 유지(회귀 0)
    demo, titles, articles = build_demo_draft_package()
    dv = {v.citation_id: v for v in demo.citation_views(titles, articles)}
    assert any(v.href == "https://www.law.go.kr/법령/법인세법/제25조" for v in dv.values())


def test_citation_link_handles_multiword_law_name():
    """변경①(다세목): 공백 포함 법령명('상속세 및 증여세법')도 조문 토큰만 제외한 앞부분
    전체를 법령명으로 도출해 §9 링크가 정확해야 한다(loc.split()[0] 단순파싱 회귀 방지, codex)."""
    from types import SimpleNamespace

    fake = SimpleNamespace(
        citation_id="c_inh", source_locator="상속세 및 증여세법 제13조",
        source_kind="법률", quote="제13조(상속세 과세가액) …", authority_rank=1,
        applicable_basis=SimpleNamespace(
            as_of_date=date(2026, 1, 1), basis_kind=SimpleNamespace(value="FISCAL_YEAR")))
    cv = CitationView.from_citation(fake, title="상속세 과세가액", article_label="제13조")
    assert cv.href == "https://www.law.go.kr/법령/상속세 및 증여세법/제13조"


# --------------------------------------------------------------------------- #
# 결정성 — 동일 입력 → 동일 구조/본문
# --------------------------------------------------------------------------- #
def test_docx_generation_is_deterministic(tmp_path):
    data, titles, articles = build_demo_draft_package()
    a = build_review_package_docx(data, tmp_path / "a.docx", titles=titles, articles=articles)
    data2, titles2, articles2 = build_demo_draft_package()
    b = build_review_package_docx(data2, tmp_path / "b.docx", titles=titles2, articles=articles2)
    assert _docx_paragraphs(a) == _docx_paragraphs(b)
    assert _docx_headings(a) == _docx_headings(b)


# --------------------------------------------------------------------------- #
# OUT-004 — 고객 전달본 ≠ 내부 메모 (승인 proof 선행)
# --------------------------------------------------------------------------- #
def test_client_deliverable_blocked_without_proof(tmp_path):
    data, titles, articles = build_demo_draft_package()
    with pytest.raises(UnapprovedClientDraftError):
        build_client_deliverable_docx(
            data, tmp_path / "client.docx", release_proof=None,
            titles=titles, articles=articles,
        )


def test_client_deliverable_rejects_mismatched_proof(tmp_path):
    data, titles, articles = build_demo_draft_package()
    other = _approved_proof("client_other", "matter_other", high_risk=True)
    with pytest.raises(UnapprovedClientDraftError):
        build_client_deliverable_docx(
            data, tmp_path / "client.docx", release_proof=other,
            titles=titles, articles=articles,
        )


def test_client_deliverable_with_proof_excludes_internal_sections(tmp_path):
    data, titles, articles = build_demo_draft_package()
    proof = _approved_proof(data.client_id, data.matter_id, high_risk=data.high_risk)
    out = build_client_deliverable_docx(
        data, tmp_path / "client.docx", release_proof=proof,
        titles=titles, articles=articles,
    )
    headings = _docx_headings(out)
    # 내부 전용 섹션(7 쟁점메모·8 채널별 원본·10 추론도식·12 검토항목)은 고객본 제외(OUT-004)
    assert "7. 쟁점별 검토 메모" not in headings
    assert "8. 출처 채널별 독립 결과" not in headings
    assert "10. 법령 추적 경로 + 추론 과정 도식" not in headings
    assert "12. 회계사 검토 필요사항" not in headings
    # 그 외 9개 섹션은 유지
    assert "6. 선택지별 세부담·리스크 비교표" in headings
    assert "9. 관련 법령·근거 자료" in headings
    assert len(headings) == 9


# --------------------------------------------------------------------------- #
# 프론트 fixture — 화면 렌더용 분석결과 JSON
# --------------------------------------------------------------------------- #
def test_frontend_fixture_shape():
    fix = build_frontend_fixture()
    assert set(fix.keys()) == {"intake", "draft"}
    # 화면① intake: 인터뷰 루프 + 상태(수집/없음/모름/결손) + 마감 한계
    intake = fix["intake"]
    statuses = {m["status"] for m in intake["checklist"]}
    assert {"수집", "없음", "모름"}.issubset(statuses)
    assert intake["early_stopped"] is True
    assert intake["limits"] and intake["deficits"]
    # 화면② 선택지: 보수/중립/적극 + 세부담 값
    draft = fix["draft"]
    keys = [o["option_key"] for o in draft["strategy_options"]]
    assert keys == ["보수", "중립", "적극"]
    assert all(o["expected_tax_burden"] for o in draft["strategy_options"])
    # 화면③ DOCX 미리보기: 12섹션 + 인용 href + 채널별 결과(OUT-007)
    assert draft["sections"] == REQUIRED_SECTIONS
    assert {c["channel"] for c in draft["channel_results"]} == {"①", "②", "③"}
    assert draft["citations"] and all(c["href"].startswith("https://www.law.go.kr/")
                                      for c in draft["citations"])
    assert any(r["requires_warning"] for r in draft["review_items"])


def test_fixture_serialization_is_deterministic():
    data, titles, articles = build_demo_draft_package()
    a = draft_package_to_fixture(data, titles=titles, articles=articles)
    data2, titles2, articles2 = build_demo_draft_package()
    b = draft_package_to_fixture(data2, titles=titles2, articles=articles2)
    assert a == b


# --------------------------------------------------------------------------- #
# OUT-003 (P0-1) — 선택지·절세기회 무인용/날조 인용 거부 + SourceRegistry 검증
# --------------------------------------------------------------------------- #
def _fabricated_citation() -> Citation:
    """근거목록엔 들어있지만 SourceRegistry 에 등록된 소스객체로 해소되지 않는 날조 인용."""
    return Citation(
        citation_id="cit_fabricated",
        source_answer_id="sa_fake",
        source_kind=SourceKind.PROVISION_VERSION,
        source_object_id="pv_does_not_exist",
        source_locator="법인세법 제999조",
        quote="존재하지 않는 날조 인용",
        applicable_basis=ApplicableBasis(
            basis_kind=BasisKind.FISCAL_YEAR, as_of_date=date(2026, 1, 1)
        ),
        authority_rank=1,
    )


def test_uncited_strategy_option_is_rejected():
    """선택지(과세논리/방어논리)에 인용 없음 → 무인용 단정 거부."""
    data, _, _ = build_demo_draft_package()
    opts = [
        dataclasses.replace(o, citation_ids=[]) if o.option_key == "적극" else o
        for o in data.strategy_options
    ]
    with pytest.raises(DraftValidationError):
        validate_draft_package(dataclasses.replace(data, strategy_options=opts))


def test_uncited_opportunity_is_rejected():
    """절세기회 법적 주장에 인용 없음 → 무인용 단정 거부."""
    data, _, _ = build_demo_draft_package()
    bad = dataclasses.replace(
        data,
        opportunities=[OpportunityItem("무근거 절세기회", "인용 없는 법적 주장", citation_ids=[])],
    )
    with pytest.raises(DraftValidationError):
        validate_draft_package(bad)


def test_fabricated_strategy_citation_is_rejected():
    """선택지 인용이 SourceRegistry 미등록(날조 소스객체) → require_citation 으로 거부."""
    data, _, _ = build_demo_draft_package()
    fake = _fabricated_citation()
    opts = [
        dataclasses.replace(o, citation_ids=["cit_fabricated"]) if o.option_key == "적극" else o
        for o in data.strategy_options
    ]
    tampered = dataclasses.replace(
        data, citations=list(data.citations) + [fake], strategy_options=opts
    )
    with pytest.raises(DraftValidationError):
        validate_draft_package(tampered)


def test_fabricated_opportunity_citation_is_rejected():
    """절세기회 인용이 날조 소스객체 → SourceRegistry 검증으로 거부."""
    data, _, _ = build_demo_draft_package()
    fake = _fabricated_citation()
    bad_ops = [
        OpportunityItem("날조 절세기회", "날조 인용을 단 법적 주장", citation_ids=["cit_fabricated"]),
        *data.opportunities,
    ]
    tampered = dataclasses.replace(
        data, citations=list(data.citations) + [fake], opportunities=bad_ops
    )
    with pytest.raises(DraftValidationError):
        validate_draft_package(tampered)


def test_strategy_citation_rendered_in_docx(tmp_path):
    """선택지 비교표에 근거(인용) 라벨이 DOCX 로 렌더된다(OUT-003 표기)."""
    data, titles, articles = build_demo_draft_package()
    out = build_review_package_docx(data, tmp_path / "pkg.docx", titles=titles, articles=articles)
    from docx import Document

    doc = Document(str(out))
    table_text = "\n".join(
        c.text for t in doc.tables for r in t.rows for c in r.cells
    )
    assert "근거(인용)" in table_text          # 7번째 컬럼 헤더
    assert "제25조" in table_text              # 선택지 행의 인용 라벨


# --------------------------------------------------------------------------- #
# OUT-006 (P1-1) — 빈/공백 문자열 필드 거부
# --------------------------------------------------------------------------- #
def test_blank_additional_request_is_rejected():
    data, _, _ = build_demo_draft_package()
    with pytest.raises(DraftValidationError):
        validate_draft_package(dataclasses.replace(data, additional_requests=["  "]))


def test_blank_strategy_tax_risk_is_rejected():
    data, _, _ = build_demo_draft_package()
    opts = [
        dataclasses.replace(o, tax_risk="   ") if o.option_key == "중립" else o
        for o in data.strategy_options
    ]
    with pytest.raises(DraftValidationError):
        validate_draft_package(dataclasses.replace(data, strategy_options=opts))


def test_blank_risk_description_is_rejected():
    data, _, _ = build_demo_draft_package()
    bad = dataclasses.replace(
        data,
        risks=[RiskItem("제목만 있음", "   ", citation_ids=list(data.risks[0].citation_ids))],
    )
    with pytest.raises(DraftValidationError):
        validate_draft_package(bad)


# --------------------------------------------------------------------------- #
# HALU-008/009 (P1-2) — 고위험 콘텐츠 경고 누락 거부 (플래그만으로 비활성화 불가)
# --------------------------------------------------------------------------- #
def test_high_risk_content_without_warning_is_rejected():
    """high_risk=False 라도 적극 선택지/HIGH 리스크가 있으면 검토경고 누락 시 거부."""
    data, _, _ = build_demo_draft_package()
    stripped = [
        it for it in data.review_items
        if it.category is not ReviewItemCategory.HIGH_RISK_AGGRESSIVE
    ]
    no_warn = dataclasses.replace(data, high_risk=False, review_items=stripped)
    assert no_warn.review_items  # 섹션10(검토항목)은 여전히 비어있지 않음
    assert any(o.option_key == "적극" for o in no_warn.strategy_options)
    with pytest.raises(DraftValidationError):
        validate_draft_package(no_warn)


# --------------------------------------------------------------------------- #
# OUT-004 (P0-2) — proof 없는 고객 레이아웃 공개 경로 제거
# --------------------------------------------------------------------------- #
def test_no_public_client_layout_path():
    """build_review_package_docx 는 내부 전용 — internal=False 같은 고객 레이아웃
    공개 인자가 제거되어, 고객본은 proof 받는 build_client_deliverable_docx 로만 생성된다."""
    data, titles, articles = build_demo_draft_package()
    with pytest.raises(TypeError):
        build_review_package_docx(  # type: ignore[call-arg]
            data, "should_not_be_created.docx", internal=False,
            titles=titles, articles=articles,
        )
