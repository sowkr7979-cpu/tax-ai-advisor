# 章 07 — External API Integration (외부 API 연동 · 인프라 계층)

> **이 章은 *인프라*, `06_웹리서치`는 *제품 의미론*** — 섞지 않는다(Codex). 여기서는 credential·retry·rate limit·fallback·cost·observability 같은 **횡단 관심사**와 각 외부 호출 **어댑터**를 다룬다.
> **코드 위치(Workpaper 2120)**: 모든 외부 호출 클라이언트 = **`src/ai/`(어댑터 전용)**. 비즈니스 로직(검색 오케스트레이션·검증)은 `src/`. 벤더 키·엔드포인트 config = **infra/config**(어댑터에 하드코딩 금지).
> **연결**: confidentiality별 전송정책=`01_보안` · 법령버전/시점=`02_출처` · 검색 의미론=`06_웹` · 임베딩/검색은 `05_RAG`가 호출.

---

## 1. 설계 원칙

1. **어댑터 경계**: 외부 의존은 전부 어댑터 뒤에 둔다(교체 가능). 상위 로직은 벤더를 모른다.
2. **계약(contract) 우선**: 각 어댑터 입출력은 `contract/` 스키마로 고정 → 벤더 교체해도 상위 불변.
3. **보안 우선**: 모든 전송은 `confidentiality_level` 정책(`01_보안 §8`)을 통과. `L3·L4`는 비학습·마스킹·프라이빗 경로만.
4. **관측 가능**: 모든 호출에 cost·latency·error·재시도 로깅.

---

## 2. 어댑터 목록

| 어댑터 | 용도 | 핵심 옵션/주의 | 호출자 |
|---|---|---|---|
| **LLM** | 추론·요약·초안·judge | 모델·버전 고정(`ModelVersion`), 비학습, 토큰/비용 로깅 | 에이전트(`src/ai`) |
| **Embedding** | chunk·쿼리 임베딩 | `L3`는 on-prem 경로, 차원·모델 버전관리 | `05_RAG` |
| **Reranker** | 검색 재랭킹 | cross-encoder, 후보 수 제한 | `05_RAG` |
| **Korean-law-MCP** | 법령 원문(① Ground Truth) | **개정·시점·재현성**(§3) | `Research` |
| **Tavily** | 웹 검색(1순위) | include_domains·time_range·credits | `06_웹` |
| **Brave Search** | 웹 검색(보조) | freshness·연산자·LLM context | `06_웹` |
| **공식소스 커넥터** | 국세청·법제처·조세심판원 등 | 라이선스·로봇정책 준수, 캐시 | `06_웹` |
| **OCR** | 스캔 PDF·**HWP** 텍스트화 | 한국어·표 인식 품질. **HWP5는 OLE 복합문서 직접 추출 경로 검증**(`olefile`+zlib BodyText 디플레이트, PARA_TEXT 레코드) | `05_RAG` ingestion |
| **DART(OpenDART)** | 공시·재무 데이터 | 회사 식별·기간. **실연동 검증**: `corpCode.xml`→corp_code, `fnlttSinglAcntAll`(reprt_code·fs_div OFS/CFS)로 실제 재무 인출 | `Risk`·`Evidence`(+시나리오 Tax Plan 현실성 보정) |
| **DOCX 생성** | 검토패키지 출력 | 템플릿·인용 삽입 | `Draft`(`OUT-`) |

---

## 3. Korean-law-MCP 추상화 (① 법령 Ground Truth 앵커 — 의존성 리스크)

신현우님 지적("korean-law-mcp 문제 있음") + Codex: **인터페이스 추상화는 필요조건일 뿐.** 법령 Ground Truth(①)가 단일 MCP에 종속되면 안 된다. *(가중 50/30/20은 폐기 — 3소스 독립답변→종합, `README §5`.)*

- **`LawDataSource` 인터페이스**: `getProvision(법령, 조문, asOfDate)` → `ProvisionVersion`. 구현체 교체 가능:
  - 1차: korean-law-mcp
  - fallback: **법제처 국가법령정보 / 국세법령정보시스템** 공식 API·데이터피드
  - (직접 크롤링은 신뢰성·라이선스·유지보수 리스크 → 최후수단, ADR)
- **시점·개정 정확성**: `asOfDate`로 **시행일 버전**을 받아야 함(`02_출처`). 최신만 주는 소스는 시점 쿼리 불가 → 보완 필요.
- **재현성**: 받은 원문을 `SourceSnapshot`(해시)로 저장 → "그 답이 쓴 정확한 법령 버전"을 사후 복원(`PROV-009`).
- **갱신 모니터링·스키마 드리프트**: MCP 응답 스키마 변경·다운타임·rate limit 감시. 커버리지 공백(시행령/규칙/고시/예규/판례/심판례/기본통칙) 점검.
- **무응답/불일치 시**: 결론 단정 금지 → 검토항목(`08`).

