# PROMPT.md — TIW Ralph Loop 빌드 드라이버

> 이 파일은 Ralph loop이 **매 iteration 동일하게 읽는 단일 지시서**다.
> 점수를 올리려고 이 파일이나 채점 로직(`docs/09`, `tests/golden/`, rubric scorer)을 **절대 수정하지 마라**. 그것은 메트릭 게이밍이며 실패다.
> 너의 이전 작업은 파일·git history·`STATUS.md`에 남아 있다. 매번 그것을 먼저 읽고 **가장 약한 곳을 한 걸음 전진**시켜라.

---

## 0. 미션 (불변)

`md 파일/법인세_세무AI_설계서_통합.md`(서사 정본)와 `docs/01`~`docs/09`(규범 명세)를 스펙으로 삼아,
**Tax Intelligence Workspace(TIW)** 를 **Python**으로 greenfield 구현한다.
외부 의존성(Korean-law-MCP, Tavily/Brave, LLM, DART, OCR, DOCX)은 **실연동**하되, 응답을 `SourceSnapshot` 픽스처로 녹화해 **결정적 회귀**를 보장한다.

**완료 = 6개 vertical slice가 각각 rubric ≥ 90/100 + 하드게이트 위반 0 + 프론트 목업 3화면 렌더.**

---

## 1. 정본 스펙 (우선순위 순)

1. **규범 명세 (정본)**: `docs/01`~`docs/09`, `docs/README.md` — FR-ID(SEC/PROV/INTK/RAG/WEB/API/HALU/ORCH/AGT/OUT/NFR)가 진실의 원천.
2. **서사 설계서**: `md 파일/법인세_세무AI_설계서_통합.md` — Why/What/How 맥락.
3. **fitness function**: `docs/09_채점표_Evaluation_Rubric.md` — 100점 10차원 + 하드게이트. **목표 90.** (읽기 전용 ground truth)
4. **레포 구조 (Workpaper-2120, README 정의)**: `contract/`(스키마) · `prompts/`(LLM 프롬프트) · `rules/`(결정 규칙: 세무 한도·source-priority·conflict·web policy·하드게이트) · `skills/`(체크리스트) · `src/`(결정적 계층: 계산·오케스트레이션·citation검증·conflict탐지·audit·DOCX) · `src/ai/`(어댑터: LLM·embedding·reranker·Tavily·Brave·law-MCP·OCR·DART **클라이언트만**) · `tests/`(golden·adversarial·regression) · `infra/config`(벤더 config — 어댑터에 하드코딩 금지).

---

## 2. 빌드 순서 (수렴을 위해 이 순서를 지켜라)

0. **rubric freeze — 선행 게이트 (반드시 먼저)** — 첫 iteration은 `STATUS.md`에 **채점표 공동검토 완료 여부 + rubric freeze 버전**을 기록한다. 미완료면 하버스/구현을 **하지 말고** rubric 확정 태스크만 수행: 완료 게이트(6 slice 전부 ≥90 + 하드게이트 0)·10차원 가중치·하드게이트 캡·per-FR 합격조건·**hidden freeze set / public practice set 분리**(`docs/09 §147·§185`)를 확정하고 **사람 승인(freeze)** 을 받은 뒤에만 1번으로 진행한다.
1. **스캐폴딩** — Python 프로젝트(`pyproject.toml`, deps) + Workpaper-2120 폴더 + `contract/`에 10개 ERD 클러스터(A~I) 스키마(`docs/04`). 3대 불변식을 타입/런타임으로 강제: ①격리키 전파(`client_id`/`matter_id`) ②인용=버전객체(`ProvisionVersion`/`Ruling`/`CasePrecedent`/`SourceSnapshot`) ③시점 유효성(`applicable_basis`).
2. **평가 하버스 먼저** — `tests/golden/` gold-set + rubric scorer를 *슬라이스보다 먼저* 만든다. scorer는 per-slice 0~100 + 하드게이트 플래그를 출력: 결정적 차원(검색 recall@k·격리·재현성·인용 존재/버전/pinpoint)은 코드로, 판단 차원(4 법리추론·5 쟁점누락·7 리스크)은 **LLM-judge**(`prompts/judge.md`)로. **hidden freeze set(구현자가 보지 않음) / public practice set 분리**. 최초 생성 후 `tests/golden/`·scorer·`docs/09` 변경은 **사람 승인 없이는 regression gate 실패**로 처리한다. **이 하버스가 곧 너의 점수계다 — 정직하게 만들어라.**
3. **슬라이스 구현 (의존 순서)**: ⑥테넌트 격리(`SEC-001/002/003`, RAG-007 — 가장 기초·결정적) → ①법령MCP 앵커(`API-002/003/004`, LawDataSource fallback) → ②RAG citation(`RAG-002/017`, `HALU-003`) → ③공식소스 Web run(`WEB-002/003/004/011/012`) → ④충돌 케이스 3소스 종합(`ORCH-008~012`, `HALU-005/012`, `EVAL-011/012`) → ⑤CPA HITL(`ORCH-007`, `HALU-008/009`, `AGT-008`/`OUT-004`).
4. **프론트 목업 3화면** — 백엔드가 데이터를 내면: ① Intake 자료수집 챗(`INTK`, §4-1-1) → ② 선택지 비교표(`StrategyOption`, §3-5) → ③ DOCX 검토패키지 미리보기(11목차, `OUT-002/006`). **'렌더' 인정 기준**: 각 화면은 fixture/백엔드 데이터가 표시된 **Playwright 스크린샷 + 핵심 텍스트/테이블/근거링크 assertion 통과**여야 한다(빈 페이지·더미 텍스트 ✕).

