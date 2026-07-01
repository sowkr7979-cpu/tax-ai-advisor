# TIW Ralph Loop — STATUS (진행 원장)

> 매 iteration 시작 시 이 파일 + `git log --oneline -15`를 먼저 읽는다. (PROMPT.md §3.1)
> 점수는 **STATUS 자기보고가 아니라** 같은 iteration의 `pytest -q` + `python -m tiw.eval` 산출 `RubricResult`로만 증명된다(완료 판정 기준).

## ☆ 라이브 백엔드 (2026-07 추가 — 실제 LLM 인테이크·전 세무거래·파일분석)
> 정적 데모의 한계(규칙기반·4대 거래)를 넘어, **실제 Claude + 기존 엔진**으로 동작하는 백엔드 앱. **하이브리드**(정적 데모 유지 + 라이브).
- **`web/backend/`**(FastAPI): `app.py`(라우트+정적서빙), `intake.py`(LLM 동적 인터뷰+finalize), `llm.py`(anthropic 직접호출·.env로더·**tool-use 구조화출력**·temperature 미전송), `files.py`(Excel/CSV/PDF 추출: openpyxl·fitz), `run.py`(런처). 실행: 레포루트 `python -m web.backend.run` → `http://127.0.0.1:8000/`(소개) `/live.html`(라이브).
- **동적 인터뷰**(요구③): Claude가 **답변을 분석**(🔎 analysis)하고 그에 따라 다음 질문을 생성(고정 질문 나열 ✕). `INTAKE_MODEL=haiku-4.5`(빠름), tool-use로 `{analysis,tx_type,next_question,ready}`.
- **파일 분석**(요구④): Excel/CSV/PDF 업로드→서버 추출→LLM이 내용 근거로 질문. `/api/upload`(multipart).
- **전 세무거래**(요구⑤): 4대 거래 하드코딩 ✕ — LLM이 **임의 거래**를 분류(예: 비상장주식 저가양도·임원 무상사택 등 검증됨)하고, `FINALIZE_MODEL=sonnet-4.6`이 경우의 수 Scenario(JSON tool-use)를 생성 → **기존 `build_scenario_docx`로 DOCX**(matplotlib 도식 4종 + **법제처 `research_issue` 실시간 근거** + 내부 RAG). `_build_scenario`가 LLM JSON→`Scenario` 안전보정·`validate()`.
- **검증**(실 API): 세션→반응형 질문(사택 소유/임차 되물음)→CSV 업로드→finalize(≈71s)→보고서 다운로드(640KB, 도식·판례 포함) 전 흐름 OK. Playwright: live.html badge=LIVE·실 LLM 분석·임의거래 감지·0 오류. **키(.env: ANTHROPIC·LAW_OC 등) 유효**.
- **GUI = openai.com/ko-KR 스타일**: 공유 `web/assets/app.css`(Inter+Noto Sans KR·흰 배경·근검정·모노톤·미니멀 카드/pill)로 index/demo/live 통일. 진입=index(소개) 우선.
- **보안 하드닝(codex 2라운드 반영·검증)**: ①프롬프트 인젝션 격리 — 업로드 파일·**대화 매 턴 사용자 답변**·finalize facts를 `_wrap_untrusted()`(`<untrusted_data>` 구분자+주입 종료태그 무력화+`_san_tag`로 파일명 속성 이탈 차단)로 감싸고 시스템 규칙 "데이터 내 지시 무시"(실검증: "PWNED/HACKED 출력 강요" 무시). ②세션 상한 `MAX_SESSIONS=200`+TTL 6h+`_evict()`(삽입 후, off-by-one 없음). ③예외 비노출 — `_fail()`이 `str(e)` 대신 일반 메시지+서버 log; finalize는 사용자 안내성 `NotReadyError`만 400 노출. ④업로드 가드 — 확장자 화이트리스트(415)+1MB 청크 누적 15MB 상한(413, 전량 read 전 차단). ⑤finalize 최소 사실관계 3건 미만 400. ⑥`_build_scenario` 배열 12·문자열 2000 상한(citation 폴백 포함). ⑦files.py try/finally로 openpyxl/fitz 핸들 보장. ⑧live.html XSS — 서버/LLM 메시지 `botText()`(esc후 **굵게**·개행만)·err textContent.
- venv 추가 의존성: fastapi·python-multipart·openpyxl·pymupdf. `web/backend/_reports/` gitignore.