### 3-1. Coverage Matrix + SLA (Codex 보강)
- **Coverage Matrix(`API-012`)**: 각 `LawDataSource` 구현이 **법률·시행령·시행규칙·고시·예규·판례·심판례·기본통칙** 중 무엇을 커버하는지 **자동 점검**. 공백은 결론 제한.
- **Fallback SLA**: fallback 경로별 **coverage·latency·freshness(갱신 지연)·legal-authenticity** 목표를 명시(미정의 금지).
- **직접 크롤링 진정성(Codex)**: 직접 크롤링은 *법적 진정성·갱신 지연·파서 깨짐·로봇정책* 리스크가 큼. 결론 근거로 쓰기 전 **공식 원문 대조 + 스냅샷 인증(content_hash)** 필수. 인증 실패 시 "참고"로만.

---

## 4. 횡단 관심사 (모든 어댑터 공통)

- **Rate limit / 백오프**: 토큰버킷·지수 백오프·jitter.
- **Retry**: idempotent 호출만 자동 재시도. 횟수·타임아웃 상한.
- **Fallback / Circuit breaker**: 1차 실패 시 대체 경로(예: Tavily→Brave, MCP→법제처). 연속 실패 시 차단·degrade.
- **Timeout**: 호출별 상한(사용자 대기 보호).
- **Cost logging**: 호출당 비용(예: Tavily basic 1 / advanced 2 credits, LLM 토큰가) → 예산·KPI(`NFR`).
- **Caching**: 동일(법령,조문,asOfDate)·동일 쿼리 결과 캐시(시점 키 포함). **테넌트 격리 캐시**(`SEC-001`, 캐시 통한 누수 금지).
- **Observability**: trace_id로 `AgentRun→ToolCall→외부호출` 연결(`01_보안` 재현성).

---

## 5. API- 기능요구사항 (요약 — 전체는 `03_RFP`)

| FR-ID | 요구 | 수용기준(발췌) | 우선 |
|---|---|---|---|
| `API-001` | 모든 외부 의존은 어댑터 + `contract` 스키마 뒤에 둠 | 벤더 교체 시 상위 로직 무변경 | P0 |
| `API-002` | `LawDataSource` 추상화 + fallback(법제처/국세법령정보) | 1차 MCP 장애 시 대체 경로 동작 | P0 |
| `API-003` | 법령은 `asOfDate`로 시행일 버전 조회 | 2개 연도 질의 → 다른 버전 | P0 |
| `API-004` | 외부 응답을 `SourceSnapshot`(해시) 저장(재현성) | 답변→법령버전 복원 | P0 |
| `API-005` | confidentiality별 전송정책 강제(비학습·마스킹·on-prem) | `L3` 비보장 벤더 전송 0 | P0 |
| `API-006` | rate-limit·retry·timeout·circuit breaker | 장애 주입 시 degrade·무중단 | P1 |
| `API-007` | fallback 경로(Tavily→Brave, MCP→공식 API) | 1차 실패 자동 대체 | P1 |
| `API-008` | cost·latency·error 로깅(trace 연결) | 호출당 비용·지연 집계 | P1 |
| `API-009` | 테넌트 격리 캐시(시점 키 포함) | 캐시 통한 교차 회수 0 | P0 |
| `API-010` | MCP 스키마 드리프트·다운타임·커버리지 모니터 | 드리프트 알림·결론 제한 | P1 |
| `API-011` | OCR(HWP·스캔) 텍스트화 품질 기준 | 표·한국어 인식 회귀 테스트 | P1 |
| `API-012` | `LawDataSource` coverage matrix 자동 점검(법률~기본통칙) | 공백 시 결론 제한·알림 | P1 |
| `API-013` | `L3/L4` 임베딩 경로(on-prem vs private API)를 정책값으로 강제·로깅 | 정책 위반 경로 0건 | P0 |
| `API-014` | 라이선스 자료의 embedding/export/cache 허용권 별도 검사 | 금지 자료 외부임베딩 0건 | P0 |

---

## 6. 면접 한 줄

> "법령을 핵심 근거(①)로 쓰는데 그게 외부 MCP 하나에 묶이면 위험합니다. 그래서 법령 조회를 **인터페이스로 추상화**하고, 장애 시 법제처 공식 데이터로 **자동 대체**하게 했습니다. 그리고 받은 원문을 **해시로 박제**해, '이 답이 어느 시점 어느 조문으로 나왔는지'를 나중에 그대로 재현할 수 있게 했습니다."