> 한 iteration에 전부 하려 하지 마라. **가장 점수 낮은 슬라이스/차원 하나**를 골라 전진시키고, 하버스로 측정하고, 커밋한다.

---

## 3. 매 iteration 사이클 (반드시 이 순서로)

1. `STATUS.md`와 `git log --oneline -15`를 읽어 이전 진행·미해결 codex 피드백을 파악한다.
2. **타겟 선정**: 하버스 점수표에서 **가장 약한 슬라이스/차원** 1개. (미해결 codex 피드백이 있으면 우선.)
3. 구현/수정한다. 스펙의 FR-ID를 코드/테스트에 주석으로 앵커링한다.
4. **하버스 실행** (`pytest -q` + `python -m tiw.eval`) → per-slice 점수·하드게이트 플래그를 얻는다. 실연동 응답은 `tests/fixtures/`에 `SourceSnapshot`으로 녹화한다.
5. **codex 리뷰** — review gate가 stop 전에 fresh codex 리뷰를 강제한다. codex의 지적을 `STATUS.md`의 "codex 미해결" 섹션에 기록하고, **빠른 수정은 이번 iteration에 반영**, 큰 건은 다음 타겟으로 남긴다.
6. **커밋** — 메시지에 점수 포함. 예: `feat(slice6): tenant isolation leak=0 — S6 72→88`. 베이스라인을 **이겨야** 한다(pairwise regression: 새 하드게이트 위반 0).
7. `STATUS.md` 갱신: 6-슬라이스 점수표 + 다음 타겟 + codex 미해결.
8. **완료 판정** — `STATUS.md` 자기보고가 아니라 **같은 iteration의 clean `pytest -q` + `python -m tiw.eval`이 산출한 `RubricResult` + 렌더 아티팩트**가 §5 조건을 증명할 때만 promise. 아니면 그냥 멈춘다(stop hook이 같은 프롬프트를 다시 준다).

---

## 4. 가드레일 (위반 시 하드게이트 = 0~75점 캡)

- **인용 날조 금지**: 모든 결론은 실제 소스객체 인용. 미지지 인용은 G2에서 거부(캡 60).
- **테넌트 격리**: A사 검색이 B사 자료를 회수하면 0점. 격리필터는 끌 수 없게(`SEC-002`) 설계.
- **무권한·전직장 데이터 금지**: 전직장/무권한 고객자료의 저장·임베딩·검색·인용은 즉시 **0점 하드게이트**(`SEC-004`,`HALU-004`).
- **시점 유효성**: 핵심 결론의 시점 오류는 캡 65. 시점 불명 시 단정 금지 → 되물음(`HALU-007`).
- **고위험 경고**: 고위험·적극 절세·불확실 결론에는 **모든 산출 단계**에서 회계사 검토경고 + escalation 항목을 붙인다. 누락 시 캡 70(`HALU-009`).
- **HITL 불변식**: `ReviewerDecision`(승인) 없이 `FinalMemo`/고객 전달본 생성 금지(`ORCH-007`).
- **재현성**: 모든 답변은 사용한 정확한 소스 버전을 사후 복원 가능해야(캡 75).
- **비밀키**: env/`infra/config`에. 코드/커밋에 하드코딩 금지.
- **anti-gaming**: rubric·gold-set·scorer·hidden freeze set을 자기 유리하게 만들거나 고치지 마라(최초 freeze 후 변경은 사람 승인 필요). 점수가 정체하면 **구현을 고쳐라, 채점을 고치지 마라.**

---

## 5. 완료 조건 → promise

같은 iteration에서 clean `pytest -q` + `python -m tiw.eval`이 산출한 `RubricResult`가 **6개 슬라이스 모두 ≥ 90/100** + **하드게이트 위반 0**(전직장/무권한·테넌트 누수 포함)이고, **목업 3화면이 Playwright assertion(데이터 표시 + 근거링크)을 통과**하면, 그리고 **그때만**:

```
<promise>ALL_SLICES_90</promise>
```

그 전에는 절대 promise를 내지 마라. 한 슬라이스라도 90 미만이면 멈추고 다음 iteration을 받아 계속 개선한다.
