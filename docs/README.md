# Tax Intelligence Workspace (TIW) — 설계 문서 세트

> **목적**: 신현우님 리뷰 + Codex 2라운드 리뷰를 반영해, 서사형 설계서(`md 파일/법인세_세무AI_설계서_통합.md` — 정본; `Claude/`에 동일 사본)를 **실행 가능한 명세(章 분리 + RFP + ERD + 채점표)** 로 내려쓴 문서 세트.
> **상태**: **v1.0 구현 완료**(slice ①~⑥ rubric ≥90 + 라이브 엔드투엔드 `python -m tiw run` + 프론트 목업 3화면) → **v1.1 진행 중**(slice⑦ 다세목·투명성, 변경①②③ — `STATUS.md` 상단). Ralph loop 자동 반복 개선 중.
> **언어**: 한국어. **독자**: 회계사(비개발자) + 개발/AI 검토자 + 채용 면접관.
> **감사 대상 spec 표면(정본)**: `md 파일/법인세_세무AI_설계서_통합.md`(+`Claude/` 동일 사본) + `docs/01~09`(`.md`) 만 Ralph가 구현 기준으로 삼는다. **`docs/_build/`**(쉬운설명 PDF·`body_*.html`)는 **Edge-headless PDF 파이프라인(`docs/_build/build_pdf.py`)이 생성하는 파생 설명 아티팩트**로 spec이 아니며 감사 대상에서 **제외**한다(정본 변경 후 별도 재생성 — 일시적으로 구버전 문구가 남을 수 있음).

---

## 0. 이 문서 세트가 답하는 핵심 질문

1. **text split / embedding / Vector DB도 직접 설계해야 하나?** → **그렇다(직접 *통제*).** 단 벡터DB *엔진*은 기존 것을 쓴다(직접 *구현* 아님). → `05_내부RAG.md`
2. **내부 RAG / 외부 API / Web Research는 별도 章이어야 하나?** → **그렇다.** 계층(인프라 vs 제품 의미론)이 다르므로 섞지 않는다. → `05`, `06`, `07`
3. **환각을 어떻게 막나?** → 무근거 결론 금지 + 인용 검증 + 충돌 표시 + HITL. → `08_환각방지_인용검증.md`
4. **이 모든 게 제대로 구현·실행되는지 어떻게 채점하나?** → 하드게이트 + 100점 분해 채점표. → `09_채점표_Evaluation_Rubric.md`

---

## 1. 문서 지도 (읽는 순서 = Codex 권고: 요구·리스크 → provenance → ERD → 구현계층 → 채점)

| # | 파일 | 章 | 한 줄 |
|---|---|---|---|
| — | `README.md` | (인덱스) | 공유 계약: 용어·FR-ID 체계·엔티티 카탈로그·레포맵 |
| 00 | `md 파일/법인세_세무AI_설계서_통합.md` | 제품 범위/전체 아키텍처 | (서사 설계서 정본 — `Claude/`에 동일 사본) |
| 01 | `01_보안_기밀_테넌시.md` | Security / Confidentiality / Tenancy | 누가 무엇에 접근하나 · 전직장 데이터 금지 · 격리 |
| 02 | `02_출처_시점유효성.md` | Provenance / Temporal Legal Validity | 인용은 *버전 박힌* 법령을 가리킨다 · 시행일 기준 유효성 |
| 03 | `03_RFP_기능요구사항.md` | RFP + NFR | 기능요구사항 전체 (FR-ID 부여) |
| 04 | `04_ERD_데이터모델.md` | ERD / 데이터 계약 | provenance 중심 엔티티·관계 |
| 05 | `05_내부RAG.md` | Internal RAG | 문서유형별 split → embedding → hybrid retrieval |
| 06 | `06_웹리서치.md` | Web Research | 최신 공식근거 *수집기*(답변기 아님) |
| 07 | `07_외부API연동.md` | External API Integration | LLM·임베딩·법령MCP·검색·OCR·DART·DOCX 어댑터 |
| 08 | `08_환각방지_인용검증.md` | Hallucination Prevention | 검증 게이트 |
| 09 | `09_채점표_Evaluation_Rubric.md` | Evaluation Rubric | Ralph loop fitness function |

> **章 10(Ralph Loop 개선 절차)는 아직 작성하지 않음** — 채점표 공동검토 후 별도 단계.

