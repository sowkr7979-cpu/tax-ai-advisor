# 章 03 — RFP · 기능요구사항 명세 (Functional & Non-Functional Requirements)

> **이 문서가 FR의 source of truth(정본).** 각 설계 章(01·02·05~08)은 *근거·설계 이유*, 본 문서는 *요구사항 등록부*다. `skills/`의 체크리스트는 여기서 파생된다(역방향 금지).
> **출발점(Codex)**: 에이전트가 아니라 **세무 워크플로 + 리스크 경계**에서 시작한다.
> **추적성**: 모든 FR은 `FR → contract/엔티티 → 구현 모듈(폴더) → EVAL 케이스`로 연결되어야 한다(§14).

---

## 1. 범위 · 우선순위 규약

- **범위**: **전(全) 세목** Business/개인 Tax 자문 *보조*(법인세를 대표 데모로). 신고서 자동작성이 아니라 **검토패키지 초안 + 선택지 비교 + 근거**.
- **MVP 입력·범위(회계사 토의 확정)**: 데이터 접근 = **수기 입력 + 엑셀 TB 업로드**(ERP 연동은 향후). 특정 절세 항목·**특정 세목 고정 ✕** — **전 세목·전 세무항목을 동일 구조로 검토**(Tax Skill Library, 세목·쟁점→법령 매핑 레지스트리 `ORCH-015`). 데모 = **목업 3화면**(Intake 챗 → 선택지 비교표 → DOCX).
- **우선순위**: `P0`(MVP 구조 데모 필수) · `P1`(Phase 2) · `P2`(Phase 3~4).
- **MoSCoW 매핑**: P0=Must, P1=Should, P2=Could.

---

## 2. 대상 사용 사례 (Target Use Cases)

| UC | 사용 사례 | 핵심 산출 |
|---|---|---|
| UC1 | **자료수집 인터뷰**(무슨 자료가 필요한지 모름) | 필요자료 안내·수집·결손 고지 |
| UC2 | **세무 리스크 식별** | 리스크 대시보드(계정변동·특수관계·손금·조사) |
| UC3 | **절세 기회 + 선택지 비교** | 보수/중립/적극 선택지별 세부담·리스크·방어 |
| UC4 | **세법 리서치(근거)** | 법령·예규·판례 인용 메모 |
| UC5 | **증빙 연결** | 쟁점 ↔ 원장·계약·통장·세금계산서 인덱스 |
| UC6 | **검토패키지 초안(DOCX)** | 13목차 보고서 초안 |
| UC7 | **다음 사업연도 재활용** | 거래처 Tax Memory |

## 3. 비사용 사례 (Non-Use Cases · 명시적 제외)

- ✗ **전문가 검토 없는 최종 세무의견/서명** (항상 HITL).
- ✗ **공격적 절세(조세회피) 설계** — 과세 리스크를 숨기는 안 제시 금지.
- ✗ **근거 없는 인용/단정** (`HALU-001`).
- ✗ **신고서 직접 전자제출** (더존/홈택스 영역).
- ✗ **전직장·무권한 고객데이터 활용** (`SEC-004`).
- ✗ **법령 시행일/적용시점 무시한 단정** (`PROV-013/014`).

## 4. 사용자 역할 (User Roles)

`CPA` · `TaxLawyer` · `Reviewer` · `Manager` · `Admin` · `ClientFacing` — 권한은 `RoleAssignment`(Matter/Engagement 범위)로 평가(`01_보안 §5`, `SEC-012`).

## 5. HITL 게이트 — 운영 계약 (누가·언제·책임지고 멈추나)

> **Codex 최우선 보강**: 게이트는 "발동·동작"만으론 부족하다. **승인자 역할·타임아웃·escalation·감사기록 엔티티**까지 정의해야 Big4 파트너 앞에서 "결국 누가 책임지고 멈추나"가 채워지고, Ralph loop 채점기가 HITL 완료를 확인할 수 있다(`ORCH-007`).

