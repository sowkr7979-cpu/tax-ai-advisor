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
def test_slice1_harness_judge_scored_and_passes():
    # judge 연결 후: 판단 차원(법리20/쟁점10/리스크11/산출9) + citation entailment 가
    # 채점되어 슬라이스가 완료(≥90)된다. fixture 재생(네트워크/키 0).
    report = run_slice(1)
    assert report.case_results
    assert report.hidden_count >= 1 and report.public_count >= 1
    assert not report.hard_gate_hit
    assert report.pending is False           # 더 이상 보류 아님 — 판단 차원 채점됨
    assert report.passed is True
    assert report.score >= 90
    assert report.completion_score == report.score
    for r in report.case_results:
        assert r.metrics["recall"] == 1.0
        assert r.metrics["reproducible"] is True
        assert r.metrics["judge_scored"] is True
        assert r.metrics["entailment"] == "2/2"      # 인용 2건(앵커+결론) 모두 결정적 지지
        # 4개 판단 차원이 실제 점수를 가진다(보류 아님, 만점 강제도 아님)
        scored = {s.dimension for s in r.dimension_scores if s.applicable and s.score is not None}
        assert {"legal_reasoning", "issue_spotting", "risk", "output"} <= scored


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


# --- P2-B: 완료점수 = headline (judge 채점 후 보류 해제) ------------------ #
def test_slice1_completion_score_present_when_scored():
    report = run_slice(1)
    assert report.pending is False
    assert report.completion_score == report.score   # 완료점수 = 결정적 소계 = headline
    assert report.deterministic_subtotal == report.score
    for r in report.case_results:
        assert r.completion_score == r.total
        dumped = r.model_dump(mode="json")
        assert dumped["completion_score"] == r.total
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