### 의존(읽기) 그래프
```
01 보안·테넌시 ─┐
02 출처·시점유효성 ─┼─► 04 ERD ─► 03 RFP ─► 09 채점표
05 RAG / 06 Web / 07 API / 08 환각방지 ─┘   (FR-ID)   (FR-ID 참조)
```
- **01·02가 04(ERD)보다 먼저**인 이유: 테넌트 격리키·source 버전·시행일 모델이 스키마의 전제이기 때문(나중에 넣으면 스키마를 갈아엎어야 함).

---

## 2. Workpaper 2120 레포 구조 (코드 — *지금은 설명만, 구현 안 함*)

이 설계가 코드가 될 때 따를 폴더 지도. **deterministic(검증·계산) 계층과 AI(어댑터) 계층의 분리**가 핵심이며, 이는 "계산층 Ground Truth + AI 보조"라는 제품 철학과 정합한다.

| # | 폴더 | 역할 | 이 설계에서 담는 것 |
|---|---|---|---|
| 01 | `root` (README) | 모듈 개요·실행정보 | 아키텍처 개요·실행법 |
| 02 | `contract/` | 입출력 스키마·모듈 계약 | ERD 산출 스키마: `Chunk`·`SourceObject`·`Citation`·`RetrievalRun`·`EvidenceBundle`·`AgentInput/Output` |
| 03 | `prompts/` | LLM 프롬프트 자산 | 6 에이전트 프롬프트 + synthesis·judge 프롬프트 |
| 04 | `rules/` | 변동·비율·위험 판정 규칙 | 세무 한도·비율·risk scoring + source-priority/conflict 규칙 + web source-policy + 하드게이트 |
| 05 | `skills/` | 운영 가이드·체크리스트 | RFP에서 *파생된* 체크리스트·HITL 절차·CPA 검토 가이드 |
| 06 | `src/` | 검증·분석·리포트 엔진(deterministic) | 계산 Ground Truth · RAG 오케스트레이션 · citation 검증 · conflict 탐지 · audit log · DOCX |
| 07 | `src/ai/` | AI 어댑터·코멘트 계층 | LLM·embedding·reranker·Tavily·Brave·법령MCP·OCR·DART **클라이언트만** |
| 08 | `tests/` | 케이스 검증·회귀 | golden set(`tests/golden/`)·adversarial·regression gate (= Ralph loop 하버스) |

**경계 규칙 (외우기):**
- **RFP의 source of truth = `docs/`** (이 폴더). `skills/`엔 *파생* 체크리스트만 — RFP 사본을 진실원본으로 두지 않는다.
- **런타임 데이터 ≠ 소스코드**: 벡터DB 데이터·retrieval log·gold-set은 `runs/`·`logs/`·`tests/golden/`·외부 스토리지에. *스키마만* `contract/`에.
- **API 호출(`src/ai/`)과 RAG 오케스트레이션(`src/`)을 섞지 않는다.**
- **벤더 config(임베딩 모델·벡터DB·검색 키)는 infra/config에**, 어댑터 코드 안에 하드코딩하지 않는다.

> ⚠️ **조기 경직 주의(Codex)**: 코드가 없는 지금 이 폴더맵을 "영구 확정"으로 보지 말 것. **확정하는 것은 *경계*(deterministic vs AI, contract vs prompt, 런타임데이터 vs 소스, 테넌트데이터 vs 공유참조)이지 폴더 영구성이 아니다.** vertical slice 몇 개(§7)가 통과하기 전까지 레포맵은 *provisional*.

---

## 3. FR-ID 체계 (RFP·채점표 공통)

형식: **`<도메인>-<3자리>`** (예: `RAG-001`). 채점표는 이 ID를 그대로 참조한다.

| 접두 | 도메인 | 章 |
|---|---|---|
| `SEC-` | 보안·기밀·테넌시·ACL | 01 |
| `PROV-` | 출처·인용·시점 유효성 | 02 |
| `INTK-` | 자료수집 인터뷰(Intake) | 03 / 기존 §4-1-1 |
| `RAG-` | 내부 RAG 파이프라인 | 05 |
| `WEB-` | Web Research | 06 |
| `API-` | 외부 API 연동 | 07 |
| `HALU-` | 환각방지·인용검증 게이트 | 08 |
| `ORCH-` | 오케스트레이션(작업분해·에이전트 병렬·종합) | 03 |
| `AGT-` | 에이전트별(Risk/Research/Strategy/Evidence/Draft) | 03 |
| `OUT-` | 산출물(비교표·DOCX 검토패키지) | 03 |
| `NFR-` | 비기능요구사항(성능·비용·가용성·운영) | 03 |
| `EVAL-` | 평가·채점·회귀 | 09 |