| 게이트 | trigger | 승인자 역할 | 필요 증거 | timeout | escalation | 감사기록 |
|---|---|---|---|---|---|---|
| H1 입력 마감 | Intake 충분/사용자 중단 | CPA | 검토범위·결손·한계 고지문 | — | — | `ReviewHistory` |
| H2 계산 플래그 | GT 불일치(`HALU-002`) | CPA | 계산로그·플래그 항목 | 작업 SLA 내 | `Reviewer` | `Review` |
| H3 충돌/시점 | 소스충돌·시점불명(`HALU-005/007`) | CPA→Reviewer | 충돌소스·시점 가정 | 작업 SLA 내 | `Reviewer` | `ConflictFlag`·`Review` |
| H4 고위험 | 적극 절세·조사 리스크 高 | **Reviewer** | 과세·방어논리·검토경고 | 확정 전 필수 | `Manager` | `ReviewerDecision` |
| H5 승인·서명 | 검토패키지 확정 | **Reviewer** | 전 게이트 통과·최종본 | 확정 전 필수 | `Manager` | `ReviewerDecision`→`FinalMemo` |

- **불변**: H4·H5 미승인 시 **고객 전달본 생성 차단**(`AGT-008`·`OUT-004`). 각 게이트 결과는 `Review`/`ReviewerDecision`에 기록(재현성).

## 6. 관할 · 시점 범위 (Jurisdiction & Temporal Scope)

- **관할(전 세목 확장, 변경①)**: **국세 전반** — 법인세·**소득세/원천세(퇴직소득 등)·부가가치세·상속세·증여세** 를 동일 파이프라인으로 검토(법인세는 대표 데모). **지방세**(취득·재산세)는 매핑 확장 대상, **관세·국제조세(이전가격 등)는 범위 외**(향후 확장 플래그). 세목·쟁점→법령(법인세법·소득세법·부가가치세법·상증세법…) 매핑은 레지스트리로 일반화(`ORCH-015`).
- **시점**: 모든 결론은 `applicable_basis`(거래일/귀속/사업연도/신고/처분/경정청구일)에 묶임(`PROV-013`).

## 7. 출력 유형 (Output Types)

선택지 비교표 · 리스크 대시보드 · 리서치 메모 · 증빙 인덱스 · **DOCX 검토패키지(13목차)** · 회계사 검토항목 리스트.

---

## 8. 기능요구사항 — 신규 도메인 (상세)

> SEC/PROV/RAG/WEB/API/HALU는 각 章에 상세. 여기서는 **章에 없던 도메인**(INTK/ORCH/AGT/OUT)을 상세 정의하고, §13에 전체 레지스트리.

### 8-1. INTK — 자료수집 인터뷰 (Intake Agent)
| FR-ID | 요구 | 입력 | 출력 | 수용기준 | 우선 |
|---|---|---|---|---|---|
| `INTK-001` | 챗봇이 필요자료를 안내·질문 | 검토목적·대상회사 | 다음 필요자료 질문 | **필수자료 체크리스트 대비 누락/수집/없음/모름 상태 100% 기록** | P0 |
| `INTK-002` | 업로드/"없음"/"모름" 처리 + Tax Vault 적재 | 사용자 응답·파일 | 적재·체크 | 미보유 항목 결손 표시 | P0 |
| `INTK-003` | 충분성 점검 루프 + 조기종료("여기까지") | 수집상태 | 반복/종료 | 사용자 선언 시 즉시 종료 | P0 |
| `INTK-004` | 마감 정리: 검토가능범위 + 결손·전제·한계 고지 | 수집자료 | 한계 고지문 | 모든 결론에 "자료한계" 꼬리표 | P0 |
| `INTK-005` | 적용시점(거래일/귀속연도) 확보, 없으면 되물음 | 사용자 | 기준일 | 시점 미확보 시 분석 차단(`PROV-013`) | P0 |
| `INTK-006` | 업로드 자료 confidentiality·라이선스 자동분류 | 파일 | 분류·게이트 | 무권한 자료 차단(`SEC-004`) | P0 |
| `INTK-007` | 업종/거래유형/세목별 **intake completeness matrix** 적용 | 검토목적·업종 | 충분성 판정 | 미충족 항목을 `자료한계`로 출력(충분성 기준 객관화) | P0 |