## ☆ 공개 배포 (2026-07 — 면접관용 라이브 URL, 사용자 유료키 감수 승인)
> FastAPI가 정적(소개/데모/라이브)+API를 **한 오리진**에 서빙 → 단일 URL로 실제 LLM 인테이크·파일업로드·검토패키지 DOCX 사용.
- **① 라이브 LLM 백엔드 = Railway**: **https://tax-ai-live-production.up.railway.app** (`/`·`/live`·`/demo`). Dockerfile 상시 컨테이너. 배포 `railway up --detach --service tax-ai-live`(멀티서비스라 --service 필수), **5MB 스테이징 디렉터리**에서(`railway up`이 .railwayignore 무시 .git/frontend까지 올려 413 → 스테이징으로 회피). 키는 `.env`→`railway variables --set`(값 미노출). **⚠ Dockerfile COPY**: `src·rules·web`+**`contract/`**(누락 시 finalize만 `ModuleNotFoundError: contract`; clean-venv가 레포루트서 돌면 못잡음 → **배포 이미지 실측 finalize 필수**).
- **② 정적 = Vercel**: **https://tax-ai-demo-taupe.vercel.app** (프로젝트 tax-ai-demo, `vercel deploy --prod`). 루트 `vercel.json`(outputDirectory=web)+`.vercelignore`(백엔드/기밀/소스 제외). `/live`는 `window.LIVE_API`로 Railway 호출(CORS *). 공개 PDF는 ASCII `intro_KICPA.pdf`(한글 URL 404 회피).
- **공개 안전장치**: 로그인 없이 접근·`LIVE_WITH_RAG=0`(내부 기밀 PDF 미노출·경량)·`LIVE_WITH_LAW=1`(법제처 실근거)·IP 분당+일일 finalize 상한(429). Linux 차트 한글=`KOREAN_FONT_PATH`(fonts-nanum).
- **배포 산출물**: `Dockerfile`·`requirements-deploy.txt`(chromadb/model2vec 제외)·`.dockerignore`·`render.yaml`·`.railwayignore`·`vercel.json`·`DEPLOY.md`. CLI 인증은 사용자 `! vercel login`·`! railway login`(브라우저 1회).
- **실측 E2E 검증**: `/live` 200·동적 인터뷰·finalize 200·**DOCX 531KB**(경우의수·법제처 실근거). clean-URL 라우트(`/live`·`/demo`·`/index`)·분석버튼 게이팅(사실관계 3개 미만시 안내)·에러 detail 표시 수정 반영.
- **비용**: Railway 상시 실행 사용량 과금 + Anthropic 인터뷰당 소비(승인). 미사용 시 Railway 서비스 일시정지 가능.

## ☆ 최신 산출물 (2026-07 업데이트 — 소개·시연·지원자료)
> 코드 엔진 변경 없음(회귀 0). 외부 소개·시연·이직 지원용 산출물 추가 + 설계서 최신화.
- **KICPA용 프로젝트 소개 PDF**: `scripts/build_project_intro_kicpa_pdf.py` → `세무AI_프로젝트소개_KICPA용.pdf`(10p, ~0.9MB). PyMuPDF·malgun **폰트 서브셋**·이미지 다운샘플·실차트(`산출물/_charts_case`) 임베드. ⚠ 루트 파일이 뷰어로 열려 있으면 잠금(Permission denied) — 닫고 재생성. `KICPA_PDF_OUT` env로 출력경로 override 가능.
- **이력서용 정적 랜딩 + 실제 동작 데모** (`web/index.html`·`web/demo.html`, **openai.com/ko-KR 스타일** 공유 `web/assets/app.css`: Inter+Noto Sans KR·흰 배경·근검정·모노톤·미니멀 카드/pill — index/demo/live 통일). **포지셔닝(정정)**: 데모는 표준 형식을 보여주는 **3~4쟁점 예시**일 뿐, 시스템은 **모든 세무거래**를 검토(내부 RAG DB 부족분은 **law.go.kr API·판례/예규/세무질의 웹리서치**로 보강). index 지표=전 세목(법인세·소득세·부가·상증·양도 등)·모든 거래·3중 검증. 데모 = **사실관계 인터뷰 챗봇**: 답변 내용에 **반응**(인용 ack + 금액·특수관계·시가·증빙 프로브)하며 최소 20문항 인터뷰(중단 시까지). **거래유형 감지 일관성(강화)**: Q1 답변에서 감지·표시하고 감지·심화질문·분석이 항상 동일 거래에 맞춰짐 — `maybeSwitchType`은 **Q1 거래 계속 검토가 원칙**이며, 부수 언급(`ASIDE`)·**우연한 다른-거래 키워드 동시등장(예: 상여 검토 중 '잉여금·감자·주식 취득')은 전환하지 않고**, `SWITCH_CUE`(사실은·정정·아니라·변경 등) 또는 `saysTransaction`(새 거래 키워드+거래/검토/취득 지정어 근접)로 **명시적 재지정**할 때만 심화슬롯 재주입하며 전환. 슬롯(미답 주제만)+프로브, 부정 인식 `hasNeg`, `inferGate` pass/risk. → **검토 패키지 보고서 .docx**: **실제 scenario_report 형식**(사실관계 전문·게이트 분석·경우의수 매트릭스·권고·절세 대안비교·사후관리/실행계획·분개·근거법령·분개장/원장 부록) + **모든 시나리오에 도식 4종 임베드**(`[그림1]`플로우차트·`[그림2]`매트릭스·`[그림3]`대안비교 그래프·`[그림4]`실행 타임라인). **차트는 `scenarios.js`에 base64 data URI로 내장**(export가 `산출물/_charts_scn`→base64) → **서버(fetch) 없이 file:// 더블클릭으로도 도식 임베드**(`dataUriToBytes`→ImageRun, `imgDims` 비율 보존; 폴백 `.doc`는 base64 `<img>`). docx UMD(CDN `docx@8.5.0`), scenarios.js ≈1.7MB. Playwright 검증: 감지=Q1 일치·전환 동작·EXECPAY 게이트 정확(D1충족/D2위험/D3위험)·docx 이미지 4·전 섹션·XSS 미실행. codex: parse 오류 없음.
- **React 목업 확장**: `frontend/src/screens/OverviewScreen.tsx` + `App.tsx` 라우트 `overview`(기본). 기존 playwright는 `#/intake|strategy|draft` 명시 이동 → 회귀 없음. `npm run build` OK.
- **설계서 최신화**: 정본 `md 파일/법인세_세무AI_설계서_통합.md` §0-A 신설 + HTML 재생성(`build_unified_html.py`), `docs/README.md` 현황, `md 파일/면접_질답…` 보조자료 포인터.
- **이직 지원자료**: `md 파일/Big4_Tax_자기소개서_면접가이드.md`(지원동기·Career goal 각 ~1,000자 + 면접 Q&A·시연 동선·학습포인트).
- 매 단계 codex 리뷰 진행.

