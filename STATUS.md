# TIW Ralph Loop — STATUS (진행 원장)

> 매 iteration 시작 시 이 파일 + `git log --oneline -15`를 먼저 읽는다. (PROMPT.md §3.1)
> 점수는 **STATUS 자기보고가 아니라** 같은 iteration의 `pytest -q` + `python -m tiw.eval` 산출 `RubricResult`로만 증명된다(완료 판정 기준).

## ★ 미션 v1.1 (변경①②③) — slice ⑦ 진행 중 (완료 게이트 미충족)
> **현 미션**: 기존 6 slice(①~⑥)는 PASS 유지하면서 **slice ⑦ "다세목·투명성"** 을 ≥90으로 올린다. **7-slice 게이트 미충족**(slice⑦ 미착수) → `<promise>` 금지, 계속 개선.
- **Rubric Freeze v1.1** (사용자 승인 확장) — 완료 게이트 6→**7 slice ≥90** + per-FR 예시 H/I/J + DOCX 11→13목차. 기존 가중치·하드게이트·6 slice 합격조건 **불변**(회귀 0).
- **slice ⑦ 3 기능 (스펙: 정본 §3-4·§4-2-1·§4-3·§4-4 + docs/03·08·09)**:
  - **변경① `ORCH-015`** 세목·쟁점→법령 레지스트리(법인세 하드코딩 제거) — 소득세/퇴직소득 케이스 동일 파이프라인 13목차 산출 + 미등록 세목 fail-closed.
  - **변경② `OUT-007`** 채널별 독립결과(①법령·②내부RAG·③웹) §8 병렬표시 + 내부RAG 부재 시 SILENT 정직표기 + 채널원본⟂종합 분리.
  - **변경③ `OUT-008`/`HALU-015`** §10 law-tracing 사슬 + ReasoningTrace 도식(하이브리드: 프론트 Mermaid / DOCX 네이티브), 실제 trace 정합(사후 서사 금지).
- **다음 타겟(우선순위)**: ① ORCH-015 레지스트리 **[iter1: 레지스트리 외부화 완료]** → 다음: law_name 쟁점별 threading + 소득세/퇴직소득 fixture·gold → ② OUT-007 채널별 표시(draft.py 섹션 + contributions 전달) → ③ OUT-008/HALU-015 ReasoningTrace + 도식. 각 단계 매 iteration codex 리뷰.
- **착수 전 측정 필요**: `tiw.eval`에 slice ⑦ 하버스(slice7_multitax_transparency) 추가 → 현재 점수(미구현이므로 <90) 산출. **(iter2 예정)**

### iter1 (a753dd6 이후) — ORCH-015 레지스트리 외부화
- **변경①(부분)**: `rules/tax_law_mapping.yaml`(세목→쟁점→법령 매핑 데이터) + `rules/tax_law_mapping.py`(로더, `IssueMapping`/`article_by_issue`/`law_name_for`) 신설. orchestrator `_ARTICLE_BY_ISSUE` = `article_by_issue()` 로 전환(하드코딩 제거). **법인세 4항목 문자 단위 동일 → 회귀 0**(`pytest 215 passed`). 소득세/퇴직소득(소득세법 제22조) 레지스트리 등록(데이터; end-to-end 는 fixture 녹화 선행).
- **남은 일(다음 iter)**: (a) ~~law_name threading~~ **[iter2 완료]** · (b) 소득세/퇴직소득 law·LLM fixture 녹화(--live) + gold · (c) `draft.py` "법인세" 제목 하드코딩 제거 · (d) slice7 하버스로 측정 · (e) OUT-007/008.