### 8-2. ORCH — 오케스트레이션
| FR-ID | 요구 | 수용기준 | 우선 |
|---|---|---|---|
| `ORCH-001` | 질의를 작업분해 → 에이전트 병렬 실행 → 결과 통합 | 다쟁점 질의 fan-out 로깅 | P0 |
| `ORCH-002` | **3소스 각각 독립 완결 답변 → 종합**(가중혼합·평균 금지) | 소스별 SourceAnswer 분리 보존 + 병렬 파이프라인 + 종합 | P0 |
| `ORCH-003` | 에이전트 간 handoff 상태 일관성(중복작업·유실 방지) | handoff 누락 0 | P1 |
| `ORCH-004` | 미해소 충돌·결손은 종합 단계에서 검토항목으로 승격 | 충돌 종합 시 단정 금지 | P0 |
| `ORCH-005` | `AnswerRun`/`SourceAnswer`/`AgentRun`/`ToolCall` trace 기록 | 답변 재현(`SEC-007`) | P0 |
| `ORCH-006` | 부분 실패(한 에이전트 장애) graceful degrade | **실패한 AgentRun/ToolCall·누락 영향·재시도 여부·결론 가능/불가 상태를 trace와 답변에 표시** | P1 |
| `ORCH-007` | HITL 게이트 운영계약(§5) 강제: 게이트별 승인자·timeout·escalation·감사기록 | H4/H5 미승인 시 고객본 차단·`ReviewerDecision` 기록 | P0 |
| `ORCH-008` | 질의당 1 `AnswerRun` + 최대 3 독립 `SourceAnswer` 후 종합 | **1≤SourceAnswer≤3 · source_type 유일 · 완결 run은 `SynthesisOpinion` 정확히 1개(보류 포함)** | P0 |
| `ORCH-009` | 각 `SourceAnswer`는 배정 소스 채널만 사용 + status(ANSWERED/SILENT/ERROR/BLOCKED) | 타 채널 누수 0·status 기록 | P0 |
| `ORCH-010` | `SynthesisOpinion` 재현성 | **불변 `SourceAnswer` 버전 + `policy_version` + `ConflictResolution` 로그 + prompt/model/tool 해시**로 재현 | P0 |
| `ORCH-011` | 종합은 claim 단위 일치/충돌/침묵 기록 | **표시되는 모든 종합 claim + 모든 충돌/침묵 source 입장을 `ClaimAlignment`가 커버** | P0 |
| `ORCH-012` | 종합은 source에 없는 인용을 새로 만들지 않음(인용 상속) | 종합 신규 인용 0 | P0 |
| `ORCH-013` | ①법령 부재 시 authority deficit 표시 + confidence 캡/HITL | **법령부재 정의(①`SourceAnswer.status`∈{SILENT,ERROR,BLOCKED} 또는 `SynthesisOpinion.authority_deficit=true`) + `confidence_cap` 정책값 + 고위험 HITL** | P0 |
| `ORCH-014` | 비용/지연 triage(병렬 실행) | **위험 tier 트리거 정의 + tier별 max 소스 + SILENT timeout/검색공백 조건 + latency/cost 예산(정책값)** | P1 |
| `ORCH-015` | **다세목(multi-tax) 쟁점→법령 매핑 레지스트리**(변경①) | **세목·쟁점 키 → (법령명·조문·조문제목) 매핑이 코드 하드코딩이 아니라 확장형 레지스트리; 저장 = `rules/tax_law_mapping.yaml`(결정 규칙 폴더, schema는 `contract/`에 정의) + reviewer 승인 변경(`rules/`는 결정 규칙 = PROMPT.md §1.4); 법인세 외 최소 1개 세목(소득세/퇴직소득) 케이스가 동일 파이프라인으로 검토패키지 산출; 미등록 세목은 fail-closed(`자료한계`/되물음, 임의 법령 추정 금지)** | P0 |

### 8-3. AGT — 에이전트별
| FR-ID | 에이전트 | 요구 | 수용기준 | 우선 |
|---|---|---|---|---|
| `AGT-001` | Risk | 계정변동·특수관계·손금·조사 리스크 탐지 | 리스크 후보+근거 생성 | P0 |
| `AGT-002` | Research | 3소스 병렬 검색→교차검증→인용 메모 | 인용 pinpoint 포함(`PROV-004`) | P0 |
| `AGT-003` | Strategy ★ | 보수/중립/적극 선택지별 세부담·리스크·방어·증빙·검토포인트 | 비교표 + 과세·방어 양면 | P0 |
| `AGT-004` | Evidence | 쟁점↔증빙 연결, 누락자료 식별 | 증빙 인덱스+결손 | P1 |
| `AGT-005` | Draft | 검토메모·소명논리·DOCX 초안 | 13목차 산출 | P0 |
| `AGT-006` | Strategy 계산검증 연계 | 절세효과 수치를 Ground Truth 검산 | 불일치 플래그(`HALU-002`) | P0 |
| `AGT-007` | Risk | 리스크 **taxonomy + 탐지규칙/임계값 + 근거 필드** 보유 | 유형·규칙·근거 갖춘 `RiskItem`만 후보 인정 | P0 |
| `AGT-008` | Strategy | **적극 선택지 가드레일** | 과세논리·방어논리·검토경고·Reviewer 승인 없이는 고객 전달본 포함 금지(`OUT-004`) | P0 |