## ★ 미션 v1.1 (변경①②③) — slice ⑦ 진행 중 (완료 게이트 미충족)
> **★ 미션 완료(v1.1)**: slice ①~⑦ **전부 PASS**. **`python -m tiw.eval` = 7/7** (①90.5 ②97.3 ③96.8 ④93.5 ⑤92.3 ⑥100 ⑦100, **하드게이트 0**). **완료 promise 3대 조건 모두 충족**: ✅ pytest 231 clean · ✅ 7 슬라이스 ≥90 + 하드게이트 0 · ✅ 목업 3화면 Playwright 3/3. slice⑦ requirement 는 **사용자 키로 소득세 end-to-end fixture(소득세법 제22조 법령·LLM·임베딩) 녹화 → 비-법인세 파이프라인=PACKAGE** 로 정식 채점(iter15). `<promise>ALL_SLICES_90</promise>` 충족.
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

### iter8 (f469ec4 이후) — §10 trace 정합 검증 강화 (HALU-015, codex 적발)
- **codex stop-time 적발**: "§10 trace validation accepts fabricated/stale trace data" — §10 검증이 `steps≥1 + law_trace≥1`(존재)만 확인 → 패키지에 없는 조문/pinpoint 를 든 **날조/stale trace 도 통과**(사후 서사 = HALU-015 위반).
- **수정**: `validate_draft_package` §10 에 **정합 검증** 추가 — law_trace 항목·추론단계가 *드는 인용(locator)* 이 실제 패키지 인용(`data.citations`) ∪ 채널 결과 인용으로 **backed** 되어야 함. 미backed → `DraftValidationError`(표시 차단, fail-closed).
- **측정**: **pytest 225**(223 + 신규 2: 날조 law_trace→reject / 날조 step 인용→reject). orchestrator/데모 trace 는 실제 Citation 에서 빌드 → 통과(회귀 0).
- **codex 미해결 → 해소**: 날조/stale trace 적발 반영 완료. (HALU-015 "사후 서사 금지" 검증으로 강제.)

### iter9 (0ce851f 이후) — §10 law-trace 빈 locator 우회 차단 (HALU-015 codex 후속)
- **codex 적발**: "§10 law-trace validation still allows unbacked rows with empty locator" — 빈 locator 행이 `if e.locator` 가드로 검사 skip → 미backed 날조행 통과.
- **수정**: 모든 law_trace 행이 **locator(pinpoint) 또는 (법령명,조문) 쌍**으로 backed 되도록 강제(빈 locator skip 제거). `_known_pairs`(citation source_locator 파싱)로 (법령,조문) 매칭.
- **측정**: **pytest 226**(225 + 신규 1: 빈 locator 소득세법 제22조 날조행→reject). 실제 trace 는 locator 보유 → 통과(회귀 0).
- **codex 미해결 → 해소**(누적 codex 적발 4건 전부 반영: 오법조회·부분커버리지·날조trace·빈locator우회).

### iter10 (32a47cc 이후) — §10 law-trace stale non-empty locator 차단 (HALU-015 codex)
- **codex 적발**: "§10 law-trace validation now lets stale non-empty locators pass" — OR 로직이 locator 가 stale/오기여도 (법령,조문) 쌍만 맞으면 통과.
- **수정**: locator 가 **있으면 엄격히 `_known_loc` 검증**(불일치=reject), **비어 있을 때만** (법령,조문) fallback. pair fallback 의 stale 누출 차단(backing 로직 exhaustive: 비어있지않음→정확매칭 / 비어있음→pair).
- **측정**: **pytest 227**(226 + 신규 1: stale non-empty locator→reject). 실제 trace locator 는 정확 매칭 → 통과(회귀 0).
- **codex 미해결 → 해소**(누적 5건: 오법조회·부분커버리지·날조trace·빈locator우회·stale-locator).