**우선순위 라벨**: `P0`(MVP 데모 필수) · `P1`(Phase 2) · `P2`(Phase 3~4).

---

## 4. 엔티티 카탈로그 (ERD 표준 이름 — 전 문서 공통)

세부 속성·관계는 `04_ERD_데이터모델.md`. 여기서는 **이름을 고정**해 문서 간 표기를 통일한다.

- **테넌시/신원**: `Tenant`(배포 단위=법인/펌) · `Client`(자문 고객사=납세자) · `Engagement`(수임 건) · `Matter`(검토 사안) · `User` · `Role`(권한 집합 정의) · `RoleAssignment`(User가 특정 Matter/Engagement 범위에서 갖는 권한 — Role은 계층 노드가 아니라 *부여*된다) · `Permission` · `AuditLog`
- **세무 워크스페이스/대상**: `TaxWorkspace` · `TaxYear`(귀속연도) · `Jurisdiction`(세목·관할) · `TrialBalance` · `AccountLedger` · `PriorReturn`(전기 신고서) · `FinancialStatement`
- **문서/RAG**: `Document` · `DocumentVersion` · `Chunk` · `Embedding` · `EmbeddingModel` · `VectorIndex` · `SourceLicense` · `RetentionPolicy`
- **법령 출처/provenance**: `LegalSource` · `LegalProvision`(조문) · `ProvisionVersion`(시행일 버전) · `TransitionRule`(부칙 적용례·경과조치 — 기계 판정) · `EffectiveDatePeriod` · `Ruling`(예규·질의회신) · `CasePrecedent`(판례·심판례) · `SourceSnapshot`(웹/외부 캡처)
- **세무 분석**: `TaxIssue`(쟁점) · `FactPattern`(사실관계) · `RiskItem` · `StrategyOption`(선택지) · `EvidenceLink`(증빙연결)
- **질의/검색/답변(독립답변→종합)**: `Question` · `AnswerRun`(질의 1건) · `RetrievalRun` · `RetrievedEvidence` · `EvidenceBundle` · **`SourceAnswer`**(소스별 완결 답변: LAW_MCP|INTERNAL_RAG|WEB) · `Claim`(원자 명제) · **`SynthesisOpinion`**(종합의견) · `ClaimAlignment`(claim 단위 일치/충돌/침묵) · `ConflictResolution`(적용 규칙 결과) · `Citation`(SourceAnswer 소속) · `ConflictFlag` · `ConfidenceScore`
- **에이전트/실행**: `AnswerRun`(질의 1건 오케스트레이션) · `AgentRun` · `PromptVersion` · `ModelVersion` · `ToolCall`
- **검토/HITL/산출**: `DraftPackage` · `Review` · `ReviewerDecision` · `Correction` · `FinalMemo` · `ReviewHistory` · `TaxMemory`(거래처별 재활용 지식)
- **평가**: `EvaluationCase` · `ExpectedIssue` · `GoldCitation` · `Score` · `RubricResult` · `FailureMode`

**불변 원칙**: ① 모든 격리 대상 레코드는 `client_id`(필요 시 `matter_id`)를 전파한다. ② **`Citation`은 raw URL/자유텍스트가 아니라 `ProvisionVersion`/`Ruling`/`CasePrecedent`/`SourceSnapshot` 같은 *버전 박힌 소스객체*를 가리킨다.**

---

## 5. 3소스 근거 모델 — **각 소스 독립 완결 답변 → 종합의견** (중요)

> **방법론 한 줄(Big4 framing)**: **"독립 출처 삼각검증 + 감사 가능한 claim 단위 정합"**(Independent source triangulation with auditable claim-level reconciliation). 권위가 다른 세 근거 흐름을 *각각 독립 분석* → *명시적 우선순위 규칙으로 정합* → *근거가 입장을 뒷받침 못 하면 전문가에게 escalate*. 시니어 세무전문가가 상충하는 권위를 따져 의견에 서명하는 방식과 동일.

