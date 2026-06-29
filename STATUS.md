# TIW Ralph Loop — STATUS (진행 원장)

> 매 iteration 시작 시 이 파일 + `git log --oneline -15`를 먼저 읽는다. (PROMPT.md §3.1)
> 점수는 **STATUS 자기보고가 아니라** 같은 iteration의 `pytest -q` + `python -m tiw.eval` 산출 `RubricResult`로만 증명된다(완료 판정 기준).

## Iteration 0 게이트 — Rubric Freeze ✅ 완료
- **Rubric Freeze v1.0** @ `470e47c` (사용자(회계사)+AI 공동검토 확정).
- 완료 게이트: 6 vertical slice **각 ≥90/100** + 하드게이트 위반 0.
- 가중치(합100): 요구6·검색9·인용12·**법리20**·쟁점10·충돌7·리스크11·산출9·**보안14**·운영2.
- 하드게이트 캡: 누수0·무권한/전직장0·날조60·시점오류55·검토경고누락60·재현불가75.
- 평가셋: hidden freeze 50% / public practice 50%(rotate) · 인간 CPA 앵커 20%.

## 현재 단계
**전체 완료 + 라이브 엔드투엔드 앱 구동** — 6/6 vertical slice PASS + 프론트 목업 3화면 Playwright 렌더 통과 + DOCX Draft(11목차) + **오케스트레이터/CLI(`python -m tiw run`)로 "새 질문 → 검토패키지 DOCX"가 한 명령으로 구동**(라이브 1회 실행으로 실제 DOCX 산출 + replay 결정성 증명). PROMPT.md 완료조건 전부 충족. **pytest 206 passed**(203 + 오케스트레이터 8 − 중복 정정; 실측 206).

### ★ 라이브 엔드투엔드 오케스트레이터 + CLI (이번 빌드 — 6 슬라이스 chaining)
- **Strategy Agent(`src/strategy.py`)**: 종합의견+리스크+회수 조문 → 보수/중립/적극 3종 선택지(§3-5). 인용은 **회수된 버전객체에 한정**(`registry.require_citation` 선행, LLM이 id 주조 불가) · 적극 가드레일/검토경고 fail-closed 복구 · grounding 결정적 재검증(`verify_entailment`, self-report 비신뢰).
- **오케스트레이터(`src/orchestrator.py`)**: §4-1 흐름 Intake→쟁점도출(TB→조문)→**3소스 Research**(①`legal_research`·②`internal_rag`(Chroma 테넌트격리·L3 외부LLM 미송신)·③`web_research`(공식소스 승격))→**Synthesis**(ConflictResolution)→Risk→**Strategy**→Evidence→**Draft 11목차 DOCX**. `live`/`replay` 토글. ①②③ 동일 gen 프롬프트를 `_MemoLLMClient`로 단일화 → 라이브=replay 결정성.
- **CLI(`tiw/cli.py`+`tiw/__main__.py`)**: `python -m tiw run [--live|--replay] [--internal|--client] [--approve-demo] --company … --question … --out …`. `python -m tiw.eval` 독립 보존.
- **데모(`tests/fixtures/company/A제조_2026.json`)**: 제조업 법인(TB 4계정·전기신고·자료 수집/없음/모름/결손·L3 사내메모).
- **검증**: pytest 206 · 슬라이스 회귀 0(①90.5②97.3③96.8④93.5⑤92.3⑥100) · replay 결정성(라이브=replay doc.xml 내용 동일, sha `a79e46`) · 신규 fixture secret 0 · **L3 메모 외부 LLM 송신 0(독립 스캔 확인)**.
- **codex 독립 리뷰(P0×3 + P1×3 전부 반영)**: **P0-1** `validate_draft_package`가 `_render`에서만 호출 → write_docx=False 우회 → **assemble 직후 무조건 호출**(OUT-003 항상 강제). **P0-2/3** `_run_internal_rag`/`_run_web`의 broad `except Exception`이 replay fixture·격리·인용 실패를 silent degrade로 은폐 → **replay 모드는 무조건 전파(fail-closed) + `_NEVER_SWALLOW`(IsolationError/CitationVerificationError/TenantBoundaryError)는 모든 모드 미삼킴**, live 운영성 실패만 degrade. **P1-1** web SILENT contribution `client_id="client_eval"` 하드코딩 → `company.client_id`(테넌트 일관). **P1-2** `_unresolved_conflicts` 무조건 하드코딩 충돌 주입 → **주쟁점이 실제 기업업무추진비일 때만 승격**(쟁점 범위 밖 무관 충돌 주입 차단). **P1-3** private `wf._build_release_proof` 직접 호출(감사 우회) → 공개 `wf.produce_client_deliverable`(교차테넌트 차단+미승인 재검증+`record_release` 의무감사) 경유 후 proof 반환. codex 종합: 인용 날조/grounding/L3 격리/HITL fail-closed **불변식 유지 확인**. 회귀테스트 3건(`test_out003_validation_runs_even_without_docx`·`test_replay_failclosed_on_isolation_error`·`test_replay_failclosed_on_fixture_failure`).