### iter11 (4673b42 이후) — slice7 하버스 추가 + 7/7 슬라이스 ≥90 측정
- **slice7 하버스**(`tiw/eval/slices/slice7_multitax_transparency.py`): gold 파일 없이 *자체 결정적 케이스* 로 3 기능 채점 — **requirement**(ORCH-015 다세목 라우팅: 법인세→법인세법·소득세→소득세법·미등록→None + 13목차) · **citation**(§10 trace 전부 backed=날조/stale 0) · **output**(§8 채널 ①②③ + §10 도식 + 13목차) · **ops**(완주). 분모 29, 판단차원 N/A(①~⑥ 행사).
- **runner/__main__ 등록**: `_REGISTRY[7]` + 글리프 ⑦ + 7-slice 요약.
- **적대적 정직성**(`tests/test_slice7_harness.py`, slice⑥ leaky-store 패턴): `package_factory` 주입점으로 날조 trace→**FABRICATED_CITATION(cap60)** · 날조 step 인용→FABRICATED · 산출실패→**NOT_REPRODUCIBLE(cap75)** 를 *같은 채점 경로* 로 적발('측정 못 함=만점' 금지).
- **측정**: `python -m tiw.eval` → **7/7 슬라이스 완료게이트 통과**(①90.5②97.3③96.8④93.5⑤92.3⑥100⑦100, 하드게이트 0). 기존 ①~⑥ 회귀 0. **pytest 231**(227+4).
- **정직성 고지**: slice⑦ 100 은 *결정적 구조 채점*(scope_note 명시) — hidden freeze CPA 케이스는 docs/09 §10 절차상 사용자(회계사) 시드 필요(미시드). 판단 품질은 별도.
- **남은 promise 조건**: §5 의 **목업 3화면 Playwright 렌더(§8/§10 프론트)** 미검증 → promise 보류. 다음 iter = 프론트 §8/§10 + Playwright.

### iter12 (297c73a 이후) — slice7 정직성: 비-법인세 파이프라인 실제 행사 (codex 적발)
- **codex 적발**: "slice 7 can falsely pass without exercising the required non-corporate-tax pipeline" — iter11 하버스가 소득세 라우팅을 **registry lookup** 으로만 보고 실제 orchestrator 는 법인세 데모만 돌려, 비-법인세 파이프라인 미행사로 false-pass(100).
- **수정**: `_income_tax_pipeline()` 추가 — 소득세(퇴직소득) 케이스를 **실제 오케스트레이터(replay)에 통과**시켜 라우팅·산출을 측정. 결과: `PACKAGE`(소득세 13목차 산출) / `ROUTING_ONLY`(소득세법 라우팅 정확하나 fixture 미녹화 fail-closed) / `FAIL`(오라우팅). **ROUTING_ONLY → requirement PENDING**(슬라이스 ≥90 불가, 정직).
- **현 상태**: 소득세 fixture 미녹화 → `ROUTING_ONLY` → slice⑦ **PENDING**. `python -m tiw.eval` = **6/7**(①~⑥ PASS). **iter11의 7/7 보고를 정직 정정**(false-pass 였음).
- **측정**: pytest 231(slice7 테스트를 PENDING 정합으로 갱신 + 적대적 적발 유지). 회귀 0.
- **codex 미해결 → 해소**(누적 6건). slice⑦ ≥90 은 **소득세 law/LLM fixture(`--live`/키) 녹화** 후 가능(사용자 키 작업).

### iter13 (19a0906 이후) — 프론트 §8/§10 + Playwright 3화면 (promise 조건 ② 충족)
- **프론트 13목차 정렬**: `DraftScreen.tsx` 가 백엔드 11목차 하드코딩 → **13목차**로 갱신. **§8 출처 채널별 독립 결과**(channel_results 표, ①②③ + SILENT) 신설 · **§10 법령 추적+추론 도식**(10-1 Mermaid flowchart `mermaidFlow()` + 추론단계 표 / 10-2 law-tracing 표) 신설 · §9~§13 renumber.
- **types.ts**: `ChannelResult`/`ReasoningStep`/`LawTraceEntry`/`ReasoningTrace` + `Draft.channel_results`/`reasoning_trace`. **fixture 재생성**(`build_frontend_fixture` → 13섹션·채널 3·trace 8단계·법령추적 4).
- **Playwright**(`mockup.spec.ts`): 화면③ 13목차 TOC=13 + §8 채널 ①②③ + §10 Mermaid(`flowchart`/`SYNTHESIS`)·추론단계(INTAKE)·법령추적(법인세법 제25조) 단언 추가. **`npx playwright test` → 3/3 passed**(스크린샷+데이터 단언).
- **측정**: tsc --noEmit 0 · **Playwright 3/3** · **pytest 231**(백엔드 무변, 회귀 0).
- **promise 진행**: ✅pytest ✅Playwright 3화면 — **유일 잔여 = slice⑦ requirement(소득세 fixture, 사용자 키)**.