# --- LLM fixture 무결성: 변조(해시 불일치) → fail-closed ------------------ #
def test_llm_fixture_hash_mismatch_fails_closed(tmp_path):
    import json as _json

    from src.ai.llm_client import LLMNotReproducible, LLMRequest, ReplayLLMTransport

    req = LLMRequest(model="claude-opus-4-8", max_tokens=10, system="s", user="u", tag="t")
    payload = {"text": "x", "model": "claude-opus-4-8",
               "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1}}
    (tmp_path / req.filename).write_text(
        _json.dumps({"response": payload, "content_hash": "DEADBEEF"}), encoding="utf-8"
    )
    (tmp_path / "manifest.json").write_text(
        _json.dumps({req.key: {"file": req.filename}}), encoding="utf-8"
    )
    with pytest.raises(LLMNotReproducible):     # 변조 스냅샷 재생 거부(만점 아님)
        ReplayLLMTransport(tmp_path).complete(req)


# --- judge fail-closed: 키/fixture 없으면 보류(만점 금지) ----------------- #
def test_slice1_judge_fail_closed_when_unavailable(tmp_path):
    # LLM fixture 가 없으면(녹화 안 됨/키 없음) 생성·judge 가 가동되지 않는다 →
    # 판단 차원은 보류(PENDING), 슬라이스는 완료가 아니다(절대 만점 처리 금지).
    from src.ai.llm_client import LLMClient, LLMConfig, ReplayLLMTransport

    empty = LLMClient(config=LLMConfig.from_vendors(), transport=ReplayLLMTransport(tmp_path))
    case = _public_case("S1-PUB-001")
    res = run_case(case, llm_client=empty)          # 빈 fixtures → 생성 LLMUnavailable
    assert res.metrics["judge_scored"] is False
    assert res.metrics["entailment"] == "PENDING_JUDGE"
    assert res.has_pending and "legal_reasoning" in res.pending_dimensions
    assert res.completion_score is None             # 완료점수 없음(보류)
    # 결정적 부분은 측정되지만(재현 가능) judge 미가동이라 미완료.
    assert res.metrics["reproducible"] is True


# --- entailment 거부: 비지지 인용 → FABRICATED_CITATION(HALU-003, cap60) -- #
class _UnsupportedJudge:
    """답변 품질은 만점이라 주장하되 인용 entailment 를 '비지지'로 판정하는 적대 judge."""

    def score(self, **kwargs):
        from src.judge import EntailmentCheck, JudgeVerdict

        return JudgeVerdict(
            fractions={"legal_reasoning": 1.0, "issue_spotting": 1.0, "risk": 1.0, "output": 1.0},
            entailments=[EntailmentCheck(claim="법리 결론", supported=False, rationale="발췌 비지지")],
        )


def test_slice1_unsupported_entailment_trips_fabricated_gate():
    # 생성은 정상 재생되되 judge 가 인용 비지지를 판정하면, 동일 채점 경로에서
    # 인용이 거부되고 FABRICATED_CITATION(cap60) 게이트가 떠야 한다(점수 부풀림 차단).
    case = _public_case("S1-PUB-001")
    res = run_case(case, judge=_UnsupportedJudge())
    assert res.metrics["fabricated_citation"] is True
    assert any(f.code == "FABRICATED_CITATION" for f in res.failure_modes)
    assert res.total <= 60                           # 판단 차원 만점이라도 cap60


# --- anti-gaming: issue_spotting 은 독립 gold 쟁점으로 채점(자기채점 아님) - #
def test_issue_spotting_scored_against_independent_gold():
    # gold 기대쟁점은 모든 slice① 케이스에 존재하고(법령/사실관계에서 독립 도출),
    # judge 프롬프트에 명시적으로 주입된다 → 생성된 답변의 self-issue 가 아니라
    # 독립 gold 로 채점된다.
    for c in load_public_cases(1) + load_hidden_cases(1):
        assert len(c.law_queries[0].gold_issues) >= 4

    from src.judge import build_judge_prompt
    from src.legal_research import generate_research_answer

    case = _public_case("S1-PUB-001")
    q = case.law_queries[0]
    src = default_law_source()
    lookup = src.lookup_provision(q.law_name, q.article_label, q.as_of_date)
    answer = generate_research_answer(           # 기본 replay 클라이언트(키 0)
        lookup=lookup, question_text=q.question_text, client_id="c",
        answer_run_id="ar", source_answer_id="sa_S1-PUB-001_S1-PUB-001-q1",
        high_risk=False,
    )
    system, user = build_judge_prompt(
        question_text=q.question_text, answer=answer,
        provision_quote=lookup.provision_version.text, gold_issues=list(q.gold_issues),
    )
    # 독립 gold 쟁점이 채점 기준으로 프롬프트에 주입됨
    assert q.gold_issues[0] in user
    assert "issue_spotting" in system
    # gold 는 답변과 별개의 객체(독립): 케이스 JSON 에서 로드된 gold 가 그대로 쓰인다.
    assert q.gold_issues == _public_case("S1-PUB-001").law_queries[0].gold_issues


# --- P1-1: entailment 는 결정적으로 검증된다(judge bool 맹신 아님) ----------- #
def test_deterministic_entailment_catches_unsupported_citation():
    # verify_entailment 는 LLM 없이 규칙 매칭만으로 '조문↔주장' 지지를 판정한다.
    from src.judge import verify_entailment

    src = default_law_source()
    pv2024 = src.lookup_provision("법인세법", "제25조", date(2024, 1, 1)).provision_version
    text = pv2024.text                       # 2024 버전: 제목 핵심어 '기업업무추진비'
    grounded = text[:120]                     # 본문 prefix = verbatim 발췌(지지)

    # 지지: claim 이 조문(제25조)·제목 핵심어(기업업무추진비)를 진술 + 발췌가 본문 부분문자열
    ok = verify_entailment("법인세법 제25조(기업업무추진비의 손금불산입)에 근거한다.", grounded, text)
    assert ok.supported is True and ok.deterministic is True

    # 미지지 C3(세목/버전 불일치): '접대비'만 진술하고 본 버전 핵심어 '기업업무추진비' 누락
    bad_subject = verify_entailment("법인세법 제25조의 2020 접대비 손금불산입 근거다.", grounded, text)
    assert bad_subject.supported is False and bad_subject.deterministic is False
    assert "기업업무추진비" in bad_subject.rationale

    # 미지지 C2(조문 참조 날조): 본문에 없는 제999조를 인용
    bad_article = verify_entailment("법인세법 제999조 기업업무추진비 가공 조문이다.", grounded, text)
    assert bad_article.supported is False

    # 미지지 C1(발췌 비근거): 본문에 없는 문장을 발췌로 제시
    bad_quote = verify_entailment("법인세법 제25조(기업업무추진비의 손금불산입)", "본문에 없는 가짜 발췌문", text)
    assert bad_quote.supported is False


def test_judge_deterministic_overrides_generous_self_report():
    # judge 가 '지지(true)'로 자가보고해도, 결정적 검증이 미지지면 최종 entailment 는
    # 미지지여야 한다(보조 self-report 가 결정적 결과를 상향조정하지 못함).
    from src.ai.llm_client import LLMResponse
    from src.judge import Judge
    from src.legal_research import generate_research_answer

    case = _public_case("S1-PUB-001")
    q = case.law_queries[0]
    src = default_law_source()
    lookup = src.lookup_provision(q.law_name, q.article_label, q.as_of_date)
    answer = generate_research_answer(
        lookup=lookup, question_text=q.question_text, client_id="c",
        answer_run_id="ar", source_answer_id="sa_S1-PUB-001_S1-PUB-001-q1",
        high_risk=False,
    )
    # 결론 claim 을 변조: 조문 제목 핵심어(기업업무추진비) 누락 → 결정적 미지지 유도
    answer.conclusion_claim = answer.conclusion_claim.model_copy(
        update={"proposition": "법인세법 제25조 관련 일반 결론(세목 명칭 누락)."}
    )

    class _GenerousJudge:
        """모든 인용을 supported=true 로 자가보고하는 관대한 judge(자기채점)."""

        def complete(self, *, system, user, tag, max_tokens=None):
            text = (
                '{"scores":{"legal_reasoning":100,"issue_spotting":100,"risk":100,"output":100},'
                '"entailment":[{"claim":"a","supported":true},{"claim":"b","supported":true}],'
                '"missed_issues":[],"unsupported_claims":[],"rationale":"all good"}'
            )
            return LLMResponse(text=text, model="fake", input_tokens=1, output_tokens=1,
                               stop_reason="end_turn", origin="fixture")

    verdict = Judge(_GenerousJudge()).score(
        question_text=q.question_text, answer=answer,
        provision_quote=lookup.provision_version.text,
        gold_issues=list(q.gold_issues), tag="t",
    )
    assert verdict.all_supported is False                  # 결정적 미지지가 최종을 지배
    assert any(e.deterministic is False for e in verdict.entailments)
    assert all(e.judge_supported for e in verdict.entailments)  # judge 자가보고는 관대했음


# --- P1-2: judge 점수 버킷 엄격화(범위 밖/오프버킷 → fail-closed) ----------- #
def test_judge_rejects_off_bucket_and_out_of_range_scores():
    from src.ai.llm_client import LLMResponse
    from src.judge import Judge, JudgeError
    from src.legal_research import generate_research_answer

    case = _public_case("S1-PUB-001")
    q = case.law_queries[0]
    src = default_law_source()
    lookup = src.lookup_provision(q.law_name, q.article_label, q.as_of_date)
    answer = generate_research_answer(
        lookup=lookup, question_text=q.question_text, client_id="c",
        answer_run_id="ar", source_answer_id="sa_S1-PUB-001_S1-PUB-001-q1",
        high_risk=False,
    )

    def _judge_with_score(lr_score):
        class _C:
            def complete(self, *, system, user, tag, max_tokens=None):
                text = (
                    '{"scores":{"legal_reasoning":%s,"issue_spotting":100,"risk":100,"output":100},'
                    '"entailment":[{"claim":"a","supported":true}],'
                    '"missed_issues":[],"unsupported_claims":[],"rationale":"r"}' % lr_score
                )
                return LLMResponse(text=text, model="fake", input_tokens=1, output_tokens=1,
                                   stop_reason="end_turn", origin="fixture")
        return Judge(_C())

    # 범위 밖(101)·오프버킷(88) 모두 보정 없이 JudgeError(만점 스냅 금지)
    for bad in ("101", "88"):
        with pytest.raises(JudgeError):
            _judge_with_score(bad).score(
                question_text=q.question_text, answer=answer,
                provision_quote=lookup.provision_version.text,
                gold_issues=list(q.gold_issues), tag="t",
            )
    # 정확한 버킷(75)은 정상 채점
    v = _judge_with_score("75").score(
        question_text=q.question_text, answer=answer,
        provision_quote=lookup.provision_version.text,
        gold_issues=list(q.gold_issues), tag="t",
    )
    assert v.fractions["legal_reasoning"] == 0.75


def test_slice1_off_bucket_judge_leaves_dimension_pending():
    # 범위 밖 judge 출력 → JudgeError → 해당 쿼리 judge 미채점 → 차원 보류(만점 아님).
    from src.ai.llm_client import LLMResponse
    from src.judge import Judge

    class _OffBucketJudge(Judge):
        def __init__(self):
            pass

        def score(self, **kwargs):
            from src.judge import JudgeError
            raise JudgeError("off-bucket score 88 (test)")

    case = _public_case("S1-PUB-001")
    res = run_case(case, judge=_OffBucketJudge())
    assert res.metrics["judge_scored"] is False
    assert res.has_pending and "legal_reasoning" in res.pending_dimensions
    assert res.completion_score is None             # 보류 → 완료점수 없음


# --- P2-2: L3/L4 기밀 컨텍스트는 외부 LLM 송신 전에 차단된다 ---------------- #
def test_generate_blocks_l3_l4_before_any_llm_send(tmp_path):
    from contract.base import ConfidentialityLevel
    from src.ai.llm_client import LLMClient, LLMConfig, ReplayLLMTransport
    from src.legal_research import ConfidentialitySendError, generate_research_answer

    src = default_law_source()
    lookup = src.lookup_provision("법인세법", "제25조", date(2024, 1, 1))
    # 빈 fixtures 클라이언트: guard 가 없다면 송신 시 LLMUnavailable 이 났을 것.
    empty = LLMClient(config=LLMConfig.from_vendors(), transport=ReplayLLMTransport(tmp_path))

    for lvl in (ConfidentialityLevel.L3_CLIENT, ConfidentialityLevel.L4_RESTRICTED):
        with pytest.raises(ConfidentialitySendError):
            generate_research_answer(
                lookup=lookup, question_text="q", client_id="c",
                answer_run_id="ar", source_answer_id="sa",
                confidentiality_level=lvl, llm_client=empty,
            )
    # 기본값(L0 공개법령)은 기밀 guard 를 통과한다(차단 대상 아님).
    assert ConfidentialityLevel.L0_PUBLIC.is_client_scoped is False