## 6 Vertical Slice 점수표 (RubricResult 기준 — 이번 iteration `python -m tiw.eval` 산출)
| # | Slice | 점수 | 하드게이트 | 상태 |
|---|---|---:|---|---|
| ⑥ | 테넌트 격리 | **100** (min over 4 cases) | 누수0 (TENANT_LEAK 미발생) | **통과 (≥90)** |
| ① | 법령MCP 앵커 답변 | **90.5** (min: PUB-001=100·PUB-002=96.8·HID-001=90.5) | 0 (TEMPORAL/FABRICATED/NOT_REPRO/MISSING_WARNING 미발생) | **통과 (≥90)** — judge 연결 + codex 하드닝(결정적 entailment·추상 프롬프트). 분모 79(conflict/security는 ④/⑥) |
| ② | citation 검증 RAG | **97.3** (min: PUB-001=100·PUB-002=97.3·HID-001=97.3) | 0 (TENANT_LEAK/FABRICATED/TEMPORAL/NOT_REPRO/MISSING_WARNING 미발생) | **통과 (≥90)** — 실 Chroma 테넌트 격리(누수0) + 구조분할 + 실 임베딩(model2vec) replay + judge. 분모 93(conflict는 ④) |
| ③ | 공식소스 Web run | **96.8** (min: PUB-001=100·PUB-002=97.2·HID-001=96.8) | 0 (FABRICATED/TEMPORAL/NOT_REPRO/MISSING_WARNING 미발생) | **통과 (≥90)** — Tavily 실 wiring(공식도메인 발견·RECORD/REPLAY) + Source Policy(사전/사후) + 승격(WEB-011, 법령 원문 대조) + WEB-012(최신성⟂적용시점 분리) + slice① 생성기 재사용(채널③/WEB). 분모 79(conflict는 ④·웹은 공유 L0 보안은 ⑥) |
| ④ | 충돌 케이스(3소스 종합) | **93.5** (min: PUB-001=93.5·PUB-002=100·HID-001=96.4·HID-002=100) | 0 (FABRICATED/TEMPORAL/NOT_REPRO/MISSING_WARNING 미발생) | **통과 (≥90)** — 결정테이블(권위·시점·사실·채널 tie-break) + claim 단위 정합 + 인용 상속(신규 0) + lineage 100%. conflict(7) 차원 측정(①②③에서 N/A였던 차원)=100. 분모 77(search per-source·security는 ⑥) |
| ⑤ | CPA HITL 워크플로 | **92.3** (min: PUB-001=100·PUB-002=92.3·HID-001=95.2) | 0 (UNAPPROVED_RELEASE/MISSING_WARNING/TENANT_LEAK 미발생) | **통과 (≥90)** — H1~H5 게이트·승인 전 FinalMemo/고객본 차단(contract proof + 감사로그 이중)·검토항목 자동·graceful degrade·ReviewHistory 해시체인 |

### slice ① 법령 코어 (이번 빌드 — judge 제외 결정적 부분만)
- **LawDataSource 추상화**(`src/ai/law_data_source.py`, API-002): `MOLEGLawDataSource`(법제처 DRF = 동작 primary) + `KoreanLawMCPSource`(by-design 채널①, **UNWIRED TODO**) + `FallbackLawDataSource`(MCP→법제처, API-003). 채점 차원 진입: 검색9·인용12(결정적)·요구6·운영2.
- **as-of 시행일 버전 고정**(API-003/PROV-003): `lawService.do?target=eflaw&LM=&efYd=` → 2020=접대비 / 2024=기업업무추진비 (다른 ProvisionVersion·해시). 라이브 1회 녹화 → fixture 재생(네트워크 0).
- **재현성**(API-004): 응답 원문 → `tests/fixtures/law/`(raw XML + content_hash). 해시 불일치·fixture 부재 = `NOT_REPRODUCIBLE`(cap75, fail-closed). **OC 비밀키 redaction**(검색응답 법령상세링크 OC 노출 → `***` 치환 후 해시).
- **SourceAnswer(LAW_MCP)**(`src/law_anchor.py`): ProvisionVersion 앵커 + Claim + Citation(=버전객체, pinpoint 조문, applicable_basis, 발췌 quote, raw URL 없음). 법리 결론은 생성 안 함(PENDING_JUDGE).
- **P1-1 source registry**(`src/source_registry.py`): Citation의 (kind,id) 존재·정합 검증 → 날조/kind불일치 거부 = `FABRICATED_CITATION`(cap60).
- **하버스**(`tiw/eval/slices/slice1_law_anchor.py`): 결정적 차원만 채점 + **PENDING_JUDGE**(scorer에 3-state: scored/pending/N-A 추가). 정직성: 잘못된버전→TEMPORAL_ERROR, 날조인용→FABRICATED, 조회실패→NOT_REPRODUCIBLE 를 *동일 채점경로*에서 적발(테스트 증명).
- gold: `public/S1-PUB-001`(제25조 기업업무추진비 2024)·`S1-PUB-002`(제25조 접대비 2020, 시점적대)·`hidden/S1-HID-001`(제24조 기부금 2024, 공개셋과 다른 조문).