### iter14 (f112903 이후) — §10 Mermaid 실제 SVG 렌더 (codex 적발)
- **codex 적발**: "§10 claims Mermaid diagram rendering, but only renders raw Mermaid text" — `<pre.mermaid>` 에 flowchart 소스만 넣고 런타임 부재로 도식 미렌더(claim 과 불일치).
- **수정**: `mermaid` npm 패키지 설치 + `DraftScreen` useEffect 에서 `mermaid.run({nodes:[ref]})` → `<pre.mermaid>` 가 **실제 SVG 도식**으로 렌더(인터랙티브, 하이브리드 프론트). Playwright 단언을 `mermaid svg` visible + 노드 라벨(SYNTHESIS)로 갱신(raw 텍스트 ✕).
- **측정**: tsc 0 · **Playwright 3/3**(§10 실제 SVG 도식 렌더 확인) · pytest 231(백엔드 무변).
- **codex 미해결 → 해소**(누적 7건).

### iter15 (92165cf 이후) — ★ 소득세 end-to-end fixture 녹화 → slice⑦ PACKAGE → 7/7 완료
- **사용자 API 키 제공**(LAW_OC·ANTHROPIC·TAVILY, `.env`) → 비-법인세(소득세) 파이프라인 end-to-end 녹화로 slice⑦ requirement 의 PENDING 해소.
- **녹화**: (a) 소득세법 제22조(퇴직소득) 법령 fixture(`record` — 법인세법 fixture 보존, manifest append) · (b) `tests/fixtures/company/소득세_퇴직소득_2026.json`(임원 퇴직위로금 5억 케이스) · (c) `python -m tiw run --live` 로 LLM gen·strategy·임베딩(48벡터, model2vec) fixture 녹화 → **13목차 DOCX 산출**(①법령+②RAG 종합 2/3). orphan fixture 정리 후 단일 재녹화(재현성).
- **orchestrator 일반화**: `_opportunities` 에 퇴직소득구분 템플릿 + **일반 폴백**(모든 등록 쟁점 ≥1 절세기회 — 다세목 검증 통과). slice7 하버스가 소득세 fixture 를 replay 입력으로 사용(녹화=replay 일치).
- **보안**: 새 fixture **secret 스캔 CLEAN**(sk-ant·LAW_OC·tvly 마커 0; OC redaction). **키는 `.env`(gitignore)만 — 커밋 0.** *(사용자 권고: 트랜스크립트 노출 키 사용 후 rotate.)*
- **측정**: **pytest 231** · **`python -m tiw.eval` 7/7 ≥90 + 하드게이트 0** · **Playwright 3/3** · 소득세 replay 결정성 확인. **완료 promise 3대 조건 전부 충족.**

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
| ⑦ | 다세목·투명성(`ORCH-015`·`OUT-007`·`OUT-008`/`HALU-015`) | **100.0** (requirement·citation·output·ops) | 0 (FABRICATED/NOT_REPRO 미발생) | **통과 (≥90)** ★v1.1 — 비-법인세(소득세) 파이프라인 **PACKAGE**(소득세 fixture 녹화 → 13목차 산출, replay 결정성) → requirement 정식 채점. §8 채널별·§10 추론/법령추적 도식 정합. 적대적 적발: 날조trace→FABRICATED(cap60)·산출실패→NOT_REPRO(cap75). hidden CPA 케이스 미시드(결정적 구조 채점). |

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

