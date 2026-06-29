"""slice ① 법령MCP 앵커 — 결정적 테스트 (실키/네트워크 불필요, fixture 재생).

핵심:
  - LawDataSource 추상화 + 법제처(MOLEG) 백엔드 + MCP→법제처 fallback (API-002/003).
  - as-of-date 시행일 버전 고정: 2020→'접대비', 2024→'기업업무추진비' (PROV-003).
  - SourceSnapshot content_hash 재현성 (API-004) + fixture 재생 결정성.
  - source registry (P1-1): 존재/kind 정합 검증 — 날조 인용 거부.
  - 하버스 정직성(anti-gaming): 잘못된 버전→TEMPORAL_ERROR, 날조 인용→
    FABRICATED_CITATION, 조회 실패→NOT_REPRODUCIBLE 를 *동일 채점 경로*에서 적발.
  - PENDING_JUDGE: 법리 등은 보류(만점 아님, N/A 아님) → 슬라이스 미완료.
"""

from __future__ import annotations

from datetime import date
from unittest import mock

import pytest

from contract.base import SourceKind
from contract.cluster_d_provenance import ProvisionVersion, Ruling
from contract.cluster_f_qa import Citation
from contract.cluster_i_eval import EvaluationCase
from src.ai.law_data_source import (
    DEFAULT_FIXTURES_DIR,
    FallbackLawDataSource,
    KoreanLawMCPSource,
    LawSourceUnavailable,
    MOLEGLawDataSource,
    ReplayTransport,
    default_law_source,
)
from src.law_anchor import REVIEW_WARNING, build_law_source_answer
from src.source_registry import (
    CitationVerificationError,
    SourceRegistry,
    VerificationStatus,
)
from tiw.eval.loader import load_hidden_cases, load_public_cases
from tiw.eval.runner import run_slice
from tiw.eval.slices.slice1_law_anchor import run_case


# --- LawDataSource: as-of 시행일 버전 고정 (API-003 / PROV-003) ----------- #
def test_asof_pins_distinct_versions():
    src = default_law_source()
    v2024 = src.lookup_provision("법인세법", "제25조", date(2024, 1, 1))
    v2020 = src.lookup_provision("법인세법", "제25조", date(2020, 1, 1))
    assert "기업업무추진비" in v2024.article_title
    assert "접대비" in v2020.article_title
    # 다른 연도 → 다른 ProvisionVersion (시행일/본문 해시 모두 상이)
    assert v2024.provision_version.effective_from == date(2024, 1, 1)
    assert v2020.provision_version.effective_from == date(2020, 1, 1)
    assert v2024.provision_version.hash != v2020.provision_version.hash


def test_fallback_chain_mcp_then_moleg():
    src = default_law_source()
    result = src.lookup_provision("법인세법", "제25조", date(2024, 1, 1))
    # MCP(unwired) 먼저 시도 → 법제처가 응답 (API-003 fallback)
    assert result.fallback_chain[0] == "korean-law-mcp"
    assert "법제처" in result.backend


def test_mcp_source_unwired_raises():
    with pytest.raises(LawSourceUnavailable):
        KoreanLawMCPSource().lookup_provision("법인세법", "제25조", date(2024, 1, 1))


# --- 재현성 (API-004): 해시 복원 + fixture 재생 ------------------------- #
def test_snapshot_hash_reproducible_from_fixture():
    src = MOLEGLawDataSource(transport=ReplayTransport(DEFAULT_FIXTURES_DIR))
    r1 = src.lookup_provision("법인세법", "제25조", date(2024, 1, 1))
    r2 = src.lookup_provision("법인세법", "제25조", date(2024, 1, 1))
    assert r1.snapshot.content_hash == r2.snapshot.content_hash  # 결정적
    assert r1.snapshot.official is True
    assert r1.snapshot.content_hash and len(r1.snapshot.content_hash) == 64


def test_missing_fixture_fails_closed(tmp_path):
    # 빈 fixtures 디렉터리 → 조회 실패 (만점 아니라 예외 = fail-closed)
    src = MOLEGLawDataSource(transport=ReplayTransport(tmp_path))
    with pytest.raises(LawSourceUnavailable):
        src.lookup_provision("법인세법", "제25조", date(2024, 1, 1))


def _load_oc_from_env() -> str | None:
    """Read the real OC from .env (never hardcode the secret in a test file)."""
    from pathlib import Path

    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return None
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("LAW_OC="):
            return line.split("=", 1)[1].strip().strip('"').strip() or None
    return None