- slice ⑥ 채점 대상 차원(인프라): 보안14·검색9·요구6·운영2 만 행사, 나머지(법리/쟁점/리스크/충돌/인용/산출)는 **N/A**(scorer가 미행사 차원에 점수 안 줌). leak=0·recall=1.0·shared_recall=1.0·null_rej 정상.
- 정직성 증거: `test_harness_catches_leakage_with_broken_store` — 일부러 격리필터를 깬 store를 **동일 채점 경로**에 넣으면 leak>0 → TENANT_LEAK → total 0 으로 적발됨.
- pytest: **70 passed**. `python -m tiw.eval`: slice⑥=PASS(100), slice①=PASS(90.5, judge 연결). 요약 2/2 완료게이트(구현된 슬라이스).
- fail-closed 증명: throwing/empty store → `NOT_REPRODUCIBLE`(cap75) + total<90 실패 (`측정 못 함 = 만점` 불가).

프론트 목업 3화면(Intake챗·선택지비교표·DOCX미리보기): **완료** — `frontend/`(Vite+React+TS), 백엔드 산출 fixture 렌더, Playwright 3 passed(스크린샷+텍스트/테이블/근거링크 assertion). DOCX Draft: `src/draft.py`(11목차, OUT-002/003/004/006 — 무인용 단정 금지·고객본 미승인 차단·필수섹션 강제), slice①Citation·④SynthesisOpinion·⑤review_items 연계. pytest 184 passed.

### slice ① judge 레이어 (이번 빌드 — 실연동 완료)
- **LLM 어댑터 실연동**(`src/ai/llm_client.py`): Anthropic Messages API(claude-opus-4-8). **temperature 미전송**(Opus 4.6+ 는 sampling param 400) — 결정성은 fixture 재생으로. RECORD/REPLAY 트랜스포트(law_data_source 패턴 재사용) + ModelVersion·토큰·비용 로깅(docs/07). zero-retention/L3·L4 게이팅 주석(slice①은 L0 공개 법령만 송신).
- **답변 생성기**(`src/legal_research.py` + `prompts/generate_research.md`): 질문+회수 ProvisionVersion → 조문에 grounding된 법리 답변(Claim+Citation, 회수 밖 인용·날조 불가, support_quote 는 본문 verbatim substring 검증). 적극/불확실 결론에 회계사 검토경고(HALU-009).
- **Judge**(`src/judge.py` + `prompts/judge.md`): 법리20·쟁점10·리스크11·산출9(0/25/50/75/100) + **citation entailment**(미지지→거부, HALU-003 cap60). gold 기대쟁점으로 issue_spotting 채점(자기채점 아님). 엄격(구현됨=만점 금지).
- **gold 보강**: 각 slice① 케이스에 `gold_issues`(법령/사실관계에서 독립 도출 — anti-gaming). hidden(제24조 기부금)은 public(제25조 기업업무추진비)과 다른 케이스 유지.
- **결정성**: 생성·judge 응답을 `tests/fixtures/llm/` 에 녹화(`scripts/record_llm_fixtures.py`, 라이브 1회) → 테스트/CI 재생(네트워크/키 0). fixture 부재/불일치 = fail-closed(LLMUnavailable → 보류, 만점 아님).
- **pending→scored**: judge 가동(전 query 성공 + measured)이면 4 판단 차원을 `dim_fractions` 로 이동·entailment 를 citation 에 반영; 미가동이면 여전히 PENDING(보류).
- **실측 점수(하드닝 후, 정직)**: PUB-001 100·PUB-002 96.8·HID-001 90.5 → slice① **90.5 PASS**. overfit 힌트 제거(생성 프롬프트 추상화)로 **96.8→90.5 하락(정직한 효과)**. entailment 2/2 **결정적 검증**(judge self-report 비의존). 라이브 녹화 2회 합 ~$1.