## ★ 후속 능력 — 내부 RAG DB 실임베딩 + 3소스 종합 산출물 (2026-06-30, 미커밋)
> 사용자 4요구: ①왜 WEB RESEARCH 미작동 ②`RAG DB/` 폴더 임베딩→벡터DB화 ③사후관리·action·plan 표시 ④가상 분개장·원장 dummy + 전 과정 codex 리뷰 + dummy 후 전 파일 최신화. **pytest 253 passed**(245 + RAG DB 단위 8).
- **① WEB 게이트 진단·수정** (`src/orchestrator.py` `_run_web`): 주쟁점이 기업업무추진비가 아니면 무조건 `None`(제25조 공식소스 fixture 1개만 녹화)이라 다른 질문에 ③웹이 침묵하던 것이 원인. `WebResearchPipeline.run` 자체는 범용. **수정**: `if self.mode!="live" and issue_key!="기업업무추진비": return None`(replay byte-identical → 회귀 0) + **live 에서만 `RecordingTavilyTransport`로 실제 Tavily 가동**.
- **② 내부 RAG DB 실임베딩** (`src/rag_db_index.py` 신규): `RAG DB/` 공개 가이드 PDF 29종(1개 이미지전용 skip)→페이지 청크 10,010건→on-prem model2vec(256d, L2정규화)→**numpy 코사인 인덱스**(`vectors.npy`+`chunks.jsonl`+`manifest.json`, `RAG DB/_index/` gitignore). 초기 chromadb 1.5.9 PersistentClient가 대용량 HNSW 세그먼트를 close 시 flush 안 해(.bin 미생성) 타프로세스 재오픈이 깨져 → 공개 코퍼스(격리 불필요)라 numpy 전환(빌드 ~4분·로딩/질의 빠름·결정적). **fail-closed**: manifest(완료표식·마지막 기록)·벡터·사이드카 + 모델/차원/ndim/shape[1]/dtype + **content hash(원자적 temp+os.replace)** 전수 대조.
- **③④ 통합 산출물** (`src/strategy_plan*.py` 확장): §2 "법령①·내부자료②·공식웹③ 3소스 교차검증 + 종합의견" 신설(`ChannelAnswer`/`ResearchSynthesis`/`RagDbEvidence` + `_render_research` + `_validate` 채널 인용 검증). `attach_rag_db_research`가 **②채널에 실제 RAG 회수 근거(가이드 파일·페이지) 부착**(없으면 보류·침묵). 사후관리·필요조치·자료(§9)·실행 로드맵=미래 plan(§10)·가상 계정별원장(§6)·분개장(§7) dummy. **14목차**(§2 삽입·번호 재정렬). 생성기 `scripts/build_comprehensive_review.py`. 데모=리노공업㈜.
- **codex 4라운드 리뷰 반영**: (1)load_index `_chunks` 대입·SHARED 회수·시점필터 검토 (2)채널매칭 `ch.channel=="②내부RAG"`→`authority=="실무서"`(replace_all 들여쓰기차로 1곳만 치환→**실RAG근거 누락 치명버그**)·핸들누수 finally·note 영어"RAG DB" 제거 (3)load_index 부분실패 핸들누수→`close_index` (4)numpy: 원자쓰기+content hash·shape/ndim/dtype·negative top_k 가드. **테스트**: `tests/test_rag_db_index.py`(8)+`test_strategy_plan_report.py`(+2: 3소스 섹션·degrade). 영어0 주의: `_ko()`가 'DB'·'fail-closed'·'TIW'는 미치환→한글 작성.
- **전 파일 최신화**: 정본 §3-4-2 신설(`md 파일/…통합.md`)+HTML 재생성(`build_unified_html.py`, Claude/ 미러 삭제 대응 skip 가드)+`pyproject.toml` adapters에 `pypdf`·`numpy` 추가+메모리([[tiw-tax-ai-design]]).