### 8-4. OUT — 산출물
| FR-ID | 요구 | 수용기준 | 우선 |
|---|---|---|---|
| `OUT-001` | 선택지별 비교표(세부담·리스크·방어·증빙·검토포인트) | 3선택지 표 생성 | P0 |
| `OUT-002` | DOCX 검토패키지 13목차 생성 | 인쇄가능 DOCX | P0 |
| `OUT-003` | 답변에 인용·검토항목·자료한계 포함 | 무인용 단정 0(`HALU-001`) | P0 |
| `OUT-004` | 고객 전달본 ≠ 내부 메모 분리 | 전략리스크 내부용 한정 | P1 |
| `OUT-005` | 정량 효과(시간 절감률 등) KPI 표기 | **검토패키지 초안 1건 ≤10분**(MVP 데모=내부 추정치 표기 / 실측 계측·공식화=P2; 절감률 + 품질지표 동반) | P2 |
| `OUT-006` | DOCX **13목차** 필수섹션 강제 | 누락 섹션 시 생성 실패·각 섹션 필수 근거/증빙/검토항목 포함. **테스트 영향**: 기존 섹션-수 검증 fixture/assertion(`REQUIRED_SECTIONS`·`draft_package_to_fixture`·프론트 DraftScreen·Playwright)을 **13섹션으로 갱신** + §8/§10 신규 필수검증 추가(회귀 0) | P0 |
| `OUT-007` | **출처 채널별 독립 결과 표시**(①법령MCP·②내부RAG·③웹)(변경②) | **종합 *전* 의 각 채널 `SourceAnswer`(답변·인용·상태)를 §8에 병렬 표시; 상태는 공식 enum `SourceAnswerStatus`(`ANSWERED`/`SILENT`/`ERROR`/`BLOCKED`) 사용(웹 abstain·내부RAG 코퍼스 부재 → `SILENT(커버리지 갭)`); 내부 RAG 부재 시 합성 0·정직 표기(`RAG-014`); 채널 원본 ⟂ 종합의견 분리(`EVAL-002`)** | P0 |
| `OUT-008` | **법령 추적 경로 + 추론 과정 도식**(변경③) | **§10에 (a)law-tracing(쟁점→법령·조문·시행버전·as-of·pinpoint·인용 사슬) + (b)`ReasoningTrace`(단계·입력·판단·인용·결과) 도식; 하이브리드 렌더=프론트 Mermaid / DOCX 네이티브 도식+트레이스 표; DOCX **결정성 기준 = 정규화 XML 구조 동등성**(core-props timestamp 고정·공백 정규화 후 `document.xml` 동일, 기존 P2 byte 결정성 패턴 연장); 트레이스의 모든 법적 판단은 인용 동반(`HALU-015`)** | P0 |

> **DOCX 13목차(필수섹션, `OUT-002/006`)**: ① Executive Summary ② 회사개요·검토범위 ③ 입력자료 목록 ④ 주요 세무 리스크 ⑤ 절세 기회 ⑥ 선택지별 세부담·리스크 비교표 ⑦ 쟁점별 검토메모 ⑧ **출처 채널별 독립 결과(①②③ 종합 전 원본)** ⑨ 관련 법령·근거 자료 ⑩ **법령 추적 경로 + 추론 과정 도식** ⑪ 추가 요청자료 ⑫ 회계사 검토 필요사항 ⑬ 결론 초안·추천 검토순서. *(내부 전용: ⑦⑧⑩(전체)⑫ — 고객 전달본은 ⑩을 법령추적 요약으로 축약, `OUT-004`.)*

---

## 9~12. 도메인별 FR (章 참조)

