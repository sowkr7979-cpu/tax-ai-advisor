"""src/dart_fetch.py — OpenDART(전자공시) 실(實)연동 재무제표 회수.

임의의 상장사 1곳을 **DART OpenAPI** 로 조회해 재무상태표·손익계산서 라인을 가져온다.
회수 응답은 ``tests/fixtures/dart/`` 에 캐시(JSON)해 재현 가능하게 한다(키 없이 replay).

OpenDART 흐름:
* ``corpCode.xml`` (zip) → 회사명/종목코드 ↔ ``corp_code`` 매핑(1회 다운로드·캐시).
* ``fnlttSinglAcntAll.json`` → 단일회사 전체 재무제표(당기 금액). ``fs_div`` OFS(개별/별도)·CFS(연결).

키는 ``.env`` 의 ``DART_API_KEY`` 에서 읽으며, 캐시/픽스처엔 저장하지 않는다(노출 차단).
"""
from __future__ import annotations

import io
import json
import os
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parents[1]
_FIX_DIR = _REPO / "tests" / "fixtures" / "dart"
_CORP_CACHE = _FIX_DIR / "corp_code_map.json"
_API = "https://opendart.fss.or.kr/api"


class DartError(RuntimeError):
    pass


def _load_key() -> str:
    key = os.environ.get("DART_API_KEY")
    if not key:
        env = _REPO / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("DART_API_KEY"):
                    key = line.split("=", 1)[1].strip()
                    break
    if not key:
        raise DartError("DART_API_KEY 가 .env/환경변수에 없습니다.")
    return key


# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FsLine:
    name: str           # 계정명(account_nm)
    amount: float       # 당기금액(thstrm_amount)
    statement: str      # 'BS' | 'IS' | 'CIS' | 'CF'


@dataclass(frozen=True)
class CompanyFinancials:
    corp_name: str
    corp_code: str
    stock_code: str
    year: int
    fs_div: str         # OFS / CFS
    lines: tuple[FsLine, ...]

    def find(self, *needles: str, statement: Optional[str] = None) -> Optional[float]:
        """계정 금액 조회. **완전일치 우선**(부분일치는 그 다음) — '자본총계' 가 '부채및자본
        총계' 에 잘못 매칭되는 것을 방지(codex 적발). statement 로 표 한정."""
        cands = [ln for ln in self.lines if not statement or ln.statement == statement]
        # 1) 계정명 완전일치(공백 무시) 우선
        for ln in cands:
            if any(ln.name.strip() == nd for nd in needles):
                return ln.amount
        # 2) 없으면 부분일치(보조 라인용)
        for ln in cands:
            if any(nd in ln.name for nd in needles):
                return ln.amount
        return None

    def bs(self) -> list[FsLine]:
        return [ln for ln in self.lines if ln.statement == "BS"]

    def is_(self) -> list[FsLine]:
        return [ln for ln in self.lines if ln.statement in ("IS", "CIS")]


# --------------------------------------------------------------------------- #
def _corp_map(*, refresh: bool = False) -> dict:
    """회사명/종목코드 → corp_code 매핑(캐시). 큰 zip 은 1회만 받는다."""
    if _CORP_CACHE.exists() and not refresh:
        return json.loads(_CORP_CACHE.read_text(encoding="utf-8"))
    import xml.etree.ElementTree as ET

    key = _load_key()
    with urllib.request.urlopen(f"{_API}/corpCode.xml?crtfc_key={key}", timeout=90) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read(z.namelist()[0]))
    by_name: dict[str, list] = {}
    by_stock: dict[str, list] = {}
    for el in root.iter("list"):
        nm = (el.findtext("corp_name") or "").strip()
        sc = (el.findtext("stock_code") or "").strip()
        cc = (el.findtext("corp_code") or "").strip()
        if not (nm and cc):
            continue
        rec = {"corp_name": nm, "corp_code": cc, "stock_code": sc}
        by_name.setdefault(nm, rec)
        if sc:
            by_stock.setdefault(sc, rec)
    out = {"by_name": by_name, "by_stock": by_stock}
    _FIX_DIR.mkdir(parents=True, exist_ok=True)
    _CORP_CACHE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def resolve(name_or_stock: str) -> dict:
    """회사명(정확) 또는 6자리 종목코드 → {corp_name, corp_code, stock_code}."""
    m = _corp_map()
    s = name_or_stock.strip()
    if s.isdigit() and len(s) == 6:
        rec = m["by_stock"].get(s)
    else:
        rec = m["by_name"].get(s)
    if not rec:
        raise DartError(f"회사를 찾을 수 없습니다: {name_or_stock}")
    return rec