### iter2 (0a0cfaa 이후) — ORCH-015 law_name 쟁점별 threading (codex 적발 수정)
- **codex stop-time 적발**: "non-corporate mapped issues can run against the wrong law" — iter1에서 소득세를 레지스트리 등록했으나 orchestrator `_lookup`/research/citations 가 여전히 하드코딩 `_LAW_NAME="법인세법"` → 소득세 쟁점이 **법인세법 제22조**로 silent 오조회 위험.
- **수정**: `_spot_issues`가 issue dict에 `law_name`/`tax_type`를 레지스트리에서 주입 → `_lookup(law_name, …)`·`_build_citations`·`_run_internal_rag`(chunk_provision)·`_run_web`·research 로그·exec_summary 전부 **쟁점별 law_name/tax_type** 로 전환. `_build_citations` dedup 키를 (법령명, 조문)으로 교정(동일 조문번호 다른 법 오결합 차단). `_summary_texts`는 `.get` 폴백(단위호출 호환).
- **측정**: **pytest 217 passed**(기존 215 + 신규 회귀 2: 소득세 쟁점 태깅 + lookup이 소득세법으로 라우팅됨을 spy로 증명). 법인세 경로 byte-동일 → 기존 slice ①~⑥ 회귀 0. `_LAW_NAME`은 이제 fallback 기본값으로만 잔존.
- **codex 미해결 → 해소**: "wrong law" 적발 반영 완료.

### iter3 (6952d96 이후) — OUT-007 part1: 채널별 결과 데이터 모델 + 배선
- **변경②(part1)**: `draft.py` `ChannelResult`(채널·소스라벨·status·answered·발췌·인용 pinpoint) + `DraftPackageData.channel_results` 필드 + `draft_package_to_fixture` 직렬화. orchestrator `_channel_results(contributions)` → 종합 *전* 의 ①②③ 독립 결과를 패키지에 적재(`_assemble_package`/`run` 배선).
- **최소 blast radius**: `REQUIRED_SECTIONS`(11) **미변경** — §8 DOCX 렌더/12→13목차 renumber 는 다음 iter. 기존 11목차 테스트 무영향(회귀 0).
- **측정**: **pytest 219 passed**(217 + 신규 2: 패키지가 ①②③ channel_results 보유 + fixture 직렬화). 데모 3소스 전부 ANSWERED 표면화 확인.
- **다음(우선순위)**: §8 DOCX 렌더 + `REQUIRED_SECTIONS` 12목차(validate/renderer/내부전용) → §10 OUT-008(ReasoningTrace) 13목차 → 프론트 §8/§10 + Playwright → slice7 하버스 측정.

### iter4 (bbb305b 이후) — OUT-007 §8 DOCX 렌더 + 12목차 (변경② 백엔드 완성)
- **변경②(백엔드 완성)**: `REQUIRED_SECTIONS` 11→**12**(§8 "출처 채널별 독립 결과" 신설, **내부 전용**). 렌더러 §8 테이블(채널·출처·상태·발췌·인용 pinpoint) + SILENT 정직표기 + 후속 섹션 인덱스 갱신(§9 관련법령~§12 결론). `validate_draft_package` §8(`channel_results`≥1) 요건 추가. `_INTERNAL_ONLY_SECTIONS`={7,8,11}. `draft_demo` 대표 채널 결과 3건. `cli` 요약 목차 동적화(`len(REQUIRED_SECTIONS)`).
- **측정**: **pytest 219**(섹션 테스트 12로 갱신, 회귀 0) + **라이브 CLI DOCX 12섹션·§8 실물 렌더 확인**(`python -m tiw run --out`).
- **변경② 상태**: 백엔드(데이터+렌더+검증) **완료**. 남음: 프론트 DraftScreen §8 + Playwright assertion.
- **다음**: 변경③ OUT-008 §10 ReasoningTrace + law-tracing 도식 → 13목차(DOCX 네이티브) + 프론트 Mermaid.

### iter5 (799017e 이후) — OUT-007 §8 완전 채널 커버리지 강제 (codex 적발)
- **codex stop-time 적발**: "§8 validation accepts incomplete channel coverage" — §8 검증이 `channel_results≥1`만 요구 → ②내부RAG/③웹이 **생략**돼도 통과(부분 커버리지 = 안 한 검색을 한 척, 정직성 위반).
- **수정**: `validate_draft_package` §8 을 **3채널(①②③) 전부 표시 필수**로 강화(`_OUT007_REQUIRED_CHANNELS`). 답 못한 채널은 *생략 ✕* → SILENT 로 남겨야 통과. orchestrator/데모는 항상 3채널 → 회귀 0.
- **측정**: **pytest 221**(219 + 신규 2: ③ 누락→fail-closed / ③ SILENT present→pass). 회귀 0.
- **codex 미해결 → 해소**: 부분 커버리지 적발 반영 완료.

