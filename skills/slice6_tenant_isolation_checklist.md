# skills/ — slice ⑥ 테넌트 격리 체크리스트 (docs/01 §4, docs/09 예시 D)

> RFP(`docs/`)에서 **파생된** 운영 체크리스트. RFP 사본 ✕.

## SEC-001 격리키 전파
- [ ] 모든 고객 파생 레코드(Chunk·Embedding·RetrievalRun·AnswerRun·SourceAnswer…)에 `client_id`.
- [ ] NULL/공백 격리키 적재 시도 → **거부 + 감사로그**.

## SEC-002 격리필터 비활성 불가
- [ ] retrieval API 시그니처에 `TenantScope` **필수 인자**(끄는 경로 없음).
- [ ] 빈 스코프 생성 자체가 예외.

## SEC-003 / RAG-007 인덱스 분리
- [ ] 고객(L3·L4) → TENANT 파티션(client별), 공유지식(L0·L1·L2) → SHARED 파티션.
- [ ] A 스코프 검색이 B 파티션을 **물리적으로 접근하지 않음**.
- [ ] 누수셋(adversarial: B 키워드로 A 질의) **교차회수 0건**.

## 채점 (docs/09 예시 D)
- 0: 혼합 인덱스 · 60: 분리됐으나 누수 일부 · 100: 물리분리 + 누수 0 + 필터 끌 수 없음.
- 누수 1건이라도 → **하드게이트 cap 0**.
