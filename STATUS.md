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
**scaffold + 평가 하버스 구축** (autonomous 루프 진입 전 수동 검증 단계 — "통제된 시작").

## 6 Vertical Slice 점수표 (RubricResult 기준)
| # | Slice | 점수 | 하드게이트 | 상태 |
|---|---|---:|---|---|
| ⑥ | 테넌트 격리 | — | — | 미착수 |
| ① | 법령MCP 앵커 답변 | — | — | 미착수 |
| ② | citation 검증 RAG | — | — | 미착수 |
| ③ | 공식소스 Web run | — | — | 미착수 |
| ④ | 충돌 케이스(3소스 종합) | — | — | 미착수 |
| ⑤ | CPA HITL 워크플로 | — | — | 미착수 |

프론트 목업 3화면(Intake챗·선택지비교표·DOCX미리보기): 미착수.

## 다음 타겟
1. Python 프로젝트 스캐폴딩 + Workpaper-2120 디렉토리(contract/ prompts/ rules/ skills/ src/ src/ai/ tests/ infra/config/).
2. `contract/`에 ERD 클러스터 A~I 스키마(docs/04) + 3대 불변식 강제.
3. 평가 하버스(`tiw.eval`): per-slice 0~100 + 하드게이트 플래그, hidden/public 분리, gold-set 부트스트랩.

## codex 미해결 피드백
- (없음) — PROMPT.md 리뷰 P0×2·P1×3·P2 반영 완료(`3e49460`).

## 빌드 환경 메모
- 스택: Python (FastAPI / pytest + LLM-judge / python-docx). 프론트 목업: 별도(Playwright assertion).
- 외부 의존성: 실연동(Korean-law-MCP·Tavily·Brave·LLM·DART·OCR) + 응답을 `tests/fixtures/` SourceSnapshot으로 녹화(결정적 회귀).
- codex review gate: 활성(매 iteration stop 전 fresh 리뷰).