- **§9 INTK/ORCH/AGT/OUT** — 위 §8.
- **보안 SEC-001~017** → `01_보안_기밀_테넌시.md §11`.
- **출처·시점 PROV-001~016** → `02_출처_시점유효성.md §7`.
- **내부 RAG-001~017** → `05_내부RAG.md §13`.
- **Web WEB-001~012** → `06_웹리서치.md §10`.
- **외부 API-001~014** → `07_외부API연동.md §5`.
- **환각방지 HALU-001~015** → `08_환각방지_인용검증.md §9`.

---

## 13. 비기능요구사항 (NFR)

| FR-ID | 항목 | 요구 | 수용기준 | 우선 |
|---|---|---|---|---|
| `NFR-001` | 토큰/비용 | 실무서 통주입 금지·top-k·압축으로 토큰 통제 | **질의유형별 max tokens/max cost 초과 시 요약·top-k 축소·비동기 전환** | P0 |
| `NFR-002` | 응답시간 | 대화형 단계 응답 SLA·장기작업 비동기 | **intake/search/synthesis/DOCX 단계별 p95 SLA, 초과 시 비동기 고지** | P1 |
| `NFR-003` | 가용성 | 외부 API 장애 시 degrade·fallback(`API-007`) | 단일 벤더 장애 무중단 | P1 |
| `NFR-004` | 확장성 | 회사·매터·문서 증가에 검색 성능 유지 | **지정 문서수/청크수에서 recall@k·p95 latency·cost 기준 이하 유지** | P2 |
| `NFR-005` | 관측성 | 필수 metric set 기록 | **run 단위: cost·latency·error·recall proxy·citation failure·tenant-filter hit/miss** | P1 |
| `NFR-006` | 정확도 임계 | 인용정확도·검색 recall@k 최소 기준(`09`) | 기준 미달 시 릴리즈 차단 | P0 |
| `NFR-007` | 재현성 | 답변→자료·법령버전·모델·프롬프트 복원 | 임의 답 100% 재현 | P0 |
| `NFR-008` | 보안·컴플 | `01_보안` 전 통제 충족 | 누수 테스트 0건 | P0 |
| `NFR-009` | 이식성 | 벤더(임베딩·벡터DB·검색) 교체 가능 | 어댑터 교체 무영향(`API-001`) | P1 |
| `NFR-010` | 라이선싱 | ingest/인용/반출 가능 출처만 사용 | `SourceLicense` 없는 결론 0 | P0 |

---

## 14. 추적성 매트릭스 (발췌)

| FR | contract/엔티티 | 모듈(폴더) | EVAL |
|---|---|---|---|
| `RAG-007` 인덱스 분리 | `VectorIndex.scope` | `src/` 검색 + infra/config | `EVAL` 누수셋 |
| `PROV-003` 시행일 버전 | `ProvisionVersion` | `src/ai/` LawDataSource | `EVAL` as-of 케이스 |
| `HALU-002` 계산검산 | `SourceAnswer`·계산로그(AnswerRun scope) | `src/` 계산엔진 | `EVAL` 한도 케이스 |
| `ORCH-008` 독립답변→종합 | `AnswerRun`·`SourceAnswer`·`SynthesisOpinion` | `src/` 오케스트레이션 | `EVAL-011` 앙상블셋(침묵·2v1·3way·법령부재) |
| `ORCH-011` claim 정합 | `ClaimAlignment`·`ConflictResolution` | `src/` 종합 | `EVAL-012` 충돌탐지·lineage |
| `AGT-003` 선택지 비교 | `StrategyOption` | `src/ai/` Strategy | `EVAL` 비교표 케이스 |
| `OUT-002` DOCX | `DraftPackage` | `src/` DOCX | `EVAL` 산출 케이스 |

> **규칙**: 추적 사슬이 끊긴 FR은 채점표(`09`)에서 감점. 모든 P0는 EVAL 케이스 보유 필수.

---

## 15. 면접 한 줄

> "기능을 '에이전트 6개'로 나열하지 않고, **세무 워크플로와 리스크 경계**에서 요구사항을 뽑았습니다. 무엇을 *안 하는지*(공격적 절세·무근거 단정·전문가 없는 최종의견)를 먼저 못박고, 모든 요구를 **데이터·모듈·평가 케이스까지 추적 가능**하게 묶었습니다."
