"""slice ③ 공식소스 Web run — 결정적 테스트 (실키/네트워크 불필요, fixture 재생).

핵심:
  - Tavily 어댑터 RECORD/REPLAY: 공식 도메인(include_domains) 발견 + SourceSnapshot 녹화.
  - Source Policy(WEB-002/003/004/007): 비공식(블로그·미러) 사전/사후 배제 — 결론 근거 0건.
  - Page Extraction → SourceSnapshot(발행기관·retrieved_at·content_hash, WEB-005).
  - 공식성 스코어링 + WEB-012: 최신성(freshness) ⟂ 적용시점 유효성(applicable_validity) 분리.
  - Promotion(WEB-011): 공식 원문만 법령 원문(채널 ①)과 대조→승격. 미승격→참고/동향.
  - 웹 단독 단정 금지(docs/06 §9): 승격 없으면 abstain.
  - SourceAnswer(WEB): slice① 생성기 재사용(source_type=WEB, 채널 ③) + 결정적 entailment.
  - 하버스 정직성(anti-gaming): 비공식 승격→FABRICATED, 날조 인용→FABRICATED, 시점불일치→
    TEMPORAL_ERROR, fixture 부재/해시불일치→NOT_REPRODUCIBLE 를 *동일 채점 경로*에서 적발.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

import pytest

from contract.base import SourceType
from contract.cluster_f_qa import Citation
from contract.cluster_i_eval import EvaluationCase
from src.ai.tavily_client import (
    DEFAULT_WEB_FIXTURES_DIR,
    OFFICIAL_DOMAINS,
    ReplayTavilyTransport,
    TavilyClient,
    TavilyRequest,
    TavilyResult,
    WebNotReproducible,
    WebSearchUnavailable,
    default_tavily_client,
    official_domain_of,
    registrable_domain,
)
from src.web_research import (
    PromotedSource,
    WebResearchPipeline,
    default_pipeline,
    plan_queries,
    snapshot_from_result,
)
from tiw.eval.loader import load_hidden_cases, load_public_cases
from tiw.eval.runner import run_slice
from tiw.eval.slices.slice3_web import run_case


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _case(case_id: str) -> EvaluationCase:
    for c in load_public_cases(3) + load_hidden_cases(3):
        if c.case_id == case_id:
            return c
    raise AssertionError(f"{case_id} not found")


def _result(*, url: str, content: str, title: str = "", official: bool = True,
            published: str | None = "2025-01-01", score: float = 0.9) -> TavilyResult:
    dom = official_domain_of(url)
    return TavilyResult(
        title=title or url, url=url, content=content, score=score,
        published_date=published, domain=dom or registrable_domain(url),
        official=dom is not None, content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def _blog_candidate() -> TavilyResult:
    return _result(
        url="https://blog.naver.com/taxguy/12345",
        title="접대비 한도 완벽정리 (개인 블로그)",
        content="법인세법 제25조 기업업무추진비 한도 정리. 블로그 요약본.",
        published="2025-06-01",
    )


# --------------------------------------------------------------------------- #
# Tavily 어댑터: 공식 도메인 정책 + RECORD/REPLAY 결정성
# --------------------------------------------------------------------------- #
def test_official_domain_policy():
    assert official_domain_of("https://www.nts.go.kr/x") == "nts.go.kr"
    assert official_domain_of("https://law.go.kr/LSW/lsInfoP.do?lsiSeq=1") == "law.go.kr"
    assert official_domain_of("https://www.moef.go.kr/a") == "moef.go.kr"
    assert official_domain_of("https://blog.naver.com/x") is None     # 비공식
    assert official_domain_of("https://taxguy.tistory.com/1") is None
    assert registrable_domain("https://txsi.hometax.go.kr/a") == "hometax.go.kr"
    assert set(OFFICIAL_DOMAINS) == {"nts.go.kr", "law.go.kr", "moef.go.kr", "tt.go.kr", "scourt.go.kr"}


def test_tavily_replay_deterministic():
    client = default_tavily_client()
    plan = plan_queries(law_name="법인세법", article_label="제25조",
                        as_of_date=date(2024, 1, 1), issue="기업업무추진비")
    r1 = client.search(plan.primary)
    r2 = client.search(plan.primary)
    assert r1.content_hash == r2.content_hash          # 결정적 (fixture 재생)
    assert r1.results and all(x.official for x in r1.results)   # 공식 도메인만
    assert r1.origin == "fixture"


def test_tavily_missing_fixture_fails_closed(tmp_path):
    client = TavilyClient(transport=ReplayTavilyTransport(tmp_path))   # 빈 fixtures
    with pytest.raises(WebSearchUnavailable):
        client.search("녹화되지 않은 임의 쿼리")


def test_tavily_fixture_hash_mismatch_fails_closed(tmp_path):
    req = TavilyRequest(query="q", max_results=8, include_domains=OFFICIAL_DOMAINS)
    (tmp_path / req.filename).write_text(json.dumps({"results": []}), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(
        json.dumps({req.key: {"file": req.filename, "content_hash": "DEADBEEF"}}),
        encoding="utf-8",
    )
    with pytest.raises(WebNotReproducible):     # 변조 스냅샷 재생 거부 (만점 아님)
        ReplayTavilyTransport(tmp_path).resolve(req)


def test_tavily_fixtures_no_known_secret_markers():
    # codex P2: .env 유무와 무관하게 fixture/manifest 전체에 알려진 secret 패턴이
    # 들어가지 않았는지 정적 검사 (CI 에 .env 가 없어도 누출을 잡는다).
    manifest_path = DEFAULT_WEB_FIXTURES_DIR / "manifest.json"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert json.loads(manifest_text), "web fixtures manifest 가 비어있다 (녹화 필요)"
    markers = ("tvly-", "Bearer ", "sk-ant-", "Authorization")
    blobs = [manifest_text] + [
        f.read_bytes().decode("utf-8", "replace")
        for f in DEFAULT_WEB_FIXTURES_DIR.glob("tavily_*.json")
    ]
    for blob in blobs:
        for marker in markers:
            assert marker not in blob, f"secret marker {marker!r} leaked into web fixtures"


def test_tavily_fixtures_carry_no_exact_key():
    # 추가: .env 가 있으면 실제 TAVILY_API_KEY 값 자체가 새지 않았는지 정확히 대조.
    # 키 값은 .env 에서 읽어 비교 — 테스트 파일에 키 하드코딩하지 않는다.
    from pathlib import Path

    manifest_path = DEFAULT_WEB_FIXTURES_DIR / "manifest.json"
    env = Path(__file__).resolve().parents[1] / ".env"
    key = None
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("TAVILY_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip() or None
                break
    if not key:
        pytest.skip(".env TAVILY_API_KEY 없음 — marker 검사는 별도 테스트가 수행")
    assert key not in manifest_path.read_text(encoding="utf-8")
    key_b = key.encode("utf-8")
    for f in DEFAULT_WEB_FIXTURES_DIR.glob("tavily_*.json"):
        assert key_b not in f.read_bytes()


# --------------------------------------------------------------------------- #
# Source Policy: 공식 우선 + 비공식 배제 (WEB-002/003/004/007)
# --------------------------------------------------------------------------- #
def test_snapshot_provenance_from_result():
    r = _result(url="https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=1",
                content="제25조(기업업무추진비) 본문", published="2024-03-01")
    snap = snapshot_from_result(r, idx=0, retrieved_at="2026-06-29T00:00:00+00:00")
    assert snap.official and snap.publisher == "법제처 국가법령정보센터"
    assert snap.content_hash and len(snap.content_hash) == 64        # WEB-005
    assert snap.published_date == date(2024, 3, 1)
    assert snap.url.startswith("https://www.law.go.kr")


def test_pipeline_excludes_blog_injection():
    # 사후 정책(WEB-007): 검색이 블로그를 끼워 넣어도 공식만 승격되고 블로그는 결론 근거 0.
    # 생성 fixture 재생을 위해 gold 질문/ID 재사용(블로그 주입은 gen 프롬프트에 영향 없음).
    case = _case("S3-PUB-001")
    q = case.web_queries[0]
    pipe = default_pipeline()
    web = pipe.run(
        question_text=q.question_text, law_name=q.law_name, article_label=q.article_label,
        as_of_date=q.as_of_date, issue=q.issue,
        source_answer_id=f"sa_{case.case_id}_{q.query_id}",
        answer_run_id=f"ar_{case.case_id}_{q.query_id}",
        extra_candidates=[_blog_candidate()],
    )
    assert web.promoted is not None
    assert official_domain_of(web.promoted.snapshot.url) is not None     # 공식만 승격
    blog_ids = {c.snapshot.snapshot_id for c in web.scored_candidates
                if c.officiality == 0}
    cited_ids = {c.source_object_id for c in web.citations}
    assert blog_ids and not (blog_ids & cited_ids)                       # 블로그 인용 0건
    blog_cand = next(c for c in web.scored_candidates if c.officiality == 0)
    assert blog_cand.promotable is False                                 # 비공식 미승격


def test_harness_blog_injection_still_passes_no_gate():
    # 동일 채점 경로에 블로그를 주입해도 공식만 승격→하드게이트 0, 비공식 승격 False.
    res = run_case(_case("S3-PUB-001"), inject_candidates=[_blog_candidate()])
    assert res.metrics["source_policy_unofficial_promoted"] is False
    assert not res.hard_gate_hit
    assert res.total >= 90


def test_promotion_requires_real_provision_overlap():
    # WEB-011(codex P0): 공식 도메인이라도 법령 원문과 실질 본문 일치(verbatim 최장 공유)가
    # 임계 미만이면 승격 불가 — 토큰 존재만으로는 안 됨. 안내성 공식 페이지(법령명만 언급)는
    # 미승격, 실제 조문 본문을 담은 페이지만 승격.
    nav_only = _result(
        url="https://www.law.go.kr/LSW/menu/nav.do",
        title="법인세법 — 국가법령정보센터",
        content="법인세법 제25조 관련 안내. 국가법령정보센터 메뉴. 법령·행정규칙·자치법규 검색.",
    )
    pipe = default_pipeline()
    scored, lookup = pipe.gather(
        law_name="법인세법", article_label="제25조", as_of_date=date(2024, 1, 1),
        issue="기업업무추진비", extra_candidates=[nav_only],
    )
    nav = next(c for c in scored if "menu/nav" in c.result.url)
    assert nav.officiality == 1.0                       # 공식 도메인
    assert nav.corroboration_len < 40                   # 실질 본문 일치 거의 없음
    assert nav.authority_corroborated is False          # 원문 대조 실패
    assert nav.promotable is False                      # 토큰만으론 미승격
    # 실제 조문 본문을 담은 후보는 큰 공유 길이로 승격
    promoted = pipe.promote(scored, lookup)
    assert promoted is not None and promoted.candidate.corroboration_len >= 40


def test_web_citation_quote_comes_from_official_content():
    # codex P0-2: web 인용 quote 는 스냅샷(공식 웹) 원문에서 발췌 — 동시에 법령 원문(①)과도
    # 일치(verbatim 공유). pv.text 에서만 잘라온 게 아님.
    import re
    case = _case("S3-PUB-001")
    q = case.web_queries[0]
    web = default_pipeline().run(
        question_text=q.question_text, law_name=q.law_name, article_label=q.article_label,
        as_of_date=q.as_of_date, issue=q.issue,
        source_answer_id=f"sa_{case.case_id}_{q.query_id}",
        answer_run_id=f"ar_{case.case_id}_{q.query_id}",
    )
    def n(s): return re.sub(r"\s+", " ", s or "")
    quote = n((web.web_citation.quote or "").rstrip("…").strip())
    assert quote
    assert quote in n(web.promoted.official_content)        # 웹 출처가 실제로 담음
    assert quote in n(web.promoted.provision_version.text)  # 법령 원문과 일치(대조)


# --------------------------------------------------------------------------- #
# WEB-012: 최신성 ⟂ 적용시점 유효성 분리 (fresh-but-stale 함정)
# --------------------------------------------------------------------------- #
def test_web012_freshness_separated_from_applicable_validity():
    # 공식(law.go.kr)이지만 *구 버전*(접대비)을 기술하는 최신(2025) 후보:
    # 최신성 高, 적용시점 유효성 0 (2024 기준 권위 버전은 '기업업무추진비'). 분리 저장 확인.
    stale_fresh = _result(
        url="https://www.law.go.kr/old/jeobdaebi",
        title="법인세법 제25조(접대비)",
        content="제25조(접대비의 손금불산입) ① 내국법인이 지출한 접대비로서 한도를 초과하는 금액은 손금불산입한다.",
        published="2025-12-01",
    )
    pipe = default_pipeline()
    scored, lookup = pipe.gather(
        law_name="법인세법", article_label="제25조", as_of_date=date(2024, 1, 1),
        issue="기업업무추진비", extra_candidates=[stale_fresh],
    )
    cand = next(c for c in scored if "old/jeobdaebi" in c.result.url)
    assert cand.freshness > 0.9                       # 최신성 高
    assert cand.applicable_validity == 0.0            # 적용시점 유효성 0 (구 버전)
    assert cand.promotable is False                   # 최신이어도 시점 불일치→미승격
    # 분리 저장: 두 점수가 독립(같지 않음)
    assert cand.freshness != cand.applicable_validity


def test_harness_records_web012_separated_scores():
    res = run_case(_case("S3-PUB-001"))
    assert res.metrics["web012_scores_separated"] is True
    assert "freshness_scores" in res.metrics and "applicable_validity_scores" in res.metrics
    # 분리 기록: 두 리스트가 독립적으로 존재
    assert len(res.metrics["freshness_scores"]) == len(res.metrics["applicable_validity_scores"])


# --------------------------------------------------------------------------- #
# Promotion(WEB-011) + 웹 단독 단정 금지 (docs/06 §9)
# --------------------------------------------------------------------------- #
def test_web_alone_abstains_when_no_official_source():
    # 공식 후보가 0이면(블로그만) 승격 불가 → abstain (웹 단독 세무 단정 금지).
    class _BlogOnlyTavily:
        def search(self, query, max_results=None, include_domains=None):
            from src.ai.tavily_client import TavilyResponse
            return TavilyResponse(query=query, results=[_blog_candidate()],
                                  origin="fixture", content_hash="x", retrieved_at=None)

    from src.ai.law_data_source import default_law_source
    pipe = WebResearchPipeline(tavily=_BlogOnlyTavily(), law_source=default_law_source())
    web = pipe.run(
        question_text="q", law_name="법인세법", article_label="제25조",
        as_of_date=date(2024, 1, 1), issue="기업업무추진비",
        source_answer_id="sa", answer_run_id="ar",
    )
    assert web.abstained is True and web.promoted is None
    assert web.research is None and web.web_citation is None       # 결론 근거 없음
    assert "웹 단독 단정 금지" in web.answer_text


def test_harness_unofficial_promotion_trips_fabricated():
    # 적대: 비공식 소스를 권위로 '승격'하는 깨진 파이프라인 → 동일 채점 경로에서
    # FABRICATED_CITATION(cap 60)로 적발 (날조 권위).
    class _UnofficialPromotePipeline(WebResearchPipeline):
        def promote(self, scored, auth_lookup):
            blog = next((c for c in scored if c.officiality == 0), None)
            if blog is None:
                return None
            return PromotedSource(candidate=blog, snapshot=blog.snapshot,
                                  official_content=blog.result.content, lookup=auth_lookup)

    res = run_case(_case("S3-PUB-001"),
                   pipeline_factory=lambda: _UnofficialPromotePipeline(),
                   inject_candidates=[_blog_candidate()])
    assert res.metrics["source_policy_unofficial_promoted"] is True
    assert any(f.code == "FABRICATED_CITATION" for f in res.failure_modes)
    assert res.total <= 60


def test_harness_web_alone_conclusion_trips_gate():
    # 적대: 승격 없이도 결론을 내야 하는데(expect_promote=False) 파이프라인이 abstain 하지
    # 않고 결론을 내면 web 단독 단정으로 적발.
    case = _case("S3-PUB-001").model_copy(deep=True)
    case.web_queries[0].expect_promote = False     # "승격 없이 결론 금지" 시나리오
    res = run_case(case)                            # 기본 파이프라인은 승격→결론 생성
    assert res.metrics["web_alone_conclusion"] is True
    assert any(f.code == "FABRICATED_CITATION" for f in res.failure_modes)


# --------------------------------------------------------------------------- #
# 하버스 end-to-end (slice ③) — judge 채점 + ≥90
# --------------------------------------------------------------------------- #
def test_slice3_harness_passes_gate():
    report = run_slice(3)
    assert report.case_results
    assert report.hidden_count >= 1 and report.public_count >= 1
    assert not report.hard_gate_hit
    assert report.pending is False
    assert report.passed is True
    assert report.score >= 90
    for r in report.case_results:
        assert r.metrics["recall"] == 1.0
        assert r.metrics["promoted"].split("/")[0] == r.metrics["promoted"].split("/")[1]
        assert r.metrics["reproducible"] is True
        assert r.metrics["judge_scored"] is True
        assert r.metrics["entailment"] == "2/2"
        assert r.metrics["web_provenance"].split("/")[0] == r.metrics["web_provenance"].split("/")[1]
        assert r.metrics["temporal_error"] is False
        assert r.metrics["source_policy_unofficial_promoted"] is False
        scored = {s.dimension for s in r.dimension_scores if s.applicable and s.score is not None}
        assert {"legal_reasoning", "issue_spotting", "risk", "output", "search", "citation"} <= scored


def test_slice3_completion_score_present_when_scored():
    report = run_slice(3)
    assert report.pending is False
    assert report.completion_score == report.score
    for r in report.case_results:
        assert r.completion_score == r.total


def test_answer_channel_is_web():
    case = _case("S3-PUB-001")
    q = case.web_queries[0]
    web = default_pipeline().run(
        question_text=q.question_text, law_name=q.law_name, article_label=q.article_label,
        as_of_date=q.as_of_date, issue=q.issue, source_answer_id=f"sa_{case.case_id}_{q.query_id}",
        answer_run_id=f"ar_{case.case_id}_{q.query_id}",
    )
    assert web.research is not None
    assert web.research.source_answer.source_type is SourceType.WEB     # 채널 ③ 표기
    assert "채널 ③" in web.answer_text
    assert web.promoted.snapshot.official is True


# --------------------------------------------------------------------------- #
# 정직성: 날조 인용 → FABRICATED_CITATION (cap 60)
# --------------------------------------------------------------------------- #
def test_harness_catches_fabricated_citation():
    def tamper(cit: Citation) -> Citation:
        return cit.model_copy(update={"source_object_id": "pv_날조_제000조_19000101"})

    res = run_case(_case("S3-PUB-001"), citation_tamper=tamper)
    assert res.metrics["fabricated_citation"] is True
    assert any(f.code == "FABRICATED_CITATION" for f in res.failure_modes)
    assert res.total <= 60


def test_harness_catches_web_provenance_tamper():
    # web 인용 발췌를 회수/법령 원문에 없는 문구로 변조 → web-provenance 대조 실패 →
    # FABRICATED (회수 밖 날조). source_object_id 는 그대로라 레지스트리 존재검증은 통과.
    def tamper(cit: Citation) -> Citation:
        if cit.source_kind.value == "SourceSnapshot":
            return cit.model_copy(update={"quote": "법령 원문에 존재하지 않는 날조 인용 ZZZ"})
        return cit

    res = run_case(_case("S3-PUB-001"), citation_tamper=tamper)
    assert res.metrics["web_provenance"].startswith("0/")
    assert res.metrics["fabricated_citation"] is True
    assert any(f.code == "FABRICATED_CITATION" for f in res.failure_modes)
    assert res.total <= 60


# --------------------------------------------------------------------------- #
# 정직성: 시행일/버전 불일치 → TEMPORAL_ERROR (cap 55)
# --------------------------------------------------------------------------- #
def test_harness_catches_temporal_mismatch():
    case = _case("S3-PUB-001").model_copy(deep=True)
    case.web_queries[0].gold_law.expected_effective_from = date(2020, 1, 1)
    res = run_case(case)
    assert res.metrics["temporal_error"] is True
    assert any(f.code == "TEMPORAL_ERROR" for f in res.failure_modes)
    assert res.total <= 55


# --------------------------------------------------------------------------- #
# fail-closed: tavily/judge fixture 부재 → NOT_REPRODUCIBLE (만점 아님)
# --------------------------------------------------------------------------- #
def test_harness_fail_closed_on_missing_tavily(tmp_path):
    from src.ai.law_data_source import default_law_source

    def factory():
        return WebResearchPipeline(
            tavily=TavilyClient(transport=ReplayTavilyTransport(tmp_path)),
            law_source=default_law_source(),
        )

    res = run_case(_case("S3-PUB-001"), pipeline_factory=factory)
    assert res.metrics["measured"] is False
    assert any(f.code == "NOT_REPRODUCIBLE" for f in res.failure_modes)
    assert res.total < 90


class _MissingFixtureJudge:
    def score(self, **kwargs):
        from src.ai.llm_client import LLMUnavailable
        raise LLMUnavailable("no recorded judge fixture (test)")


def test_harness_fail_closed_on_missing_judge_fixture():
    res = run_case(_case("S3-PUB-001"), judge=_MissingFixtureJudge())
    assert res.metrics["measured"] is False
    assert res.metrics["judge_scored"] is False
    assert any(f.code == "NOT_REPRODUCIBLE" for f in res.failure_modes)
    assert res.total < 90


def test_slice3_judge_fail_closed_when_unavailable(tmp_path):
    # 생성 LLM fixture 가 없으면 pipeline.run 이 LLMUnavailable → 케이스 측정 불가.
    from src.ai.llm_client import LLMClient, LLMConfig, ReplayLLMTransport

    empty = LLMClient(config=LLMConfig.from_vendors(), transport=ReplayLLMTransport(tmp_path))
    res = run_case(_case("S3-PUB-001"), llm_client=empty)
    assert res.metrics["measured"] is False
    assert res.metrics["judge_scored"] is False
    assert any(f.code == "NOT_REPRODUCIBLE" for f in res.failure_modes)


# --------------------------------------------------------------------------- #
# 정직성: 비지지 entailment → FABRICATED_CITATION
# --------------------------------------------------------------------------- #
class _UnsupportedJudge:
    def score(self, **kwargs):
        from src.judge import EntailmentCheck, JudgeVerdict
        return JudgeVerdict(
            fractions={"legal_reasoning": 1.0, "issue_spotting": 1.0, "risk": 1.0, "output": 1.0},
            entailments=[EntailmentCheck(claim="c", supported=False, rationale="비지지")],
        )


def test_harness_unsupported_entailment_trips_fabricated_gate():
    res = run_case(_case("S3-PUB-001"), judge=_UnsupportedJudge())
    assert res.metrics["fabricated_citation"] is True
    assert any(f.code == "FABRICATED_CITATION" for f in res.failure_modes)
    assert res.total <= 60


# --------------------------------------------------------------------------- #
# high-risk: hidden 케이스는 고위험(검토경고 필수)
# --------------------------------------------------------------------------- #
def test_hidden_case_high_risk_and_carries_warning():
    hid = _case("S3-HID-001")
    assert hid.web_queries[0].high_risk is True
    res = run_case(hid)
    assert res.metrics["missing_review_warning"] is False
    assert not any(f.code == "MISSING_REVIEW_WARNING" for f in res.failure_modes)


# --------------------------------------------------------------------------- #
# anti-gaming: public/hidden 분리 + 서로 다른 조문(overfit 방지)
# --------------------------------------------------------------------------- #
def test_public_hidden_separate_and_distinct_articles():
    pub = load_public_cases(3)
    hid = load_hidden_cases(3)
    assert {c.case_id for c in pub} == {"S3-PUB-001", "S3-PUB-002"}
    assert {c.case_id for c in hid} == {"S3-HID-001"}
    pub_articles = {q.gold_law.article_label for c in pub for q in c.web_queries}
    hid_articles = {q.gold_law.article_label for c in hid for q in c.web_queries}
    assert hid_articles and not (hid_articles & pub_articles)     # 숨김셋 ≠ 공개셋 조문
    for c in pub + hid:
        for q in c.web_queries:
            assert len(q.gold_issues) >= 4
            assert q.gold_official_domains                       # 공식 도메인 recall 목표 존재
