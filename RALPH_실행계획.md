# TIW Ralph Loop — 실행 계획

## Context — 왜 이 작업인가

`md 파일/법인세_세무AI_설계서_통합.md`(서사 정본) + `docs/01~09`(규범 명세)까지 **설계는 끝났고 코드는 0**인 상태다. README의 현재 단계는 "사용자+AI 공동 채점표 검토 → Ralph loop(vertical slice 6종 게이트)". 목표는 이 설계서를 스펙으로 **TIW 백엔드 + 평가 하버스 + 프론트 목업 3화면**을 Python으로 greenfield 구현하고, **6개 vertical slice를 rubric ≥90점**으로 통과시키는 것이다. 매 iteration 끝에 **codex 리뷰**를 강제로 받는다.

## 확정된 결정

- **스택**: Python (FastAPI 백엔드 / pytest+LLM-judge 하버스 / python-docx)
- **외부 의존성**: 실연동 (+ `SourceSnapshot` 픽스처 녹화로 결정적 회귀)
- **범위**: 백엔드 파이프라인 + 평가 하버스 + 프론트 목업 3화면
- **완료 게이트**: 6 slice 각각 rubric ≥90 + 하드게이트 위반 0 + 목업 3화면 렌더
- **codex 리뷰**: review gate로 매 iteration(stop 시점) 강제

## 루프 메커니즘

- 드라이버: 루트 `PROMPT.md` (매 iteration 동일하게 읽음). self-reference는 파일+git history+`STATUS.md`.
- 빌드 순서: ①스캐폴딩(Workpaper-2120 + contract 스키마) → ②**평가 하버스 먼저** → ③슬라이스 ⑥→①→②→③→④→⑤ → ④목업 3화면.
- 각 iteration: STATUS 읽기 → 최약점 1개 전진 → 하버스 측정 → **codex 리뷰 반영** → 커밋(점수) → STATUS 갱신.
- 종료: 전 slice ≥90 충족 시 `<promise>ALL_SLICES_90</promise>`, 아니면 stop hook이 재투입.

## 런치 전 체크리스트 (선행 필수)

1. **`!codex login`** — codex CLI는 설치됐으나 미로그인. 미로그인이면 review gate가 동작 안 함.
2. **review gate 켜기** — `/codex:setup --enable-review-gate` (stop 전 fresh codex 리뷰 강제 = 매 iteration 리뷰).
3. **git 초기화** — `.git`가 비어있음(깨짐). `git init` + 기본 브랜치 `main` + 설계 산출물 베이스라인 커밋(이후 diff·pairwise regression 기준).
4. **rubric 90 게이트 명문화** — docs/09에 "목표 90점"은 이미 있음. 완료 게이트("6 slice 전부 ≥90 + 하드게이트 0")를 docs/09에 1줄로 확정(첫 reviewed 변경으로).
5. **PROMPT.md codex 리뷰** — 루프 시작 전에 드라이버 프롬프트 자체를 codex로 1회 리뷰(메트릭 게이밍 여지·완료조건·가드레일 점검).

## 런치 커맨드 (체크리스트 후)

```
/ralph-loop "루트 PROMPT.md를 읽고 TIW greenfield 빌드의 다음 iteration을 그대로 실행하라. STATUS.md가 6개 슬라이스 전부 ≥90/100 + 하드게이트 0 + 목업 3화면 렌더를 보일 때만 <promise>ALL_SLICES_90</promise>를 출력하라." --completion-promise "ALL_SLICES_90" --max-iterations 120
```

언제든 `/cancel-ralph`로 중단 가능.

## 주요 리스크 / 의존성

- **gold-set 품질이 rubric의 의미를 좌우** — 4·5·7차원(법리추론·쟁점누락·리스크)은 본래 CPA 채점. 사용자(회계사)가 gold 케이스를 시드·검증해줄수록 점수가 신뢰 가능. 초기엔 설계서 예시로 부트스트랩.
- **메트릭 게이밍** — 루프가 채점을 자기 유리하게 고칠 위험 → rubric/gold/scorer 읽기전용 + codex 리뷰가 감시.
- **실연동 비용/레이트리밋** — 픽스처 녹화로 회귀는 결정적, 실호출은 신규 케이스에만.
- **루프 규모** — 6 slice 풀스펙 90점은 거대. 정체 시 슬라이스 1~2개부터 90 달성 후 확장으로 축소 가능.

## 검증 방법

- 슬라이스별: `python -m tiw.eval --slice N` → 0~100 + 하드게이트 플래그.
- 전체: `pytest -q` (결정적 차원) + judge run (판단 차원).
- 목업: 3화면 로컬 렌더(스크린샷) 확인.
- 회귀: 새 커밋이 같은 케이스에서 baseline을 이기고 신규 하드게이트 위반 0.