### iter6 (68c8adf 이후) — OUT-008 part1: ReasoningTrace 데이터 모델 + 실제 trace 빌드
- **변경③(part1)**: `draft.py` `LawTraceEntry`/`ReasoningStep`/`ReasoningTrace` + `DraftPackageData.reasoning_trace`(Optional) + fixture 직렬화. orchestrator `_build_reasoning_trace` → **실제 실행 단계**(INTAKE→ISSUE_SPOTTING→RESEARCH_CH1/2/3→SYNTHESIS→STRATEGY→DRAFT) + law-tracing(쟁점별 **실제 회수 Citation** 에서 법령명·조문·시행시점·pinpoint·발췌).
- **HALU-015 정합**: 법적 판단 단계(쟁점도출·종합·전략)는 인용 pinpoint 동반, SYNTHESIS step 은 실제 `synthesis_id` 참조(사후 서사 ✕). 채널 step 은 `source_answer_id` 참조.
- **최소 blast radius**: `REQUIRED_SECTIONS`(12) 미변경 — §10 DOCX 렌더/13목차는 다음 iter. `reasoning_trace` Optional 기본 None → 데모/검증 무영향(회귀 0).
- **측정**: **pytest 223**(221 + 신규 2: trace 단계 커버리지+법적단계 인용+synthesis_id 참조 / fixture 직렬화).
- **다음**: §10 DOCX 네이티브 도식 + law-tracing 표 → **13목차** → 프론트 §8/§10(Mermaid) + Playwright → slice7 하버스.

