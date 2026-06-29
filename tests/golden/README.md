# tests/golden — gold-set (Ralph-loop ground truth, docs/09 §6/§8)

> **이 디렉토리·scorer·docs/09 변경은 사람 승인 없이는 regression gate 실패** (PROMPT.md §2).

## 구조 (hidden ⟂ public 분리 — EVAL-004)
- `public/` — **공개 연습셋(rotate)**. 구현자가 봐도 되는 케이스.
- `hidden/` — **숨김 freeze 셋**. 평가 시 `tiw.eval.loader.load_hidden_cases`로만 로드.
  `src/` 구현 코드는 이 디렉토리를 **import 하지 않는다**(정답 외우기 방지).

로더는 *디렉토리가 visibility를 결정*하도록 강제한다(파일이 스스로 라벨을 못 속임).

## slice ⑥ 케이스 (테넌트 격리)
| case | set | 무엇을 시험 |
|---|---|---|
| S6-PUB-001 | public | 교차 격리(동일내용 A/B) + 공유법령 회수 |
| S6-PUB-002 | public | NULL 격리키 적재 거부(SEC-001) + 정상 회수 |
| S6-HID-001 | hidden | 누수셋: 질의가 타사 자료를 명시 요구해도 교차회수 0 |
| S6-HID-002 | hidden | 3사 동일내용 + 공유법령, 스코프 회전 |

## 채점 (정직성)
- 교차회수(leakage) **1건이라도 → 하드게이트 TENANT_LEAK → cap 0**.
- slice 점수 headline = **케이스 최솟값**(한 케이스 누수면 슬라이스 실패).
- 인프라 슬라이스는 *실제로 행사한 차원*(보안·검색·요구·운영)만 채점하고 나머지는 N/A.
  scorer가 행사하지 않은 차원에 점수를 주지 않는다(`tiw/eval/scorer.py`).
