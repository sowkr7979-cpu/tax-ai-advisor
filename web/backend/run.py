"""web/backend/run.py — 라이브 인테이크 서버 실행 런처.

사용:  레포 루트에서  python -m web.backend.run  [--port 8000] [--open]
접속:  http://127.0.0.1:8000/  (프로젝트 소개) · /live.html (라이브 데모)
"""
from __future__ import annotations

import argparse
import sys

from . import llm


def main() -> int:
    ap = argparse.ArgumentParser(description="세무 AI 라이브 인테이크 서버")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--open", action="store_true", help="브라우저 자동 열기")
    args = ap.parse_args()

    llm.load_env()
    status = "LIVE(Claude 연결)" if llm.llm_available() else "오프라인(ANTHROPIC_API_KEY 없음 — 라이브 인테이크 불가)"
    url = f"http://{args.host}:{args.port}/"
    print(f"세무 AI 라이브 서버 · {status}")
    print(f"  소개:   {url}")
    print(f"  라이브: {url}live.html")
    print(f"  정적 데모: {url}demo.html")
    if args.open:
        import webbrowser

        webbrowser.open(url + "live.html")

    import uvicorn

    uvicorn.run("web.backend.app:app", host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
