# Tax AI Advisor — 세무 AI 자문 시스템

세무 거래를 입력하면 **법령·판례 근거를 수집·검증**하고, 회계사 검토용 **자문 보고서(DOCX)** 를 자동 작성하는 AI 시스템입니다.
공인회계사(KICPA)가 세무 실무 관점에서 설계하고 직접 개발했습니다.

| 구분 | 링크 |
|---|---|
| 🔴 라이브 앱 (FastAPI + LLM) | https://tax-ai-live-production.up.railway.app |
| 🟢 정적 데모 (시나리오 체험) | https://tax-ai-demo-taupe.vercel.app |
| 🔗 자매 프로젝트 — 온프레미스 세무조정 자동화 (로컬 LLM/Ollama) | https://github.com/sowkr7979-cpu/tax-adjustment-demo |

---

## 무엇을 만들었나

**질문 → 사실관계 확인 → 근거 수집 → 검증 → 보고서** 파이프라인 전체를 자동화했습니다.

1. **AI 세무자문 보고서** — 새 질문에 대해 사실관계를 동적으로 질문하고, 13개 목차의 자문 보고서 DOCX를 생성
2. **'경우의 수' 의사결정 보고서** — 하나의 거래를 판단 게이트로 분해해 경우의 수(안전·주의·위험)별 세무리스크·절세전략을 플로우차트와 함께 제시
3. **시나리오 Tax Plan** — 재무제표 쟁점을 강조하고 시나리오별 세부담을 비교하는 실행계획 보고서
4. **CPA 리뷰 보고서** — 회계사 검토용 자연어 보고서 (근거 하이퍼링크 포함)

## 근거를 어떻게 보장하나 (신뢰성 설계)

세무 문서에서 가장 위험한 것은 **그럴듯한 거짓 인용**입니다. 이 시스템의 원칙:

- **fail-closed 검증** — 인용된 법령·판례가 실제 원문과 대조되지 않으면 출력에서 제외. 근거가 없으면 지어내지 않고 **빈칸으로 남김**
- **3소스 교차검증** — ① 법제처 Open API(법령·판례·해석례 실시간) ② 내부 RAG DB(세법 자료 31권 → 10,304 청크 임베딩 인덱스) ③ 웹 리서치(Tavily)를 교차 대조
- **AI/계산 분리** — 금액·한도 계산은 규칙 엔진이 전담, LLM은 판단 보조만 수행

## 기술 스택

- **LLM**: Claude API (tool use 기반 tool calling)
- **RAG**: model2vec 임베딩 + numpy 코사인 인덱스 (PDF 31권, 스캔본은 Tesseract OCR로 온프렘 처리)
- **외부 연동**: 법제처 Open API · DART Open API · Tavily 웹검색
- **백엔드/배포**: FastAPI · Docker · Railway (정적 데모는 Vercel)
- **산출물**: python-docx / matplotlib (DOCX 보고서 · 플로우차트 · Excel/PDF)
- **품질**: pytest **273건** · 기능 슬라이스별 평가 루브릭(LLM-judge) 90점 게이트 · Claude Code ↔ Codex 교차 리뷰 루프

## 실행 방법

```bash
pip install -r requirements-deploy.txt   # 또는 pyproject.toml 기반 설치
cp .env.example .env                     # API 키 입력 (법제처 OC·Anthropic·DART·Tavily)

python -m tiw run                        # CLI: 새 질문 → 13목차 자문 DOCX
python -m web.backend.run                # 웹: 라이브 백엔드 (web/live.html)
pytest tests -q                          # 테스트 273건
```

> 내부 RAG 인덱스는 저장소에 포함되지 않습니다(원본 PDF는 공개 세무 가이드).
> `scripts/build_rag_db_index.py` 로 각자 재생성합니다 — 인덱스 무결성은 manifest·hash로 fail-closed 검증됩니다.

## 저장소 구조

```
src/         핵심 로직 (자문 파이프라인 · 시나리오 플래너 · RAG · 보고서 렌더러)
web/         라이브 앱(FastAPI 백엔드 + live.html) · 정적 데모(demo.html)
tiw/         CLI 엔트리포인트
docs/        설계 문서 (RFP · ERD · 평가 루브릭 · 슬라이스별 명세)
tests/       pytest 273건 (외부 API는 fixture 재생·오프라인 replay)
contract/    기능 슬라이스 계약 정의
```

## 개발 방식

RFP(요구사항)와 ERD(데이터 모델)를 먼저 확정하고, 기능을 7개 슬라이스로 나눠
**Claude Code(구현) ↔ Codex(리뷰)** 교차 리뷰 루프로 개발했습니다.
각 슬라이스는 평가 루브릭 90점 게이트를 통과해야 다음 단계로 진행했습니다.

---

**면책**: 본 프로젝트는 학습·포트폴리오 목적의 소프트웨어이며, 산출물은 세무 전문가의 검토를 전제로 한 초안입니다. 실제 세무 신고·자문은 반드시 공인된 세무 전문가와 진행하십시오.