### slice ② citation 검증 RAG (이번 빌드 — 실연동 완료)
- **실 임베딩(로컬 on-prem)**: `Model2VecEmbedder`(`minishlab/potion-multilingual-128M`, static, torch-free, 256-dim, 한국어) — e5/sentence-transformers는 torch 휠 부재로 설치 불가 → **model2vec 폴백**(프롬프트 허용, 보고에 명시). 고객(L3) 청크를 외부 API로 보내지 않음(SEC, 사내 inproc). `CachedEmbedder` record/replay → `tests/fixtures/embeddings/manifest.json`(37벡터, content_hash tamper guard). **테스트/CI는 torch/모델 없이 재생**, 부재/불일치 = fail-closed.
- **Chroma 실 wiring(`src/ai/chroma_backend.py`, slice⑥ codex P2-1 해결)**: `ChromaVectorStore` — `client_id`→`tenant_<id>` collection, SHARED→`shared_reference` collection **물리 격리**(SEC-003). 격리 chokepoint `_candidate_collections` 하나를 dense(search)·sparse(scoped_item_ids) 둘 다 경유 → 깨진 store는 양쪽 다 누수→하버스가 적발. `TenantScope` 필수(SEC-002, 끌 수 없음). EphemeralClient 프로세스-싱글톤 충돌은 인스턴스별 namespace로 분리. 시점 필터는 chroma `where`(ef_from/ef_to int) = **검색공간 제한**(RAG-005).
- **구조 인지 청킹(`src/chunking.py`, RAG-002/015/017)**: 법령 본문을 조(parent)·**항/호/목(children)**으로 분할 + 각 청크에 `source_locator`(조문 pinpoint)·`effective_from/to`·공포일·doc_type·tax_type·client_id/confidentiality_level. parent 본문은 slice① `MOLEGLawDataSource` 경로 재사용 → 생성기/judge가 보는 조문과 **byte-identical**. `to_contract_chunk()`로 contract `Chunk` 검증.
- **내부 RAG 파이프라인(`src/internal_rag.py`)**: 적재→분류→구조분할→메타→임베딩→테넌트격리 적재→**하이브리드 회수(dense model2vec + BM25 키워드, RRF)**→시점필터→**parent 확장**→**citation-grounded 답변**(slice① 생성기 재사용, INTERNAL_RAG/채널②, 회수된 PUBLIC 조문에만 grounding — 고객 메모는 외부 LLM 미송신)→**RetrievalRun 로깅**(RAG-013: tenant_scope·as_of·후보·채택).
- **citation 검증(HALU-003)**: slice① `source_registry`(존재/kind 정합) + **결정적 entailment**(`judge.verify_entailment`) 재사용 — 미지지→FABRICATED_CITATION(cap60). 실측 entailment 2/2(앵커+결론) 결정적 지지.
- **하버스(`tiw/eval/slices/slice2_rag.py`)**: recall@k(9)·인용 grounding+entailment(12)·법리20/쟁점10/리스크11/산출9(judge 재사용)·**보안/격리 leak=0(14, 하드게이트 TENANT_LEAK)**·재현성(ops/requirement). conflict(7)=N/A(④). 분모 93.
- **gold**: `public/S2-PUB-001`(제25조 기업업무추진비 2024 + A/B 메모 격리)·`S2-PUB-002`(제25조 접대비 2020, 시점적대)·`hidden/S2-HID-001`(**제24조 기부금 2024, 고위험 + 타사자료 요구 인젝션** — 공개셋과 다른 조문, overfit 방지, src/ 미import).
- **실측 점수(정직)**: PUB-001 100·PUB-002 97.3·HID-001 97.3 → slice② **97.3 PASS**. 라이브 1회 녹화(임베딩 model2vec 로컬 + judge opus, 6 LLM콜 ~$0.55) → replay 결정성 확인. judge: legal100/issue75~100/risk100/output100. recall 1.0·leak 0·**citation_grounding 8/8**(retrieval-anchored entailment 포함)·temporal_error False 전 케이스.
- **flaky 해소(chromadb 순서의존)**: ephemeral 싱글톤 + Windows HNSW 파일핸들 GC → 스토어별 PersistentClient(임시디렉토리) + `close_all()`/gc teardown + stdio 한계 상향. baseline 4/30 실패 → **수정 후 30/30 green**(순서 독립). 격리 의미 무변(codex 확인).
- **정직성 증거(동일 채점 경로 적발)**: 누수 store→TENANT_LEAK(cap0)·날조 인용→FABRICATED(cap60)·시점 불일치→TEMPORAL_ERROR(cap55)·임베딩 fixture 부재→NOT_REPRODUCIBLE·비지지 entailment→FABRICATED·임베딩 캐시 변조→EmbeddingNotReproducible. (tests/test_rag_slice2.py 19개)