## ★ 후속 능력 — 전(全) 코퍼스 OCR 임베딩 + '경우의 수' 절세전략·세무리스크 의사결정 보고서 (2026-07-01, 미커밋)
> 사용자 추가요구: ①`(2025) 세법해석 사례집.pdf`까지 **전 PDF 임베딩**(스캔본 OCR) ②실무서 서평(법인관리·세금폭탄·절세전략·세무리스크) 같은 **분기적 사고방식**으로 '경우의 수'별 절세전략·세무리스크 추론 ③이를 **플로우차트**(최우선)로 직관화 ④반영한 **dummy 산출물**. 매 단계 codex 리뷰. **pytest 263 passed**(253 + 시나리오 10).
- **② 전 코퍼스 OCR 임베딩** (`src/rag_db_index.py` 확장): 스캔(이미지전용) PDF 2종(세법해석 사례집 256p·첨단산업 안내 58p)은 텍스트 레이어 0 → **온프렘 OCR 폴백** 추가: `_find_ghostscript/_find_tesseract/_find_tessdata` 도구 탐색(PATH+표준경로 glob) → `_ocr_pdf`(Ghostscript로 전 페이지 그레이스케일 PNG 1회 렌더 → 페이지별 Tesseract `-l kor --psm 3`, 외부 전송 0) → `extract_chunks`가 pypdf 추출 0건 PDF에 OCR 폴백(출처 `(OCR)` 표시). **arity 변경**: `extract_chunks(return_skipped=True)` → `(chunks, skipped, ocr_files)` 3튜플(유일 호출자 `build_index` 갱신, manifest `ocr_files` 기록). **결과**: 31 PDF 전부 색인(이전 29+skip2 → **skip 0**), 7,562 페이지청크 → **10,304 청크**(+294 OCR). 도구: winget Tesseract 5.4 + tessdata_best `kor.traineddata`(11.9MB, `~/tessdata`) + 기존 Ghostscript 10.01. OCR 품질 양호(사례집 회신문·예규번호·판례번호 정상 인식).
- **②③④ '경우의 수' 의사결정 보고서** (신규 4파일): 실무서의 분기적 사고를 **데이터 구조**로 옮김 — `src/scenario_planner.py`(`Scenario`=거래/사건; `Gate`순차분기·`Leaf`경우의수별 결론[위험등급·세무리스크·절세전략·근거]·`PlanStep`·`JournalIllustration`; `validate()`로 게이트≥2·경우≥2·위험등급 허용값·**근거 필수(날조방지)** 강제; 데모 3종=비상장 자기주식 취득·임원 보수/퇴직금·가지급금, **붙여준 서평 미복제·동일 사고로 원본 추론**) → `src/scenario_flowchart.py`(matplotlib **세로 의사결정 spine + 리스크 옆분기** 플로우차트 + 경우의수 매트릭스 PNG; 주황 마름모=판단·빨강=리스크·초록=정상종결; 영어0·Noto Sans KR) → `src/scenario_report.py`(회계사용 DOCX: 방법론→[시나리오별: 플로우차트·매트릭스+표·권고·**사후관리/필요조치/실행계획**·**분개 예시**·내부RAG 근거·근거법령 하이퍼링크]→**부록 분개장·총계정원장 dummy**(대차 일치 검증); `cpa_report` 헬퍼 재사용; `_rag_evidence`로 내부 색인 회수[미가용시 degrade·날조금지]; 근거링크=국가법령정보센터 **검색**[조문ID 임의합성 금지]). 생성기 `scripts/build_scenario_dummy.py`·인덱스 빌드 `scripts/build_rag_db_index.py`. 데모=가나다정밀㈜. 산출물=`산출물/가나다정밀_경우의수_절세전략_세무리스크_의사결정보고서.docx`.
- **요구사항 매핑**: ③사후관리·필요조치·실행계획 = 시나리오별 §N-4 + 내부RAG 회수 근거가 자본거래 실무사례·임원퇴직금 손금산입·업무무관 가지급금 가이드에 정확 매칭. ④분개장·원장 dummy = 부록 A/B(권고 경로 분개 집계·계정별 잔액·대차일치).
- **테스트**: `tests/test_scenario_planner.py`(11: 구조무결성·권고=안전·validate fail-closed 5종[공백근거 우회 차단 포함]·플로우차트/매트릭스 렌더·검색URL·DOCX 산출[이미지6·부록·사후관리]). 영어0 주의: `_ko()`가 D1/D2/D3·금액 미손상 확인.
- **codex 리뷰(라운드1)**: scenario_planner basis 공백 우회 차단(`all(str(b).strip())`)·rag_db OCR returncode fail-closed(`OcrError`→PDF skip, 부분 성공 위장 금지)·flowchart 0-게이트 가드·build_rag_db_index `--dpi` 스레딩. 전부 반영.

### ★ DART 실재무 그라운딩 — 종합세무검토 + 회사 [사실관계] 의사결정 보고서 (2026-07-01, 미커밋)
> 사용자 추가요구: **DART API 로 임의 dummy 회사**의 절세전략·세무리스크 의사결정보고서(**종합세무검토 포함**) 생성. 분개장·계정별원장·증빙은 **임의(가상) 생성**, **[상황]→[사실관계]** 로 바꾸고 [사실관계]도 임의 생성해 추론. **pytest +6**(test_dart_case).
- **DART 실연동** (`src/dart_fetch.py` 신규): OpenDART `corpCode.xml`(zip)→회사명/종목코드↔corp_code 매핑(캐시 `tests/fixtures/dart/corp_code_map.json`, **12MB gitignore**) + `fnlttSinglAcntAll.json`→`CompanyFinancials`(BS/IS 라인). **키는 `.env` DART_API_KEY 에서만 읽고 캐시/픽스처에 미저장**(URL 제외, 응답 본문만 캐시; secret 스캔 0 확인). OFS 비면 CFS 폴백. 재무 fixture(소형 105KB)는 커밋(replay 재현).
- **회사 그라운딩 보고서** (`src/dart_case_data.py` 신규 + `scenario_report.build_company_case_docx`): DART 실수치(데모=**한미반도체 FY2024 연결**: 자산7,109억·이익잉여금6,100억[자본금127억의 48배]·매출5,589억·영업이익2,554억·순이익1,526억)→ **① 회사개요 ② 종합세무검토(재무제표→잠재 세무쟁점 6行: 잉여금환원·임원보수·가지급금·R&D공제·접대비·업무용차량) ③ 시나리오 4종**(자기주식·임원보수·가지급금 = demo 재사용 + **[사실관계] 합성**[실수치 맥락]; **신규 R&D 세액공제** 시나리오=조특법 제10조·신성장구분·당기/증가분·최저한세 분기, 절세 positive) **④ 부록 분개장·총계정원장·증빙목록 dummy**. [상황]→**[사실관계]** 라벨(플로우차트 시작박스 포함). 재무수치만 실값·그 외 분개/증빙/거래사실은 가상(dummy) 명시. 생성기 `scripts/build_dart_case_report.py`(`--company`/`--year`/`--fs`). 산출=`산출물/한미반도체_종합세무검토_경우의수_의사결정보고서.docx`(22쪽).
- **테스트** `tests/test_dart_case.py`(6: 실수치 개요·종합검토行·시나리오4 grounding·R&D positive·DOCX[종합검토·증빙·[사실관계]]). 합성 CompanyFinancials 로 **네트워크 0**.

