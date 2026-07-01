"""web/backend/app.py — 라이브 세무 인테이크 FastAPI 앱.

동일 오리진에서 정적 웹(index/demo/live + assets)과 API를 함께 서빙한다.
실행:  레포 루트에서  python -m web.backend.run   (또는 uvicorn web.backend.app:app)
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import files as filemod
from . import intake, llm

WEB_DIR = Path(__file__).resolve().parents[1]  # .../web
log = logging.getLogger("web.backend")

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15MB — 데모 파일 상한
ALLOWED_EXT = (".xlsx", ".xlsm", ".xls", ".csv", ".pdf")

# --- 공개 배포용 남용 방지(유료 키 과다 소진 차단) ------------------------------- #
# 로그인 없이 접근은 열되, IP당 분당 요청 상한 + 전체 일일 상한(특히 비싼 finalize).
RATE_PER_MIN = int(os.environ.get("LIVE_RATE_PER_MIN", "20"))
DAILY_MSG_CAP = int(os.environ.get("LIVE_DAILY_MSG_CAP", "800"))
DAILY_FINALIZE_CAP = int(os.environ.get("LIVE_DAILY_FINALIZE_CAP", "80"))
_ip_hits: dict[str, deque] = defaultdict(deque)
_daily = {"day": "", "msg": 0, "final": 0}

app = FastAPI(title="세무 AI 라이브 인테이크")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    return (xff.split(",")[0].strip() if xff else (request.client.host if request.client else "?"))


def _rate_guard(request: Request) -> None:
    """IP당 슬라이딩 1분 창 요청 상한. 초과 시 429."""
    now = time.monotonic()
    dq = _ip_hits[_client_ip(request)]
    while dq and now - dq[0] > 60:
        dq.popleft()
    if len(dq) >= RATE_PER_MIN:
        raise HTTPException(status_code=429, detail="요청이 많습니다. 잠시 후 다시 시도해 주세요.")
    dq.append(now)


def _daily_guard(kind: str) -> None:
    """전체 일일 상한(과다 과금 방지). kind: 'msg' | 'final'."""
    day = time.strftime("%Y-%m-%d", time.gmtime())
    if _daily["day"] != day:
        _daily.update(day=day, msg=0, final=0)
    if kind == "final":
        if _daily["final"] >= DAILY_FINALIZE_CAP:
            raise HTTPException(status_code=429, detail="오늘 데모 분석 한도에 도달했습니다. 내일 다시 이용해 주세요.")
        _daily["final"] += 1
    else:
        if _daily["msg"] >= DAILY_MSG_CAP:
            raise HTTPException(status_code=429, detail="오늘 데모 이용 한도에 도달했습니다. 내일 다시 이용해 주세요.")
        _daily["msg"] += 1


def _fail(status: int, public_msg: str, e: Exception) -> JSONResponse:
    """내부 예외 상세(경로·키·라이브러리 메시지)를 클라이언트에 노출하지 않는다."""
    log.exception("%s: %s", public_msg, e)
    return JSONResponse(status_code=status, content={"detail": public_msg})


class StartReq(BaseModel):
    pass


class MsgReq(BaseModel):
    session_id: str
    text: str = ""


class FinalizeReq(BaseModel):
    session_id: str


@app.get("/api/health")
def health():
    return {"ok": True, "llm": llm.llm_available()}


@app.post("/api/session/start")
def session_start(_: StartReq | None = None):
    return intake.start_session()


@app.post("/api/message")
def message(req: MsgReq, request: Request):
    _rate_guard(request)
    _daily_guard("msg")
    try:
        return intake.handle_message(req.session_id, req.text)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="세션이 만료되었거나 존재하지 않습니다. 새로고침해 주세요.") from e
    except Exception as e:  # noqa: BLE001
        return _fail(500, "인테이크 처리 중 오류가 발생했습니다.", e)


@app.post("/api/upload")
async def upload(request: Request, session_id: str = Form(...), file: UploadFile = File(...)):
    _rate_guard(request)
    _daily_guard("msg")
    fname = file.filename or "upload"
    if not fname.lower().endswith(ALLOWED_EXT):
        raise HTTPException(status_code=415, detail="지원하지 않는 파일 형식입니다(Excel·CSV·PDF만 허용).")
    try:
        # 전체를 한 번에 읽지 않고 청크로 읽어 상한 초과 시 즉시 중단(메모리 보호).
        buf = bytearray()
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            buf.extend(chunk)
            if len(buf) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="파일이 너무 큽니다(최대 15MB).")
        ex = filemod.extract(fname, bytes(buf))
        return intake.handle_file(session_id, ex)
    except HTTPException:
        raise
    except KeyError as e:
        raise HTTPException(status_code=404, detail="세션이 만료되었거나 존재하지 않습니다. 새로고침해 주세요.") from e
    except Exception as e:  # noqa: BLE001
        return _fail(500, "파일을 처리하지 못했습니다.", e)


@app.post("/api/finalize")
def finalize(req: FinalizeReq, request: Request):
    _rate_guard(request)
    _daily_guard("final")  # 비싼 호출(sonnet ~수십초) — 일일 상한 별도
    try:
        return intake.finalize(req.session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="세션이 만료되었거나 존재하지 않습니다. 새로고침해 주세요.") from e
    except intake.NotReadyError as e:  # 사용자 안내성 메시지만 노출
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001  (검증/생성 내부 오류는 상세 비노출)
        return _fail(500, "분석·보고서 생성 중 오류가 발생했습니다.", e)


@app.get("/api/report/{sid}")
def report(sid: str):
    s = intake.SESSIONS.get(sid)
    if not s or not s.report_path or not Path(s.report_path).exists():
        raise HTTPException(status_code=404, detail="보고서를 찾을 수 없습니다.")
    fname = f"검토패키지_{(s.tx_type or '세무거래').replace(' ', '')}.docx"
    return FileResponse(
        s.report_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=fname,
    )


# 정적 웹(가장 마지막에 마운트 — API 경로 우선). "/" → index.html
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