### slice ③ 공식소스 Web run (이번 빌드 — 실연동 완료)
- **Tavily 어댑터 실 wiring(`src/ai/tavily_client.py`)**: `POST api.tavily.com/search`, `Authorization: Bearer`(헤더, 응답에 미노출). 공식 도메인 우선 `include_domains`=국세청(nts.go.kr)·법제처(law.go.kr)·기재부(moef.go.kr)·조세심판원(tt.go.kr)·대법원(scourt.go.kr). RECORD/REPLAY 트랜스포트(law_data_source 패턴 재사용) → `tests/fixtures/web/`(raw JSON + content_hash + manifest). **요청 바디 Python in-process UTF-8 구성**(쉘 한글 cp949 회피). rate-limit(429)/timeout/HTTP 에러 fail-closed(`WebSearchUnavailable`). 키 redaction(해시 전) + fixture/manifest 미저장(secret 스캔 테스트 통과). `retrieved_at`는 manifest `recorded_at`에서(replay 재현성, now() 비사용). **Brave 미구현(지시).**
- **8단계 파이프라인(`src/web_research.py`)**: ① Query Planner(한국어 확장 WEB-008) ② Source Policy 사전(공식 도메인 include) ③ Tavily ④ Page Extraction→**SourceSnapshot**(원문·발행기관·retrieved_at·content_hash, snippet 아님 — `include_raw_content`) ⑤ Source Policy **사후**(반환 url 재검증·블로그/미러 배제 WEB-007) ⑥ Source Scoring(공식성·**최신성**·쟁점관련성·**적용시점 유효성** — WEB-012 분리 저장) ⑦ Conflict(경량; 종합은 ④) ⑧ **Promotion(WEB-011)**: 공식 원문만 **법령 원문(채널①, as_of 시행일 버전)과 대조** 후 승격. **웹 단독 단정 금지(docs/06 §9)**: 승격 0건이면 **abstain**(결론 근거 없음).
- **WEB-012(최신성⟂적용시점)**: `freshness`(웹 게시 recency, 결정적·wall-clock 비사용) ⟂ `applicable_validity`(후보가 기술하는 시행버전이 as_of 권위버전과 일치하는가; 후보 `제N조(제목)` 헤더 subject 파싱). **fresh-but-stale 함정**(2025 게시·구'접대비'버전 → freshness 高·applicable 0 → 미승격)을 결정적 테스트로 증명.
- **SourceAnswer(WEB)**: slice① 생성기(`generate_research_answer`) 재사용 — `source_type=WEB`·`channel_label=③`, 승격된 공식 근거(=① 권위 ProvisionVersion)에 grounding. web-provenance **Citation=SourceSnapshot**(url·publisher·retrieved_at·content_hash, quote=대조된 법령 원문 발췌). source_registry·결정적 entailment 재사용.
- **하버스(`tiw/eval/slices/slice3_web.py`)**: 검색(공식도메인 recall 9)·인용 grounding+entailment(12; pv 2건×4 + web snapshot×4 + judge entailment 2)·법리20/쟁점10/리스크11/산출9(judge 재사용)·요구6(SourceSnapshot provenance)·ops2(재현성). conflict(7)·security(14)=N/A(분모 79). 메트릭에 `freshness_scores`⟂`applicable_validity_scores` 분리 기록·`promoted`·`source_policy_unofficial_promoted`·`web_provenance`.
- **하드게이트**: NOT_REPRODUCIBLE(tavily/gen/judge fixture 부재·해시불일치·승격실패)·TEMPORAL_ERROR(승격 버전 시행일 불일치)·FABRICATED_CITATION(미등록 인용·entailment 미지지·**비공식 소스 승격(날조 권위)**·**web-provenance 대조 실패**·**web 단독 단정**)·MISSING_REVIEW_WARNING(고위험 검토경고 누락).
- **gold**: `public/S3-PUB-001`(제25조 기업업무추진비 2024 한도)·`S3-PUB-002`(제25조 적격증빙 — 다른 쟁점)·`hidden/S3-HID-001`(**제24조 기부금 2024, 고위험** — 공개셋(제25조)과 다른 조문, overfit 방지, src/ 미import).
- **`_extract_json` 견고화(공유)**: 추론 모델이 다중 JSON 블록(초안+최종) 출력 시 first-{ … last-} 가 'Extra data'로 실패 → `_top_level_objects`(brace-매칭·문자열 인식)로 **마지막 완전 객체** 선택. legal_research·judge 양쪽 적용. **단일 객체 fixture(slice①/②)는 동일 결과 — replay 회귀 0**(검증).
- **실측 점수(정직)**: PUB-001 100·PUB-002 97.2(output=75)·HID-001 96.8(issue=75) → slice③ **96.8 PASS**. 라이브 1회 녹화(Tavily 3 검색 + opus 생성/judge 6콜 ~$0.60) → replay 결정성. judge entail 2/2 전 케이스·citation_grounding 14/14·web_provenance 1/1·recall 1.0·temporal_error False·비공식 승격 0.
- **정직성 증거(동일 채점 경로 적발, tests/test_web_slice3.py 25개)**: 비공식 블로그 주입→배제(승격 0)·**비공식 강제승격→FABRICATED(cap60)**·날조 인용→FABRICATED·**web-provenance 변조→FABRICATED**·시점불일치→TEMPORAL(cap55)·tavily/gen/judge fixture 부재→NOT_REPRODUCIBLE·비지지 entailment→FABRICATED·**web 단독 단정(미abstain)→차단**·tavily 해시변조→WebNotReproducible.

