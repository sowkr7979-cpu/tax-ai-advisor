# 세무 AI 라이브 백엔드(FastAPI) — 컨테이너 이미지.
# FastAPI가 정적 웹(index/demo/live + assets)과 API를 한 오리진에서 서빙 → 단일 URL로 면접관이 바로 사용.
# 공개 데모 기본값: RAG off(기밀 내부자료 미노출·경량), 법제처(law.go.kr) 실근거 on, 차트 on.
FROM python:3.12-slim

# 한글 폰트(matplotlib 차트 렌더링용). 없으면 차트 라벨이 깨진다.
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-nanum fontconfig \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    KOREAN_FONT_PATH=/usr/share/fonts/truetype/nanum/NanumGothic.ttf \
    LIVE_WITH_RAG=0 \
    LIVE_WITH_LAW=1

WORKDIR /app

COPY requirements-deploy.txt .
RUN pip install -r requirements-deploy.txt

# 앱 코드만 복사(.dockerignore가 기밀 RAG DB·.env·산출물·테스트 등 제외).
COPY src ./src
COPY rules ./rules
COPY web ./web

EXPOSE 8000
# 호스트가 주입하는 $PORT 사용(Render/Railway/Fly), 없으면 8000.
CMD ["sh", "-c", "uvicorn web.backend.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