기존 서사 설계서의 "비중 50/30/20 가중 혼합"을 **폐기**하고 다음으로 확정한다(신현우님 제안 + Codex 설계):

- **핵심 모델**: 3소스가 **각각 독립적으로 완결된 답변(100%)** 을 만든다 → ①Korean-law-MCP 법령 답변 · ②내부 RAG 답변 · ③웹 답변(`SourceAnswer`). 그 뒤 **종합 에이전트**가 **claim(원자적 명제) 단위**로 일치/충돌/침묵을 매핑하고, 권위·시점·사실관계로 정합해 **종합의견(`SynthesisOpinion`)** 을 낸다. → `08 §5`, `03 ORCH-008~013`.
- **왜 가중 혼합이 아니라 독립 답변인가**: 자유서술 법리를 산술 가중으로 섞으면 빠르지만 부정확. 세 완결 답변을 **비교·종합**하면 (a) 정확하고 (b) **어디서 갈리는지(충돌)** 가 claim 단위로 드러나 회계사 검토에 유리.
- **권위 우선순위 = 종합 시 조정 기준**(가중치 ✕): 법률 > 시행령 > 시행규칙/고시 > (해석)예규·판례·심판례 > 라이선스 실무서 > 웹. **시행령은 위임범위 내 보충, 예규·판례는 해석·구체화이지 법령을 override하지 않음**(예규=구속력 한계, 판례=확정 변수). **다수결 금지** — 권위·시점이 우선(소수라도 상위 권위·유효 최신법이면 그것이 지배).
- **종합은 직접 인용하지 않는다**: 종합의견은 `SourceAnswer`의 인용을 **상속**할 뿐 새 인용을 만들지 않는다. 모든 표시 claim은 인용된 source claim으로 **추적**돼야 한다.
- **엣지 케이스**: 한 소스 침묵=불일치 아님(커버리지 갭 표시) · 3자 모두 불일치=종합 보류(소스별 답변은 표시) · ①법령 부재인데 ②③ 합치=비권위적 합의(실무 가이드로만, confidence 캡·HITL).
- **충돌은 평균 ✕**: 미해소 충돌은 단정하지 않고 **회계사 검토항목**으로(`08 §5-1` 결정테이블).
- **시점 유효성**: 모든 결론은 *거래일/신고연도/현재 자문일* 기준 유효 법령 버전에 묶인다. → `02_출처_시점유효성.md`.

---

## 6. ⚠️ 기밀·윤리 고지 (전 문서 적용)

- **전직장(예: RSM 신한) 고객 자문·신고 자료를 가져와 임베딩/학습/인용하는 것은 비밀유지·직업윤리 위반** → 금지(`SEC-` 하드게이트).
- 익명화도 *자동으로* 안전하지 않다(재식별·계약·동의 문제).
- **안전한 내부지식 소싱**: 공개 법령/예규/국세청 자료 · **라이선스된 실무서/출판물("서점·출판 제휴")** · 합성(synthetic) 자문 예시 · 신규 작성 내부 플레이북. 고객 데이터는 *수임범위+동의+접근통제+보존기간* 하에서만.

---

## 7. 진행 상태 & 다음 단계

- [x] 章 분리 목차 + 레포맵 매핑 확정 (plan)
- [x] 본 문서 세트 초안 작성 (01·02·05·06·07·08 → 04 ERD → 03 RFP → 09 채점표)
- [x] 서사 md ↔ docs 일관성 검수·정합화 (Codex 리뷰 반영)
- [ ] 사용자+AI 공동 채점표 검토
- [ ] (이후) Ralph loop — **vertical slice 7종** 통과를 게이트로: ①법령MCP 앵커 답변 ②citation 검증된 RAG 답변 ③공식소스 Web run ④충돌 케이스 ⑤CPA 검토 워크플로 ⑥테넌트격리 테스트 ⑦다세목·투명성(`ORCH-015`·`OUT-007`·`OUT-008`/`HALU-015`, 변경①②③)

## 8. 추적성 규칙

모든 기능은 **RFP 요구(FR-ID) → contract 스키마/엔티티 → 구현 모듈(폴더) → test/eval 케이스(EVAL-ID)** 로 추적 가능해야 한다. 채점표는 이 사슬이 끊긴 기능을 감점한다.

---
*문서 세트 v1 · Claude(설계) + Codex(리뷰) · 근거: 8개사 벤치마크 + 신현우님 리뷰*