def test_fixtures_carry_no_secret():
    # OC(인증키)가 녹화 fixture/manifest 에 새지 않았는지 (비밀키 금지). OC 값은
    # .env 에서 읽어 비교 — 테스트 파일에 키를 하드코딩하지 않는다.
    import json

    manifest = json.loads((DEFAULT_FIXTURES_DIR / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest.values():
        assert "OC=***" in entry["url_redacted"]  # 항상 마스킹돼야 한다

    oc = _load_oc_from_env()
    if not oc:
        pytest.skip(".env LAW_OC 없음 — 마스킹 마커만 검증")
    oc_b = oc.encode("utf-8")
    for entry in manifest.values():
        assert oc not in entry["url_redacted"]
    for xml in DEFAULT_FIXTURES_DIR.glob("*.xml"):
        assert oc_b not in xml.read_bytes()


# --- source registry (P1-1): 존재/kind 정합 ------------------------------ #
def _basis_citation(pv: ProvisionVersion, kind=SourceKind.PROVISION_VERSION, oid=None) -> Citation:
    from contract.base import ApplicableBasis, BasisKind

    return Citation(
        citation_id="c1",
        source_answer_id="sa1",
        source_kind=kind,
        source_object_id=oid or pv.provision_version_id,
        source_locator="법인세법 제25조",
        applicable_basis=ApplicableBasis(basis_kind=BasisKind.FISCAL_YEAR, as_of_date=date(2024, 1, 1)),
    )


def test_registry_accepts_real_citation():
    src = default_law_source()
    lookup = src.lookup_provision("법인세법", "제25조", date(2024, 1, 1))
    reg = SourceRegistry()
    reg.register_all([lookup.provision_version, lookup.snapshot])
    v = reg.verify_citation(_basis_citation(lookup.provision_version))
    assert v.ok and v.status is VerificationStatus.OK


def test_registry_rejects_fabricated_id():
    src = default_law_source()
    lookup = src.lookup_provision("법인세법", "제25조", date(2024, 1, 1))
    reg = SourceRegistry()
    reg.register_all([lookup.provision_version, lookup.snapshot])
    bogus = _basis_citation(lookup.provision_version, oid="pv_존재하지않는_제999조_20240101")
    v = reg.verify_citation(bogus)
    assert v.is_fabrication and v.status is VerificationStatus.NOT_FOUND


def test_registry_rejects_kind_mismatch():
    src = default_law_source()
    lookup = src.lookup_provision("법인세법", "제25조", date(2024, 1, 1))
    reg = SourceRegistry()
    reg.register_all([lookup.provision_version, lookup.snapshot])
    # 같은 id 인데 kind 를 RULING 으로 위조 → kind 불일치
    mism = _basis_citation(lookup.provision_version, kind=SourceKind.RULING)
    v = reg.verify_citation(mism)
    assert v.is_fabrication and v.status is VerificationStatus.KIND_MISMATCH


# --- P1-B: citation 경계에서 registry 검증 필수화 (eval 우회 차단) -------- #
def test_builder_rejects_unregistered_provision():
    # eval 하버스를 거치지 않고 src.law_anchor 빌더를 직접 호출해도, 권위 레지스트리에
    # 등록되지 않은(=미존재) 조문 인용은 경계에서 거부된다(NOT_FOUND).
    src = default_law_source()
    lookup = src.lookup_provision("법인세법", "제25조", date(2024, 1, 1))
    empty = SourceRegistry()  # 권위 카탈로그에 해당 조문 미등록 = 미존재 조문
    with pytest.raises(CitationVerificationError) as exc:
        build_law_source_answer(
            lookup=lookup, client_id="c", answer_run_id="ar",
            source_answer_id="sa", registry=empty,
        )
    assert exc.value.verification.status is VerificationStatus.NOT_FOUND


def test_builder_rejects_kind_mismatch_at_boundary():
    # 동일 id 가 RULING 으로 등록된 권위 레지스트리 → PROVISION_VERSION 인용과 kind 불일치.
    src = default_law_source()
    lookup = src.lookup_provision("법인세법", "제25조", date(2024, 1, 1))
    pv = lookup.provision_version
    reg = SourceRegistry()
    reg.register(Ruling(ruling_id=pv.provision_version_id, document_number="x", title="x"))
    with pytest.raises(CitationVerificationError) as exc:
        build_law_source_answer(
            lookup=lookup, client_id="c", answer_run_id="ar",
            source_answer_id="sa", registry=reg,
        )
    assert exc.value.verification.status is VerificationStatus.KIND_MISMATCH


def test_builder_self_verifies_without_registry():
    # registry 미지정(기본) 경로: 번들 자신의 버전객체로 자기검증 통과(정상 lookup).
    src = default_law_source()
    lookup = src.lookup_provision("법인세법", "제25조", date(2024, 1, 1))
    bundle = build_law_source_answer(
        lookup=lookup, client_id="c", answer_run_id="ar", source_answer_id="sa"
    )
    assert bundle.citation.source_object_id == lookup.provision_version.provision_version_id


# --- SourceAnswer(LAW_MCP) builder (PROV-002/004/005) -------------------- #
def test_builder_anchors_to_provision_version():
    src = default_law_source()
    lookup = src.lookup_provision("법인세법", "제25조", date(2024, 1, 1))
    bundle = build_law_source_answer(
        lookup=lookup, client_id="client_A", answer_run_id="ar1", source_answer_id="sa1"
    )
    cit = bundle.citation
    assert cit.source_kind is SourceKind.PROVISION_VERSION
    assert cit.source_object_id == lookup.provision_version.provision_version_id
    assert "제25조" in (cit.source_locator or "")             # pinpoint (PROV-004)
    assert cit.applicable_basis.as_of_date == date(2024, 1, 1)  # 시점 (PROV-005)
    assert cit.quote                                           # 지지 발췌
    assert bundle.source_answer.source_type.value == "LAW_MCP"
    assert bundle.source_answer.client_id == "client_A"        # 격리키 전파


def test_builder_high_risk_attaches_warning():
    src = default_law_source()
    lookup = src.lookup_provision("법인세법", "제24조", date(2024, 1, 1))
    hi = build_law_source_answer(
        lookup=lookup, client_id="c", answer_run_id="ar", source_answer_id="sa", high_risk=True
    )
    lo = build_law_source_answer(
        lookup=lookup, client_id="c", answer_run_id="ar", source_answer_id="sa2", high_risk=False
    )
    assert REVIEW_WARNING in hi.review_warnings and REVIEW_WARNING in hi.source_answer.answer_text
    assert lo.review_warnings == []


# --- 하버스 end-to-end (slice ①) ---------------------------------------- #
def test_slice1_harness_deterministic_dims_pass_but_pending():
    report = run_slice(1)
    assert report.case_results
    assert report.hidden_count >= 1 and report.public_count >= 1
    assert not report.hard_gate_hit
    assert report.score >= 90               # 결정적 소계
    # 법리 등은 보류 → 슬라이스는 완료가 아니다(만점 처리 금지)
    assert report.pending is True
    assert not report.passed
    assert "legal_reasoning" in report.pending_dimensions
    for r in report.case_results:
        assert r.metrics["recall"] == 1.0
        assert r.metrics["reproducible"] is True
        assert r.metrics["entailment"] == "PENDING_JUDGE"


# --- 정직성: 잘못된 시행일 버전 → TEMPORAL_ERROR ------------------------- #
class _WrongVersionSource:
    """as-of 와 무관하게 항상 2024 버전을 돌려주는 적대적 소스(테스트 전용)."""

    name = "wrong-version"

    def __init__(self) -> None:
        self._inner = default_law_source()

    def lookup_provision(self, law_name, article_label, as_of_date):
        return self._inner.lookup_provision(law_name, article_label, date(2024, 1, 1))


def _public_case(case_id: str) -> EvaluationCase:
    for c in load_public_cases(1):
        if c.case_id == case_id:
            return c
    raise AssertionError(f"{case_id} not found")


def test_harness_catches_wrong_version_as_temporal_error():
    # S1-PUB-002 는 as-of 2020(접대비) 인데, 잘못된 소스가 2024(기업업무추진비)를 주면
    # 동일 채점 경로에서 시행일 오류로 적발되어 캡(≤55) 되어야 한다.
    case = _public_case("S1-PUB-002")
    wrong = run_case(case, law_source=_WrongVersionSource())
    assert wrong.metrics["temporal_error"] is True
    assert any(f.code == "TEMPORAL_ERROR" for f in wrong.failure_modes)
    assert wrong.total <= 55
    # 정상 소스는 같은 케이스에서 시행일 오류 없음
    clean = run_case(case)
    assert clean.metrics["temporal_error"] is False
    assert not clean.hard_gate_hit


# --- 정직성: 날조 인용 → FABRICATED_CITATION ----------------------------- #
def test_harness_catches_fabricated_citation():
    case = _public_case("S1-PUB-001")

    def tamper(cit: Citation) -> Citation:
        return cit.model_copy(update={"source_object_id": "pv_날조_제000조_19000101"})

    res = run_case(case, citation_tamper=tamper)
    assert res.metrics["fabricated_citation"] is True
    assert any(f.code == "FABRICATED_CITATION" for f in res.failure_modes)
    assert res.total <= 60


# --- 정직성: 조회 실패 → NOT_REPRODUCIBLE (fail-closed) ------------------- #
def test_harness_fail_closed_on_unresolved_lookup(tmp_path):
    case = _public_case("S1-PUB-001")
    broken = MOLEGLawDataSource(transport=ReplayTransport(tmp_path))  # 빈 fixtures
    res = run_case(case, law_source=broken)
    assert res.metrics["measured"] is False
    assert any(f.code == "NOT_REPRODUCIBLE" for f in res.failure_modes)
    assert res.total < 90


# --- P1-A: 검색 단계 실패 → NOT_REPRODUCIBLE (silent passthrough 금지) ---- #
class _NoSearchTransport:
    """efbody fixture 는 정상 재생하되 lawSearch fixture 만 누락된 상황을 모사
    (검색 fixture 제거/조작 → search_found=False). 본문은 여전히 핀되지만, 검색
    단계가 필수 재현성 조건이므로 NOT_REPRODUCIBLE 로 닫혀야 한다."""

    def __init__(self) -> None:
        self._inner = ReplayTransport(DEFAULT_FIXTURES_DIR)

    def resolve(self, req):
        if req.endpoint == "lawSearch":
            raise LawSourceUnavailable("search fixture removed (test)")
        return self._inner.resolve(req)


def test_harness_fail_closed_on_missing_search():
    case = _public_case("S1-PUB-001")
    src = MOLEGLawDataSource(transport=_NoSearchTransport())
    res = run_case(case, law_source=src)
    # lookup 자체는 본문으로 해결되지만 검색은 0건 → 측정 불가로 닫혀야 한다.
    assert res.metrics["search_found"].startswith("0/")
    assert res.metrics["search_complete"] is False
    assert res.metrics["measured"] is False
    assert any(f.code == "NOT_REPRODUCIBLE" for f in res.failure_modes)
    assert res.total < 90
    # 측정 차원 0점화 확인 (검색 실패가 silent passthrough 되지 않음)
    assert res.metrics["recall"] == 0.0


# --- P2-B: pending headline 분리 (완료점수 vs 결정적 소계) ---------------- #
def test_slice1_pending_separates_completion_from_subtotal():
    report = run_slice(1)
    assert report.pending is True
    assert report.completion_score is None          # 완료점수 없음(보류)
    assert report.deterministic_subtotal >= 90      # 결정적 소계만 노출
    assert report.deterministic_subtotal == report.score
    for r in report.case_results:
        assert r.completion_score is None
        assert r.deterministic_subtotal == r.total
        dumped = r.model_dump(mode="json")
        assert dumped["completion_score"] is None
        assert dumped["deterministic_subtotal"] == r.total


# --- 정직성: high-risk 검토경고 누락 → MISSING_REVIEW_WARNING ------------ #
def test_harness_catches_missing_review_warning():
    # 빌더가 high-risk 인데 경고를 누락한 번들을 돌려주도록 패치 → 게이트 적발
    case = _public_case("S1-PUB-001")
    case_hr = case.model_copy(deep=True)
    case_hr.law_queries[0].high_risk = True

    real = build_law_source_answer

    def no_warning(**kwargs):
        bundle = real(**{**kwargs, "high_risk": False})  # 경고 강제 누락
        return bundle

    with mock.patch("tiw.eval.slices.slice1_law_anchor.build_law_source_answer", no_warning):
        res = run_case(case_hr)
    assert res.metrics["missing_review_warning"] is True
    assert any(f.code == "MISSING_REVIEW_WARNING" for f in res.failure_modes)


# --- anti-gaming: hidden/public 분리 로딩 + slice 필터 ------------------- #
def test_public_hidden_separate_and_slice_filtered():
    pub = load_public_cases(1)
    hid = load_hidden_cases(1)
    assert {c.case_id for c in pub} == {"S1-PUB-001", "S1-PUB-002"}
    assert {c.case_id for c in hid} == {"S1-HID-001"}
    assert all(c.slice == 1 for c in pub + hid)
