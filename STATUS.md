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
**scaffold + 평가 하버스 골격 + slice ⑥ 결정적 구현 완료** (autonomous 루프 진입 전 수동 검증 단계 — "통제된 시작"). 미커밋(워킹트리).

## 6 Vertical Slice 점수표 (RubricResult 기준 — 이번 iteration `python -m tiw.eval` 산출)
| # | Slice | 점수 | 하드게이트 | 상태 |
|---|---|---:|---|---|
| ⑥ | 테넌트 격리 | **100** (min over 4 cases) | 누수0 (TENANT_LEAK 미발생) | **통과 (≥90)** |
| ① | 법령MCP 앵커 답변 | — | — | 미착수 |
| ② | citation 검증 RAG | — | — | 미착수 |
| ③ | 공식소스 Web run | — | — | 미착수 |
| ④ | 충돌 케이스(3소스 종합) | — | — | 미착수 |
| ⑤ | CPA HITL 워크플로 | — | — | 미착수 |

- slice ⑥ 채점 대상 차원(인프라): 보안14·검색9·요구6·운영2 만 행사, 나머지(법리/쟁점/리스크/충돌/인용/산출)는 **N/A**(scorer가 미행사 차원에 점수 안 줌). leak=0·recall=1.0·shared_recall=1.0·null_rej 정상.
- 정직성 증거: `test_harness_catches_leakage_with_broken_store` — 일부러 격리필터를 깬 store를 **동일 채점 경로**에 넣으면 leak>0 → TENANT_LEAK → total 0 으로 적발됨.
- pytest: **34 passed** (베이스라인 21 + codex 수정 검증 13: fail-closed 3·공백키/FactPattern 거부 8·미등록게이트 차단 3).
- fail-closed 증명: throwing/empty store → `NOT_REPRODUCIBLE`(cap75) + total<90 실패 (`측정 못 함 = 만점` 불가).

프론트 목업 3화면(Intake챗·선택지비교표·DOCX미리보기): 미착수(백엔드 슬라이스 선행).

## 다음 타겟
1. **slice ① 법령MCP 앵커**(API-002/003/004, LawDataSource fallback) — `src/ai/korean_law_mcp_client.py` 실연동 + 응답을 `tests/fixtures/` SourceSnapshot 녹화 → ProvisionVersion 앵커. 채점 차원: 인용(12)·법리(20) 진입 → `prompts/judge.md` LLM-judge 연결.
2. slice ② citation 검증 RAG(RAG-002/017·HALU-003) — 실 임베더(`RealEmbeddingClient`) wiring.
3. eval 하버스에 ①용 케이스 + LLM-judge 연동(현재는 결정적 차원만 가동).

## codex 미해결 피드백 (이번 iteration codex 코드리뷰 결과)
- **반영 완료**: P0-1 평가 fail-closed(예외/빈결과→NOT_REPRODUCIBLE) · P1-2 공백 격리키 거부 · P1-3 FactPattern client_id 전파 · P2-2 미등록 hard gate code 차단(KeyError).
- **연기(후속 slice)**:
  - P1-1 citation version-object 존재·정합성 미검증 → **slice ①(법령MCP)** 에서 source registry로 처리.
  - P1-4 hidden freeze set repo 평문 노출 → 수용 한계(로컬 솔로). 완화: PROMPT.md `tests/golden/hidden/` 열람 금지 규칙. 향후 CI 비밀 artifact 외부화 검토.
  - P2-1 Chroma 운영 백엔드 격리 미구현 → **slice ②** 에서 실 wiring + tenant별 collection 격리 테스트.

## 빌드 환경 메모
- 스택: Python 3.11+ (검증: 3.14.4). 핵심 deps = `pydantic>=2.7`+`pyyaml`(결정적 경로). 어댑터(fastapi/anthropic/chromadb/python-docx)는 `[adapters]`/`[api]` extra — slice⑥ 테스트는 실키·heavy wheel 없이 통과.
- 실행: `pip install -e .` → `pytest -q` → `python -m tiw.eval --slice 6`. (Windows cp949 대응: CLI가 stdout을 UTF-8로 reconfigure.)
- 외부 의존성: 실연동(Korean-law-MCP·Tavily·Brave·LLM·DART·OCR) + 응답을 `tests/fixtures/` SourceSnapshot으로 녹화 — 현재는 어댑터 인터페이스+TODO wiring 지점만(slice①~⑤에서 연결).
- 격리 핵심: `src/vector_store.py` 가 client별 파티션 ⟂ SHARED 파티션을 **물리 분리**, 스코프 검색은 자기 파티션(+SHARED)만 순회 → 타사 파티션 미접근. `TenantScope` 필수 인자(SEC-002, 끌 수 없음).
- codex review gate: 활성(매 iteration stop 전 fresh 리뷰).
