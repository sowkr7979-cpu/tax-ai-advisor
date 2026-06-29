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
**slice ⑥·①·②·⑤ 완료 (4/6 PASS)** (autonomous 루프 진입 전 수동 검증 단계 — '통제된 시작'). 남은: ③(웹, 키 필요)·④(충돌종합) + 목업.

## 6 Vertical Slice 점수표 (RubricResult 기준 — 이번 iteration `python -m tiw.eval` 산출)
| # | Slice | 점수 | 하드게이트 | 상태 |
|---|---|---:|---|---|
| ⑥ | 테넌트 격리 | **100** (min over 4 cases) | 누수0 (TENANT_LEAK 미발생) | **통과 (≥90)** |
| ① | 법령MCP 앵커 답변 | **90.5** (min: PUB-001=100·PUB-002=96.8·HID-001=90.5) | 0 (TEMPORAL/FABRICATED/NOT_REPRO/MISSING_WARNING 미발생) | **통과 (≥90)** — judge 연결 + codex 하드닝(결정적 entailment·추상 프롬프트). 분모 79(conflict/security는 ④/⑥) |
| ② | citation 검증 RAG | **97.3** (min: PUB-001=100·PUB-002=97.3·HID-001=97.3) | 0 (TENANT_LEAK/FABRICATED/TEMPORAL/NOT_REPRO/MISSING_WARNING 미발생) | **통과 (≥90)** — 실 Chroma 테넌트 격리(누수0) + 구조분할 + 실 임베딩(model2vec) replay + judge. 분모 93(conflict는 ④) |
| ③ | 공식소스 Web run | — | — | 미착수 |
| ④ | 충돌 케이스(3소스 종합) | — | — | 미착수 |
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

프론트 목업 3화면(Intake챗·선택지비교표·DOCX미리보기): 미착수(백엔드 슬라이스 선행).

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

## 다음 타겟
1. slice ③ 공식소스 Web run(WEB-002/003/004/011/012) — **Tavily/Brave 키 필요(미보유)** + 어댑터 실 wiring + SourceSnapshot 녹화 + 공식 도메인 우선.
2. slice ④ 충돌 케이스(3소스 종합) — ①②③ SourceAnswer claim 단위 정합 + conflict(7) 차원 측정.
3. (선택) slice① HID-001 lr/is=75 개선 / korean-law-mcp 실 wiring(현재 fallback 법제처).
4. (선택) slice② children 색인을 dense 회수 경로에 직접 편입(현재 parent-level 회수 + child 메타) — recall 견고성 유지 전제.

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

## 빌드 환경 메모
- 스택: Python 3.11+ (검증: 3.14.4). 핵심 deps = `pydantic>=2.7`+`pyyaml`(결정적 경로). 어댑터(fastapi/anthropic/chromadb/python-docx)는 `[adapters]`/`[api]` extra — slice⑥ 테스트는 실키·heavy wheel 없이 통과.
- 실행: `pip install -e .` → `pytest -q` → `python -m tiw.eval --slice 6`. (Windows cp949 대응: CLI가 stdout을 UTF-8로 reconfigure.)
- 외부 의존성: 실연동(Korean-law-MCP·Tavily·Brave·LLM·DART·OCR) + 응답을 `tests/fixtures/` SourceSnapshot으로 녹화 — 현재는 어댑터 인터페이스+TODO wiring 지점만(slice①~⑤에서 연결).
- 격리 핵심: `src/vector_store.py` 가 client별 파티션 ⟂ SHARED 파티션을 **물리 분리**, 스코프 검색은 자기 파티션(+SHARED)만 순회 → 타사 파티션 미접근. `TenantScope` 필수 인자(SEC-002, 끌 수 없음).
- codex review gate: 활성(매 iteration stop 전 fresh 리뷰).
