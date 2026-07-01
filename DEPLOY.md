# 라이브 데모 배포 (면접관용 공개 URL)

FastAPI가 정적 웹(소개·데모·라이브)과 API를 **한 오리진**에서 서빙하므로, 컨테이너 하나만 배포하면
면접관이 단일 URL로 **실제 LLM 인테이크**(답변 분석→동적 질문·Excel/PDF 업로드·법제처 실근거·검토
패키지 DOCX)를 바로 사용할 수 있습니다.

> Vercel/서버리스는 이 백엔드에 부적합합니다(finalize ~수십 초 > 함수 타임아웃, 무거운 의존성).
> **컨테이너 호스트**(Render/Railway/Fly)를 사용합니다.

## 공개 데모 기본 정책
- **RAG off**(`LIVE_WITH_RAG=0`): 내부 실무 PDF(기밀)를 공개 호스트에 올리지 않음 + 이미지 경량화.
  핵심 기능(동적 LLM 인터뷰·**법제처 law.go.kr 실근거**·차트 DOCX)은 그대로 동작.
- **남용 방지**(로그인 없이 접근은 열되): IP당 분당 요청 상한 + 일일 분석 상한으로 유료 키 과다 소진 차단.
  - `LIVE_RATE_PER_MIN`(기본 20), `LIVE_DAILY_MSG_CAP`(기본 800), `LIVE_DAILY_FINALIZE_CAP`(기본 80)

## 필요한 키(호스트 Secret으로 입력 — 레포에 커밋 금지)
- `ANTHROPIC_API_KEY` — Claude 호출(유료).
- `LAW_OC` — 법제처 국가법령정보 OpenAPI 인증키(실판례·예규 근거).

## A. Render (권장 — 무료 티어 있음, 브라우저만으로 설정)
1. 이 레포를 GitHub에 올린다(기밀은 `.gitignore`로 이미 제외: `RAG DB/*.pdf`, `.env`).
   ```bash
   git add -A && git commit -m "chore: 배포 아티팩트"
   # GitHub에 빈 repo 생성 후:
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```
2. Render 대시보드 → **New → Blueprint** → 이 레포 선택(`render.yaml` 자동 인식).
3. `ANTHROPIC_API_KEY`, `LAW_OC` 값을 Secret으로 입력 → **Apply**.
4. 빌드(수 분) 후 `https://tax-ai-live.onrender.com/` 형태의 URL 생성 → 면접관에게 전달.
   - free 플랜은 유휴 시 슬립(첫 접속 30초 지연) + matplotlib 렌더 중 메모리 부족(OOM) 가능 →
     `render.yaml`의 `plan: starter` 권장.

## B. Railway / Fly.io (Dockerfile 그대로 사용)
- Railway: New Project → Deploy from Repo → 변수(`ANTHROPIC_API_KEY`,`LAW_OC`) 설정.
- Fly.io: `fly launch`(Dockerfile 감지) → `fly secrets set ANTHROPIC_API_KEY=... LAW_OC=...` → `fly deploy`.

## C. 로컬에서 컨테이너 확인(선택, Docker 필요)
```bash
docker build -t tax-ai-live .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=... -e LAW_OC=... tax-ai-live
# http://localhost:8000/  (소개→라이브)
```

## 배포 후 점검
- `GET /api/health` → `{"ok":true,"llm":true}`
- 소개(`/`) → 라이브(`/live.html`)에서 실제 인터뷰·업로드·보고서 다운로드 확인
- 차트 한글이 깨지면 `KOREAN_FONT_PATH`가 설치 폰트를 가리키는지 확인(이미지엔 `fonts-nanum` 포함).

## 참고
- 전체 RAG까지 포함해 운영하려면(전용 환경): `LIVE_WITH_RAG=1` + `RAG DB/` 동봉 + `pyproject.toml`
  전체 의존성 설치(chromadb/model2vec). 단, 내부 기밀자료가 포함되므로 **비공개** 환경에서만.