_SJ = {"BS": "BS", "IS": "IS", "CIS": "CIS", "CF": "CF"}


def fetch_financials(
    corp_code: str, year: int, *, reprt_code: str = "11011", fs_div: str = "OFS",
    corp_name: str = "", stock_code: str = "", use_cache: bool = True,
) -> CompanyFinancials:
    """단일회사 전체 재무제표 회수(당기 금액). 캐시 JSON 있으면 재사용(재현성)."""
    _FIX_DIR.mkdir(parents=True, exist_ok=True)
    cache = _FIX_DIR / f"{corp_code}_{year}_{reprt_code}_{fs_div}.json"
    if use_cache and cache.exists():
        payload = json.loads(cache.read_text(encoding="utf-8"))
    else:
        key = _load_key()
        url = (f"{_API}/fnlttSinglAcntAll.json?crtfc_key={key}&corp_code={corp_code}"
               f"&bsns_year={year}&reprt_code={reprt_code}&fs_div={fs_div}")
        with urllib.request.urlopen(url, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
        payload = json.loads(raw)
        # 정상 응답만 캐시(오류 응답을 캐시해 영구화하지 않음). 키(url)는 저장 안 함.
        if payload.get("status") == "000":
            cache.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    # **캐시·라이브 양쪽 모두** status 검증(codex 적발 — 캐시 경로 우회 차단).
    if payload.get("status") != "000":
        raise DartError(f"DART 응답 오류 status={payload.get('status')} "
                        f"msg={payload.get('message')}")

    lines: list[FsLine] = []
    for it in payload.get("list", []):
        sj = it.get("sj_div", "")
        if sj not in _SJ:
            continue
        amt = (it.get("thstrm_amount") or "").replace(",", "").strip()
        try:
            val = float(amt)
        except ValueError:
            continue
        name = (it.get("account_nm") or "").strip()
        if name:
            lines.append(FsLine(name=name, amount=val, statement=_SJ[sj]))
    return CompanyFinancials(
        corp_name=corp_name, corp_code=corp_code, stock_code=stock_code,
        year=year, fs_div=fs_div, lines=tuple(lines),
    )


def load_company(name_or_stock: str, year: int, *, fs_div: str = "OFS") -> CompanyFinancials:
    """회사명/종목코드 + 연도 → 재무제표(해소 + 회수, 캐시). OFS 비면 CFS 폴백."""
    rec = resolve(name_or_stock)
    fin = fetch_financials(rec["corp_code"], year, fs_div=fs_div,
                           corp_name=rec["corp_name"], stock_code=rec["stock_code"])
    if not fin.lines and fs_div == "OFS":
        fin = fetch_financials(rec["corp_code"], year, fs_div="CFS",
                               corp_name=rec["corp_name"], stock_code=rec["stock_code"])
    if not fin.lines:
        # 폴백 후에도 라인 0건이면 빈 객체를 조용히 반환하지 않고 fail-closed(codex 적발)
        raise DartError(
            f"DART 재무 라인 0건: {rec['corp_name']}({rec['corp_code']}) {year} — "
            "사업연도/보고서코드/재무제표구분 확인 필요.")
    return fin