### iter7 (51b0eac 이후) — OUT-008 §10 DOCX 렌더 + 13목차 (변경③ DOCX 백엔드 완성)
- **변경③(DOCX)**: `REQUIRED_SECTIONS` 12→**13**(§10 "법령 추적 경로 + 추론 과정 도식", **내부 전용**). 렌더러 §10: **10-1** law-tracing 표(쟁점→법령·조문·적용시점·pinpoint·발췌) + **10-2** ReasoningTrace 네이티브 흐름 도식(`[단계]→[단계]`) + 단계 표(#·단계·판단/근거·인용). `validate` §10(`reasoning_trace.steps≥1` + `law_trace≥1`). `_INTERNAL_ONLY`={7,8,10,12}. `draft_demo` 대표 trace(8단계+법령추적 4). 후속 §11~§13 인덱스 갱신.
- **측정**: **pytest 223**(섹션 13 갱신, 회귀 0) + **라이브 CLI DOCX 13섹션·§10(10-1/10-2) 실물 렌더 확인**.
- **★ 3개 변경 DOCX 백엔드 전부 완료**: 변경① 레지스트리·변경② §8 채널별·변경③ §10 추론도식. 검토패키지 13목차 완성(내부 전용 4: 7·8·10·12).
- **남은 큰 덩어리**: ① 프론트 §8/§10(Mermaid 도식) + Playwright 갱신 · ② **slice7 하버스**(`tiw.eval`) → slice⑦ 측정(현재 미측정) · ③ 소득세 end-to-end fixture(`--live`, 키 대기).

## Iteration 0 게이트 — Rubric Freeze ✅ 완료
- **Rubric Freeze v1.0** @ `470e47c` (사용자(회계사)+AI 공동검토 확정).
- 완료 게이트(v1.0): 6 vertical slice **각 ≥90/100** + 하드게이트 위반 0. **(v1.1에서 7 slice로 확장 — 위 섹션)**
- 가중치(합100): 요구6·검색9·인용12·**법리20**·쟁점10·충돌7·리스크11·산출9·**보안14**·운영2.
- 하드게이트 캡: 누수0·무권한/전직장0·날조60·시점오류55·검토경고누락60·재현불가75.
- 평가셋: hidden freeze 50% / public practice 50%(rotate) · 인간 CPA 앵커 20%.

## v1.0 결과 (✅ 완료 — 이력; **현재 미션은 상단 v1.1 slice⑦**)
> 아래는 v1.0(slice ①~⑥) 달성 기록이다. **현재 상태가 아님** — 현재는 v1.1 7-slice 게이트 **미충족**(상단 섹션). 이 기록은 회귀 baseline·구현 참조용으로 보존한다.
**[v1.0 완료]** 6/6 vertical slice PASS + 프론트 목업 3화면 Playwright 렌더 통과 + DOCX Draft(11목차 — v1.1에서 13목차로 확장 예정) + **오케스트레이터/CLI(`python -m tiw run`)로 "새 질문 → 검토패키지 DOCX"가 한 명령으로 구동**(라이브 1회 실행으로 실제 DOCX 산출 + replay 결정성 증명). v1.0 PROMPT.md 완료조건 충족. **pytest 214 passed**(당시).

### ★ 라이브 엔드투엔드 오케스트레이터 + CLI (이번 빌드 — 6 슬라이스 chaining)
- **Strategy Agent(`src/strategy.py`)**: 종합의견+리스크+회수 조문 → 보수/중립/적극 3종 선택지(§3-5). 인용은 **회수된 버전객체에 한정**(`registry.require_citation` 선행, LLM이 id 주조 불가) · 적극 가드레일/검토경고 fail-closed 복구 · grounding 결정적 재검증(`verify_entailment`, self-report 비신뢰).
- **오케스트레이터(`src/orchestrator.py`)**: §4-1 흐름 Intake→쟁점도출(TB→조문)→**3소스 Research**(①`legal_research`·②`internal_rag`(Chroma 테넌트격리·L3 외부LLM 미송신)·③`web_research`(공식소스 승격))→**Synthesis**(ConflictResolution)→Risk→**Strategy**→Evidence→**Draft 11목차(v1.0 당시) DOCX**. `live`/`replay` 토글. ①②③ 동일 gen 프롬프트를 `_MemoLLMClient`로 단일화 → 라이브=replay 결정성.
- **CLI(`tiw/cli.py`+`tiw/__main__.py`)**: `python -m tiw run [--live|--replay] [--internal|--client] [--approve-demo] --company … --question … --out …`. `python -m tiw.eval` 독립 보존.
- **데모(`tests/fixtures/company/A제조_2026.json`)**: 제조업 법인(TB 4계정·전기신고·자료 수집/없음/모름/결손·L3 사내메모).
- **검증**: pytest 210 · 슬라이스 회귀 0(①90.5②97.3③96.8④93.5⑤92.3⑥100) · replay 결정성(라이브=replay doc.xml 내용 동일, sha `01775e`) · 신규 fixture secret 0 · **L3 메모 외부 LLM 송신 0(독립 스캔 확인)** · 비-데모 주쟁점(지급이자/기부금)에 접대비 서사 누출 0(독립 probe + 회귀테스트).
- **codex 독립 리뷰(P0×3 + P1×3 전부 반영)**: **P0-1** `validate_draft_package`가 `_render`에서만 호출 → write_docx=False 우회 → **assemble 직후 무조건 호출**(OUT-003 항상 강제). **P0-2/3** `_run_internal_rag`/`_run_web`의 broad `except Exception`이 replay fixture·격리·인용 실패를 silent degrade로 은폐 → **replay 모드는 무조건 전파(fail-closed) + `_NEVER_SWALLOW`(IsolationError/CitationVerificationError/TenantBoundaryError)는 모든 모드 미삼킴**, live 운영성 실패만 degrade. **P1-1** web SILENT contribution `client_id="client_eval"` 하드코딩 → `company.client_id`(테넌트 일관). **P1-2** `_unresolved_conflicts` 무조건 하드코딩 충돌 주입 → **주쟁점이 실제 기업업무추진비일 때만 승격**(쟁점 범위 밖 무관 충돌 주입 차단). **P1-3** private `wf._build_release_proof` 직접 호출(감사 우회) → 공개 `wf.produce_client_deliverable`(교차테넌트 차단+미승인 재검증+`record_release` 의무감사) 경유 후 proof 반환. codex 종합: 인용 날조/grounding/L3 격리/HITL fail-closed **불변식 유지 확인**. 회귀테스트 3건(`test_out003_validation_runs_even_without_docx`·`test_replay_failclosed_on_isolation_error`·`test_replay_failclosed_on_fixture_failure`).
- **codex stop-time 추가 적발 — 잘못된 법리 요약 클래스(2라운드 반영 완료)**: 오케스트레이터가 데모(기업업무추진비/접대비) 서사를 **여러 곳에서 무조건 출력** → 주쟁점이 다른 비-데모 입력에 **잘못된/불일치 요약** 출력 위험. 1차+2차로 전부 제거:
  - exec_summary/conclusion/recommended_order → `_summary_texts(company, primary, answered_channels)` 로 추출, **실제 주쟁점에서 도출**(접대비 전용 절=예규·심판례·증빙 부인 범위는 주쟁점이 기업업무추진비일 때만).
  - **stance**·**`_risks` 과세논리 제목** → 주쟁점 도출(데모 기업업무추진비는 녹화 fixture 키/결정성 보존 위해 동일 문자열 유지).
  - **거짓 웹 회수 주장 차단**: exec_summary 의 "3소스 독립 회수"가 웹 보류 시에도 ③웹을 주장 → **실제 응답 채널(answered_channels)만 정직 기술** + 미응답 시 "③공식웹은 적용 공식근거 없어 보류" 고지.
  - **`_evidence_requests`** 고정 4항목(승용차·접대비 무조건) → **식별된 쟁점별 증빙 + 공통 거버넌스**로 빌드.
  - **`_spot_issues`** 가 질문 무관하게 기업업무추진비 주쟁점 고정 → **질문이 명시한 쟁점을 주쟁점으로 승격**(`_ISSUE_QUERY_TERMS`; 데모 질문은 기업업무추진비 명시 → 동일).
  - **지급이자 절세기회 템플릿** 추가(validate ≥1 opportunity 충족 → 지급이자 단독 matter 도 정상).
  - 회귀테스트 5건(요약 누출0·심화절 유지·웹 정직·증빙 쟁점일치·질문→주쟁점). **codex 재검증 STILL-LEAKS 지적 전부 해소**. pytest **210**, 데모 결정성 유지(sha `01775e`), 슬라이스 회귀 0.
  - **3라운드(draft.py 섹션 헤더)**: 11목차(v1.0 당시) §8 고정 헤더 "관련 법령·예규·판례 근거"가 **예규/판례를 무조건 표기**(데모조차 법령+웹만 인용 → 과표기) → **"관련 법령·근거 자료"**(법령·예규·판례·웹 포괄, 실제 인용만 본문 나열)로 정정. 백엔드(REQUIRED_SECTIONS·validate)·프론트(DraftScreen·fixture·Playwright)·테스트 동기 갱신. **pytest 210 + Playwright 3 passed**. codex 최종 STILL-LEAKS의 유일 잔여 항목 해소 → **SUMMARY-SAFE**.
  - **4라운드(비-데모 replay 경로 fail-closed UX)**: 질문→주쟁점 승격 후, replay 에 녹화 안 된 질문/쟁점(예: 지급이자)은 LLM fixture 부재로 **raw traceback(exit 1)** 노출 → CLI 가 transport fail-closed(`LLMError`/`LawSourceError`/`WebSearchError`/`Embedding*`)를 잡아 **명확한 안내 + exit 2**로 변환(데모는 질문 없이 결정적 실행, 새 질문은 `--live`). 잘못된/합성 답을 만들지 않고 산출물도 미생성. **codex 재검증 2차 잔여 2건 반영**: (1) Orchestrator 생성자를 try 밖→**안으로 이동**(live 키 부재 등 구성 시점 오류도 친화 exit 2), (2) `_REPRO_ERRORS` 외 예기치 못한 예외(비-repro RuntimeError 등)도 **catch-all 로 깔끔히 exit 1**(raw traceback 전면 금지). 회귀테스트 4건(비-데모 replay→exit2·산출없음 / 데모 replay→exit0·DOCX / live 생성실패→exit2 / 예기치못한 오류→exit1·traceback 없음). **pytest 214 passed**.

## 7 Vertical Slice 점수표 (RubricResult 기준 — 이번 iteration `python -m tiw.eval` 산출)
> ⑦은 v1.1 신규 — **미구현(<90)** 이므로 7-slice 완료 게이트 **미충족**. ①~⑥은 PASS 유지(회귀 0 강제).
| # | Slice | 점수 | 하드게이트 | 상태 |
|---|---|---:|---|---|
| ⑥ | 테넌트 격리 | **100** (min over 4 cases) | 누수0 (TENANT_LEAK 미발생) | **통과 (≥90)** |
| ① | 법령MCP 앵커 답변 | **90.5** (min: PUB-001=100·PUB-002=96.8·HID-001=90.5) | 0 (TEMPORAL/FABRICATED/NOT_REPRO/MISSING_WARNING 미발생) | **통과 (≥90)** — judge 연결 + codex 하드닝(결정적 entailment·추상 프롬프트). 분모 79(conflict/security는 ④/⑥) |
| ② | citation 검증 RAG | **97.3** (min: PUB-001=100·PUB-002=97.3·HID-001=97.3) | 0 (TENANT_LEAK/FABRICATED/TEMPORAL/NOT_REPRO/MISSING_WARNING 미발생) | **통과 (≥90)** — 실 Chroma 테넌트 격리(누수0) + 구조분할 + 실 임베딩(model2vec) replay + judge. 분모 93(conflict는 ④) |
| ③ | 공식소스 Web run | **96.8** (min: PUB-001=100·PUB-002=97.2·HID-001=96.8) | 0 (FABRICATED/TEMPORAL/NOT_REPRO/MISSING_WARNING 미발생) | **통과 (≥90)** — Tavily 실 wiring(공식도메인 발견·RECORD/REPLAY) + Source Policy(사전/사후) + 승격(WEB-011, 법령 원문 대조) + WEB-012(최신성⟂적용시점 분리) + slice① 생성기 재사용(채널③/WEB). 분모 79(conflict는 ④·웹은 공유 L0 보안은 ⑥) |
| ④ | 충돌 케이스(3소스 종합) | **93.5** (min: PUB-001=93.5·PUB-002=100·HID-001=96.4·HID-002=100) | 0 (FABRICATED/TEMPORAL/NOT_REPRO/MISSING_WARNING 미발생) | **통과 (≥90)** — 결정테이블(권위·시점·사실·채널 tie-break) + claim 단위 정합 + 인용 상속(신규 0) + lineage 100%. conflict(7) 차원 측정(①②③에서 N/A였던 차원)=100. 분모 77(search per-source·security는 ⑥) |
| ⑤ | CPA HITL 워크플로 | **92.3** (min: PUB-001=100·PUB-002=92.3·HID-001=95.2) | 0 (UNAPPROVED_RELEASE/MISSING_WARNING/TENANT_LEAK 미발생) | **통과 (≥90)** — H1~H5 게이트·승인 전 FinalMemo/고객본 차단(contract proof + 감사로그 이중)·검토항목 자동·graceful degrade·ReviewHistory 해시체인 |
| ⑦ | 다세목·투명성(`ORCH-015`·`OUT-007`·`OUT-008`/`HALU-015`) | **미구현(<90)** | — (하버스 slice7 미작성) | **미충족** ★v1.1 신규 — 세목 레지스트리 + 채널별 독립표시 + 추론·법령추적 도식. 이번 미션 타겟. |

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

프론트 목업 3화면(Intake챗·선택지비교표·DOCX미리보기): **완료** — `frontend/`(Vite+React+TS), 백엔드 산출 fixture 렌더, Playwright 3 passed(스크린샷+텍스트/테이블/근거링크 assertion). DOCX Draft: `src/draft.py`(11목차(v1.0 당시), OUT-002/003/004/006 — 무인용 단정 금지·고객본 미승인 차단·필수섹션 강제), slice①Citation·④SynthesisOpinion·⑤review_items 연계. pytest 184 passed.

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
