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
**scaffold + 평가 하버스 + slice ⑥ + slice ① (judge 연결까지) 완료** (autonomous 루프 진입 전 수동 검증 단계). 미커밋(워킹트리).

## 6 Vertical Slice 점수표 (RubricResult 기준 — 이번 iteration `python -m tiw.eval` 산출)
| # | Slice | 점수 | 하드게이트 | 상태 |
|---|---|---:|---|---|
| ⑥ | 테넌트 격리 | **100** (min over 4 cases) | 누수0 (TENANT_LEAK 미발생) | **통과 (≥90)** |
| ① | 법령MCP 앵커 답변 | **90.5** (min: PUB-001=100·PUB-002=96.8·HID-001=90.5) | 0 (TEMPORAL/FABRICATED/NOT_REPRO/MISSING_WARNING 미발생) | **통과 (≥90)** — judge 연결 + codex 하드닝(결정적 entailment·추상 프롬프트). 분모 79(conflict/security는 ④/⑥) |
| ② | citation 검증 RAG | — | — | 미착수 |
| ③ | 공식소스 Web run | — | — | 미착수 |
| ④ | 충돌 케이스(3소스 종합) | — | — | 미착수 |
| ⑤ | CPA HITL 워크플로 | — | — | 미착수 |

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

## 다음 타겟
1. (선택) slice① 여유 확보: HID-001 lr/is=75 → 생성기의 *일반* 사실판단 쟁점 추출력 개선(overfit 재도입·채점 변경 금지). 이미 90.5 통과.
2. slice ② citation 검증 RAG(RAG-002/017·HALU-003) — 실 임베더(`RealEmbeddingClient`) wiring + tenant별 collection 격리.
3. korean-law-mcp 백엔드 실 wiring(`KoreanLawMCPSource` TODO) — 현재 fallback으로 법제처가 응답.

## codex 미해결 피드백 (이번 iteration codex 코드리뷰 결과)
- **반영 완료**: P0-1 평가 fail-closed(예외/빈결과→NOT_REPRODUCIBLE) · P1-2 공백 격리키 거부 · P1-3 FactPattern client_id 전파 · P2-2 미등록 hard gate code 차단(KeyError).
- **연기(후속 slice)**:
  - P1-1 citation version-object 존재·정합성 미검증 → **slice ①에서 `src/source_registry.py`로 해결**(존재/kind 정합 검증 → FABRICATED_CITATION 게이트, 테스트 포함). ✅
  - P1-4 hidden freeze set repo 평문 노출 → 수용 한계(로컬 솔로). 완화: PROMPT.md `tests/golden/hidden/` 열람 금지 규칙. 향후 CI 비밀 artifact 외부화 검토.
  - P2-1 Chroma 운영 백엔드 격리 미구현 → **slice ②** 에서 실 wiring + tenant별 collection 격리 테스트.
- **slice ① 법령 코어 codex 리뷰** (P0 없음): **반영 완료** — P1-A 검색실패 fail-closed(`search_complete` 재현성 조건) · P1-B source registry를 citation 경계에서 필수화 · P2-B pending headline 분리(`completion_score`/`deterministic_subtotal`). **수용 한계** — P2-A manifest 서명 부재(로컬 솔로). **견고 확인** — as-of 시행일 버전 고정·OC redaction(해시 전)·fixture 재생 무결성·FABRICATED+PENDING 게이트.
- **slice ① judge 레이어 codex 리뷰** (P0 없음): **반영 완료** — P1-1 entailment를 **결정적 검증**(judge self-report 비의존, citation별 C1 verbatim·C2 조문참조 실재·C3 제목핵심어) · P1-2 judge 버킷 {0,25,50,75,100} 외 → `JudgeError` · P1-3 점수 투명성(분모 79, conflict/security는 ④/⑥ 측정) · P2-1 생성 프롬프트 추상화(세목/조문 선주입 제거 → **96.8→90.5 정직 하락**) · P2-2 L3/L4 외부 LLM 송신 차단 guard. codex 종합판정: "rubric 내 수학적으로 정직."

## 빌드 환경 메모
- 스택: Python 3.11+ (검증: 3.14.4). 핵심 deps = `pydantic>=2.7`+`pyyaml`(결정적 경로). 어댑터(fastapi/anthropic/chromadb/python-docx)는 `[adapters]`/`[api]` extra — slice⑥ 테스트는 실키·heavy wheel 없이 통과.
- 실행: `pip install -e .` → `pytest -q` → `python -m tiw.eval --slice 6`. (Windows cp949 대응: CLI가 stdout을 UTF-8로 reconfigure.)
- 외부 의존성: 실연동(Korean-law-MCP·Tavily·Brave·LLM·DART·OCR) + 응답을 `tests/fixtures/` SourceSnapshot으로 녹화 — 현재는 어댑터 인터페이스+TODO wiring 지점만(slice①~⑤에서 연결).
- 격리 핵심: `src/vector_store.py` 가 client별 파티션 ⟂ SHARED 파티션을 **물리 분리**, 스코프 검색은 자기 파티션(+SHARED)만 순회 → 타사 파티션 미접근. `TenantScope` 필수 인자(SEC-002, 끌 수 없음).
- codex review gate: 활성(매 iteration stop 전 fresh 리뷰).