### ★ 시나리오별 Tax Plan + 법제처 판례·해석례 실조회 + RAG 회수사유·일치검토 (2026-07-01, 미커밋)
> 사용자 추가요구(강제): ① 각 시나리오에 한맥 수준 **TAX PLAN(대안별 요지·추가세부담·장단점)** + **실행 타임라인(시점 최적화)을 [실행계획]에** 포함 ② **korean-law API 는 법령만이 아니라 최신 예규·판례·질의해석까지 검토** ③ 내부 RAG 는 **왜 회수했는지 상세 설명 + 현재 내용과 일치하는지 세밀 검토** ④ 필요 자료는 가상 생성. **pytest +1**(Tax Plan 대안).
- **① Tax Plan(대안 비교)**: `scenario_planner.PlanAlt`(대안 요지·추가세부담(가정 억)·장단점·권고) + `Scenario.alternatives`. 시나리오마다 대안 3종(예: 자기주식 소각/현금배당/유상감자) — **권고 대안 = 최저 추가세부담**(일관성). 렌더 `N-4. Tax Plan` 표 + `scenario_flowchart.save_burden_bar`(추가세부담 비교 막대, 권고 강조). **실행 타임라인**: `save_plan_timeline`(시점·행위·효과 세로 도식)을 `N-5 [실행계획]`에 삽입.
- **② 법제처 판례·해석례 실조회** (`src/law_open_api.py` 신규): DRF `lawSearch.do?target=prec|expc|law` 키워드 조회 → `LawHit`(제목·번호·일자·출처·링크). **OC 키 redact**(응답 상세링크가 OC echo → `content.replace(oc,'***')` 후에만 캐시/링크; 캐시 `tests/fixtures/law_open/` secret 0 확인). `research_issue`가 판례+해석례+법령 동시 조회(target별 degrade). 렌더 `N-8. 관련 판례·해석례·법령(법제처 실시간)` — **실제 회수만**(날조 0), 0건/오프라인은 '조회 불가' 정직 표기. 실측: 가지급금→대법원 2025두34068(2025.09), 자기주식→서울고법 2014누66344 등 **최신 실판례** 회수.
- **③ RAG 회수사유·일치검토**: `_rag_evidence`가 passage별 **회수 사유**(질의어 매칭 토큰·코사인 유사도) + **일치 검토**(`_scenario_key_terms` 핵심어 겹침 → 직접관련/배경참고/참고만 판정, 겹친 핵심어 명시, ‘키워드 1차판정·원문 의미는 회계사 확인’ 고지)를 반환. 렌더 `N-7`. **fail-closed**(미가용 [] + stderr 고지).
- 렌더 `_render_scenario` 9소절(플로우차트·매트릭스·권고·**Tax Plan**·**실행계획+타임라인**·분개·**RAG 사유/일치**·**판례/해석례**·근거법령). `with_law` 토글(테스트 네트워크 0). 두 산출물 재생성(가나다 22쪽·한미반도체). 매 단계 codex 리뷰.

## 빌드 환경 메모
- 스택: Python 3.11+ (검증: 3.14.4). 핵심 deps = `pydantic>=2.7`+`pyyaml`(결정적 경로). 어댑터(fastapi/anthropic/chromadb/model2vec/numpy/pypdf/python-docx)는 `[adapters]`/`[api]` extra — slice⑥ 테스트는 실키·heavy wheel 없이 통과(내부 RAG DB 실임베딩만 model2vec+pypdf+numpy 필요).
- 실행: `pip install -e .` → `pytest -q` → `python -m tiw.eval --slice 6`. (Windows cp949 대응: CLI가 stdout을 UTF-8로 reconfigure.)
- 외부 의존성: 실연동(Korean-law-MCP·Tavily·Brave·LLM·DART) + 응답을 `tests/fixtures/` SourceSnapshot으로 녹화. **OCR은 내부 RAG DB 스캔본 ingestion 경로에 실(實) wiring**(온프렘 Ghostscript 10.01 + Tesseract 5.4 `kor`(tessdata_best, `~/tessdata`); `src.ai.ocr_client` 어댑터 스텁과 별개로 `src/rag_db_index._ocr_pdf`가 실제 동작). 그 외 채널 어댑터는 slice①~⑤에서 연결.
- 격리 핵심: `src/vector_store.py` 가 client별 파티션 ⟂ SHARED 파티션을 **물리 분리**, 스코프 검색은 자기 파티션(+SHARED)만 순회 → 타사 파티션 미접근. `TenantScope` 필수 인자(SEC-002, 끌 수 없음).
- codex review gate: 활성(매 iteration stop 전 fresh 리뷰).