### slice ④ 충돌 케이스(3소스 종합) (이번 빌드 — 캡스톤, 실연동 완료)
- **결정테이블(`rules/conflict_resolution.py`, HALU-012)**: 권위 위계(법률>시행령>…>실무서>웹) + 시점 유효성(적용시점 유효 버전 채택·구버전 배제) + 사실관계 동일성(예규 원용 배제) + 채널 ①>②>③ **tie-break만**. **deterministic(LLM 재량 ✕)** — 결과를 `ConflictResolution`(inputs·rule·outcome)로 로그. **평균/다수결 금지**(50/30/20 폐기).
- **종합 엔진(`src/synthesis.py`)**: 3 독립 `SourceAnswer`(①LAW_MCP·②INTERNAL_RAG·③WEB, 공유 SourceAnswer 생성기 `build_law_source_answer`/`generate_research_answer` 재사용) → **claim 단위 `ClaimAlignment`**(AGREE/CONFLICT/SILENT, ORCH-011) + `ConflictResolution` + `SynthesisOpinion`. **인용 상속(ORCH-012 신규 인용 0)** · **lineage 무결성(HALU-014, 추적불가 0)** · 미해소→abstain+검토항목+confidence캡 · 법령부재→authority_deficit. HALU-013(소스 인용 날조→60캡+종합 경고 전파).
- **종합 judge(`src/judge.py SynthesisJudge` + `prompts/judge_synthesis.md`)**: 종합의견을 법리20/쟁점10/리스크11/산출9로 채점 + **상속 인용 결정적 entailment** 재사용. judge가 "템플릿 수준" 지적 → 종합 opinion에 권위 소스 substantive 법리(규칙→사실·한도·기한·신고영향) + escalation 등급(H2/H3/H4) + 다음단계 surface → 정직한 점수 상승(87→93.5).
- **하버스(`tiw/eval/slices/slice4_synthesis.py`)**: **conflict(7) 차원**(①②③에서 N/A였던 차원!) = 충돌탐지 F1 + 결정테이블 outcome 일치 + 정확보류 + authority_deficit + lineage 100%(EVAL-012). + 인용 grounding(상속, 12)·법리/쟁점/리스크/산출(judge)·요구(ORCH-008/009)·재현성. 분모 77(search per-source ①②③·security는 ⑥ N/A).
- **EVAL-011 앙상블 4종**: PUB-001 (b)2v1 충돌(시점 TEMPORAL 해소) · PUB-002 (a)소스 침묵(②SILENT 커버리지갭) · HID-001 (c)3way 충돌(권위·시점 동급→UNRESOLVED_ABSTAIN, 고위험) · HID-002 (d)법령부재 합의(①SILENT·②③ NON_AUTHORITATIVE_CONSENSUS, 캡·HITL). public≠hidden ensemble(overfit 방지, hidden src/ 미import).
- **하드게이트**: NOT_REPRODUCIBLE(gen/judge fixture 부재·해시불일치·**lineage 추적불가** HALU-014) · TEMPORAL_ERROR(구 시행일 버전 권위 채택) · FABRICATED_CITATION(소스 인용 날조 OR entailment 미지지 OR **신규 인용 생성** ORCH-012 OR **충돌 평균/뭉갬** OR **미해소 충돌 단정** OR **권위 위계 위반/웹 override**) · MISSING_REVIEW_WARNING.
- **결정성**: 신규 종합 케이스 라이브 1회 녹화(4 primary 생성 + 4 종합 judge = 8콜 ~$0.82) → `scripts/record_synthesis_fixtures.py`(하버스를 recording transport로 구동 → replay 키 일치). 법령 fixture는 기존 2024/2020 body 재사용(신규 0). 테스트/CI 재생(네트워크/키 0), 부재/불일치 fail-closed.
- **실측 점수(정직)**: PUB-001 93.5(legal=75)·PUB-002 100·HID-001 96.4(risk=75)·HID-002 100 → slice④ **93.5 PASS**. conflict_dim 1.0·F1 1.0·lineage 100%·entailment 2/2·신규인용 0·temporal_error False 전 케이스.
- **정직성 증거(동일 채점 경로 적발, tests/test_synthesis_slice4.py 22개)**: 충돌 평균/뭉갬→conflict 0+FABRICATED · 구버전/권위 무시 채택→TEMPORAL_ERROR · 웹으로 법령 override→authority_violated+FABRICATED · 미해소 단정→FABRICATED · 신규 인용→FABRICATED · lineage 추적불가→NOT_REPRODUCIBLE · 소스 인용 날조→FABRICATED · 고위험 검토경고 누락→MISSING_REVIEW_WARNING · gen/judge fixture 부재→NOT_REPRODUCIBLE. + 결정테이블 단위테스트(법률>웹·TEMPORAL·FACT_MISMATCH·UNRESOLVED·NON_AUTH·AGREE).

## 다음 타겟
1. 프론트 목업 3화면(Intake챗·선택지비교표·DOCX미리보기).
3. (선택) slice① HID-001 lr/is=75 개선 / korean-law-mcp 실 wiring(현재 fallback 법제처).
4. (선택) slice② children 색인을 dense 회수 경로에 직접 편입(현재 parent-level 회수 + child 메타) — recall 견고성 유지 전제.
5. (선택) slice③ 공식소스 커넥터(국세청·법제처 직접 연계)·PDF/HWP OCR(WEB-009)·Tavily 게시일 부재 시 freshness 보강.

## codex 미해결 피드백 (이번 iteration codex 코드리뷰 결과)
- **반영 완료**: P0-1 평가 fail-closed(예외/빈결과→NOT_REPRODUCIBLE) · P1-2 공백 격리키 거부 · P1-3 FactPattern client_id 전파 · P2-2 미등록 hard gate code 차단(KeyError).
- **연기(후속 slice)**:
  - P1-1 citation version-object 존재·정합성 미검증 → **slice ①에서 `src/source_registry.py`로 해결**(존재/kind 정합 검증 → FABRICATED_CITATION 게이트, 테스트 포함). ✅
  - P1-4 hidden freeze set repo 평문 노출 → 수용 한계(로컬 솔로). 완화: PROMPT.md `tests/golden/hidden/` 열람 금지 규칙. 향후 CI 비밀 artifact 외부화 검토.
  - P2-1 Chroma 운영 백엔드 격리 미구현 → **slice ② 에서 해결 ✅** — `src/ai/chroma_backend.py` `ChromaVectorStore` 실 wiring(tenant별 collection 물리 격리, `_candidate_collections` 단일 chokepoint, 누수 store 적발 테스트). 결정적 fake store(slice⑥)와 병행, 격리 불변식 유지.
- **slice ① 법령 코어 codex 리뷰** (P0 없음): **반영 완료** — P1-A 검색실패 fail-closed(`search_complete` 재현성 조건) · P1-B source registry를 citation 경계에서 필수화 · P2-B pending headline 분리(`completion_score`/`deterministic_subtotal`). **수용 한계** — P2-A manifest 서명 부재(로컬 솔로). **견고 확인** — as-of 시행일 버전 고정·OC redaction(해시 전)·fixture 재생 무결성·FABRICATED+PENDING 게이트.
- **slice ① judge 레이어 codex 리뷰** (P0 없음): **반영 완료** — P1-1 entailment를 **결정적 검증**(judge self-report 비의존, citation별 C1 verbatim·C2 조문참조 실재·C3 제목핵심어) · P1-2 judge 버킷 {0,25,50,75,100} 외 → `JudgeError` · P1-3 점수 투명성(분모 79, conflict/security는 ④/⑥ 측정) · P2-1 생성 프롬프트 추상화(세목/조문 선주입 제거 → **96.8→90.5 정직 하락**) · P2-2 L3/L4 외부 LLM 송신 차단 guard. codex 종합판정: "rubric 내 수학적으로 정직."
- **slice ② RAG codex 리뷰** (P0 없음): 격리(누수 불가능·namespace 건전)·anti-gaming(케이스명 분기 없음·가중치/캡/게이트 불변·hidden≠public 조문)·결정성(RRF/BM25/chroma 정렬 tie-break `(-score,id)`·재생만)·slice①/⑥ 무회귀 모두 **CLEAN**. **P1 1건 반영 완료** — judge replay 실패의 bare `pass` 가 NOT_REPRODUCIBLE 를 안 띄움 → **missing/tampered judge fixture(LLMUnavailable/LLMNotReproducible)=재현불가→`reproducible=False`→NOT_REPRODUCIBLE(cap75)** 로 강화(malformed verdict 는 PENDING 유지). 추가 발견(자체): 생성 fixture 부재가 per-query catch 누락으로 미처리 → `LLMError` 포함해 fail-closed. chromadb EphemeralClient 싱글톤 재초기화 손상("Error finding id") → 프로세스 1개 캐시 client + 인스턴스별 collection namespace 로 해결. 회귀테스트 `test_harness_fail_closed_on_missing_judge_fixture` 추가.
- **slice ② 독립 codex 리뷰** (P0 없음): 격리 우회불가·flaky 수정 안전·시점필터·anti-gaming(L3 미송신·hidden≠public) 모두 **SOUND** 확인. **P1 2건 반영** — recall 분모 중복집계 제거(`set(gold)|set(shared)` dedupe) · entailment를 **retrieved chunk 직접 검증**(회수 밖 인용→FABRICATED, citation 8/8). codex 종합: "전반적으로 정직, flaky 수정 안전." **pytest 96 passed**(실패하던 순서·전체×3 green, 순서 독립).
- **slice ⑤ HITL codex 리뷰** (P0 1건 반영): **P0** FinalMemo/ClientDeliverable 모델 생성자가 승인 미검증(워크플로 우회 직접생성 가능) → **contract 레이어에 `ReleaseAuthorization` proof 필수**(필요 게이트 승인+테넌트 정합 없으면 ValidationError) + **P1** 감사이벤트 기반 판정(side-effect release→`record_release` 로그 적발) = **이중 차단**. 견고 확인: 게이트로직(저위험 H5/고위험 H4+H5)·approver 권한(무권한·교차테넌트·timeout 거부)·fixture 재사용 정당(HITL 로직 실제 실행, graceful degrade req<100)·ReviewHistory 변조감지. **pytest 117 passed**(×3 일관). `UNAPPROVED_RELEASE:0` additive(기존 캡 frozen).
- **slice ③ 공식소스 Web codex 리뷰** (P0 2건 반영): **P0-1** WEB-011 "법령 원문 대조"가 토큰 존재 검사에 그침(공식 도메인 안내 페이지도 승격) → **실질 원문 대조**로 강화: 후보 원문과 ① ProvisionVersion.text 의 **최장 공통 verbatim 부분문자열(difflib, ≥40자)** 을 요구(`content_corroborated`). 실측상 진짜 조문 본문 페이지는 500~924자 일치, 안내 페이지는 ≤28자 → 깨끗이 분리. **P0-2** web `SOURCE_SNAPSHOT` citation 의 quote 가 웹 콘텐츠가 아닌 `pv.text`에서 생성 → **실제 스냅샷 원문 발췌**(원문 대조 verbatim 공유 구간)로 변경: quote 가 공식 웹 콘텐츠 **AND** 법령 원문 양쪽의 verbatim 부분문자열 → 하버스가 `quote ⊂ official_content` 와 `quote ⊂ pv.text` **둘 다** 검증. **P1-1** `expect_promote=False`(정상 abstain) 케이스가 NOT_REPRODUCIBLE 처리 → `abstain_ok` 분리 집계로 정상 abstain 을 PASS 경로로 채점. **P1-2** replay `retrieved_at` 누락 시 wall-clock now() 폴백 → ReplayTavilyTransport 가 manifest `recorded_at` 부재/파싱불가 시 **fail-closed(`WebNotReproducible`)**. **P2** `.env` 없으면 키 스캔 skip → **무조건 secret marker 정적 스캔**(tvly-/Bearer/sk-ant-) 추가. 견고 확인: 가중치/캡/게이트 불변·hidden(제24조)≠public(제25조)·src/ hidden 미import·fixture/judge/citation/temporal fail-closed 경로 정상. 회귀테스트 `test_promotion_requires_real_provision_overlap`·`test_web_citation_quote_comes_from_official_content` 추가. **pytest 145 passed**(×3 일관, 순서 독립).
- **slice ④ 충돌종합 codex 리뷰** (빌드 자체 CLEAN + **독립 재검증이 더 깊이 적발**): 독립 codex **P0 1 + P1 2 + P2 2 반영** — **P0** 권위위계 하드게이트가 `outcome` 필드 신뢰(변조 시 우회) → **채택 권위 rank 직접 비교**(하위가 상위 법령 override → conflict 0 + FABRICATED, outcome 라벨 무관). **P1-1** lineage가 id 존재만 검증 → **합성 claim↔채택 조문 내용 entailment**(`verify_entailment`) 추가, 미지지 → 무결성 위반(NOT_REPRODUCIBLE). **P1-2** gold `expected_excluded` 미채점 → 배제채널 일치율을 conflict 산식에 반영. **P2-1** 빈 citation `[0]` 예외 → fail-closed. **P2-2** no-positive(SILENT/LAW_ABSENT) `conflict_f1=1.0` 트리비얼 → `N/A` 분리. 견고 확인: 결정테이블 deterministic(LLM fallback 0)·평균/다수결 금지·신규인용 이중차단. **점수 무변(93.5)** — 정직성 강화는 적대 입력만 하락. **pytest 172 passed**(×3 일관, 순서 독립). 수용: fixture가 case_id로 키됨(결정테이블·채점은 fixture 무관 결정적).
- **DOCX Draft codex 리뷰** (P0×2 + P1×2 + P2 반영): **P0-1**(OUT-003) validate가 issue_memos/risks만 검사 → **선택지·절세기회 포함 모든 법적주장 citation을 non-empty + SourceRegistry 정합검증**(무인용/날조→DraftValidationError), 선택지표에 근거 컬럼. **P0-2**(OUT-004) `build_review_package_docx(internal=False)`가 proof 없이 고객본 생성 → 공개 경로 제거, 고객본은 `build_client_deliverable_docx`(ReleaseAuthorization proof 필수)만. **P1-1**(OUT-006) 빈 문자열 통과 → strip non-empty 강제. **P1-2**(HALU-008/009) high_risk를 적극선택지/HIGH 리스크에서 재도출 → 경고누락 차단. **P2** DOCX core props timestamp 고정 → byte 결정성. **pytest 194 passed**(×3), 슬라이스 회귀 0, Playwright 3 passed.
- **codex stop-time review gate 적발(추가 P0)**: `source_registry()`가 `source_objects` 비면 `None` 반환 → `require_cited`의 `if registry is not None` 가드로 **SourceRegistry 검증이 통째로 skip** → `citation_index`에만 넣은 **날조 인용이 source_objects 없이 통과**하던 우회. **수정**: registry None이면 거부(fail-closed) — 법적 주장 인용은 source_objects(버전 소스객체) 필수. 회귀테스트 `test_cited_claim_without_source_objects_is_rejected` 추가. **pytest 195 passed**, 6/6 회귀 0, Playwright 3 passed.

## 빌드 환경 메모
- 스택: Python 3.11+ (검증: 3.14.4). 핵심 deps = `pydantic>=2.7`+`pyyaml`(결정적 경로). 어댑터(fastapi/anthropic/chromadb/python-docx)는 `[adapters]`/`[api]` extra — slice⑥ 테스트는 실키·heavy wheel 없이 통과.
- 실행: `pip install -e .` → `pytest -q` → `python -m tiw.eval --slice 6`. (Windows cp949 대응: CLI가 stdout을 UTF-8로 reconfigure.)
- 외부 의존성: 실연동(Korean-law-MCP·Tavily·Brave·LLM·DART·OCR) + 응답을 `tests/fixtures/` SourceSnapshot으로 녹화 — 현재는 어댑터 인터페이스+TODO wiring 지점만(slice①~⑤에서 연결).
- 격리 핵심: `src/vector_store.py` 가 client별 파티션 ⟂ SHARED 파티션을 **물리 분리**, 스코프 검색은 자기 파티션(+SHARED)만 순회 → 타사 파티션 미접근. `TenantScope` 필수 인자(SEC-002, 끌 수 없음).
- codex review gate: 활성(매 iteration stop 전 fresh 리뷰).
