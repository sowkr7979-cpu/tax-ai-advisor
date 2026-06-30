"""src/law_open_api.py — 법제처 국가법령정보 Open API(DRF) 실시간 조회: 법령·판례·해석례.

korean-law 채널을 '법령 검색'에만 한정하지 않고 **최신 판례·법령해석례(예규/질의해석)**까지
검토하기 위한 어댑터. 키워드로 ``target`` 별 조회한다:
* ``law``  — 현행 법령
* ``prec`` — 판례(대법원·국세법령정보시스템 등)
* ``expc`` — 법령해석례(정부유권해석)

OC 키는 ``.env`` 의 ``LAW_OC`` 에서만 읽는다. DRF 응답은 상세링크에 **OC 를 echo** 하므로,
캐시/표시 전에 OC 를 ``***`` 로 **redact** 한다(비밀키 노출 차단). 응답은
``tests/fixtures/law_open/`` 에 캐시(재현)하며, 캐시엔 redact 된 본문만 저장한다.

fail-closed: 네트워크/파싱 실패는 ``LawOpenError`` 로 올린다(상위 렌더러가 '조회 불가'로 정직
표기). 날조 없음 — 회수된 실제 판례/해석례만 표시한다.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parents[1]
_FIX = _REPO / "tests" / "fixtures" / "law_open"
_BASE = "https://www.law.go.kr/DRF/lawSearch.do"
_PORTAL = "https://www.law.go.kr"

_KIND = {"law": "법령", "prec": "판례", "expc": "법령해석례"}


class LawOpenError(RuntimeError):
    pass


@dataclass(frozen=True)
class LawHit:
    kind: str           # 법령 | 판례 | 법령해석례
    title: str          # 법령명 / 사건명 / 안건명
    ident: str          # 사건번호 / 안건번호 / 공포번호
    date: str           # 선고일자 / 회신일자 / 시행일자
    source: str         # 데이터출처명 / 해석기관
    url: str            # 포털 링크(OC 미포함)


def _load_oc() -> str:
    oc = os.environ.get("LAW_OC")
    if not oc:
        env = _REPO / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("LAW_OC="):
                    oc = line.split("=", 1)[1].strip().strip('"')
                    break
    if not oc:
        raise LawOpenError("LAW_OC 가 .env/환경변수에 없습니다.")
    return oc.strip()


def _first(el: ET.Element, *tags: str) -> str:
    for t in tags:
        node = el.find(t)
        if node is not None and (node.text or "").strip():
            return node.text.strip()
    return ""


def _portal_link(detail_link: str, oc: str) -> str:
    """DRF 상세링크(OC echo 포함) → OC 제거한 포털 절대링크."""
    if not detail_link:
        return _PORTAL
    link = detail_link.replace(oc, "***") if oc else detail_link  # 빈 OC로 URL 손상 방지
    if link.startswith("/"):
        return _PORTAL + link
    return link


def _search_raw(target: str, query: str, display: int, *, use_cache: bool) -> bytes:
    """DRF lawSearch 호출(또는 캐시). 응답에서 OC 를 redact 한 bytes 반환."""
    _FIX.mkdir(parents=True, exist_ok=True)
    key = f"{target}|{query}|{display}"
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    cache = _FIX / f"{target}_{h}.xml"
    if use_cache and cache.exists():
        return cache.read_bytes()
    oc = _load_oc()
    qs = urllib.parse.urlencode({"OC": oc, "target": target, "type": "XML",
                                 "query": query, "display": str(display)})
    try:
        with urllib.request.urlopen(f"{_BASE}?{qs}", timeout=30) as resp:
            content = resp.read()
    except Exception as exc:  # noqa: BLE001
        raise LawOpenError(f"법제처 DRF 조회 실패({target}, '{query}'): {type(exc).__name__}") from exc
    # OC redaction — 응답 상세링크에 echo 된 키 제거 후에만 캐시/반환(노출 차단)
    content = content.replace(oc.encode("utf-8"), b"***")
    # **정상 응답만 캐시**(codex HIGH): 인증/오류 본문(검색 메타 totalCnt 없음)을 '0건'으로
    # 영구화하지 않는다 — 파싱 실패·메타 부재면 캐시하지 않고 fail-closed.
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise LawOpenError(f"법제처 응답 파싱 실패({target}, '{query}'): {exc}") from exc
    if root.findtext("totalCnt") is None:
        raise LawOpenError(
            f"법제처 응답에 검색 메타(totalCnt) 없음 — 오류/인증 실패 의심({target}, '{query}')")
    cache.write_bytes(content)
    return content


def search(target: str, query: str, *, display: int = 3, use_cache: bool = True) -> list[LawHit]:
    """target(law|prec|expc) 키워드 조회 → LawHit 목록(실제 회수만, 날조 0)."""
    if target not in _KIND:
        raise LawOpenError(f"지원하지 않는 target: {target}")
    content = _search_raw(target, query, display, use_cache=use_cache)
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise LawOpenError(f"법제처 응답 파싱 실패({target}): {exc}") from exc
    oc = ""  # 링크 redaction 은 이미 _search_raw 에서 됐지만, 안전하게 한 번 더
    try:
        oc = _load_oc()
    except LawOpenError:
        pass
    hits: list[LawHit] = []
    item_tags = {"law": "law", "prec": "prec", "expc": "expc"}
    for el in root.iter(item_tags[target]):
        if target == "prec":
            hit = LawHit(
                kind="판례",
                title=_first(el, "사건명"),
                ident=_first(el, "사건번호"),
                date=_first(el, "선고일자"),
                source=_first(el, "데이터출처명", "법원명"),
                url=_portal_link(_first(el, "판례상세링크"), oc),
            )
        elif target == "expc":
            hit = LawHit(
                kind="법령해석례",
                title=_first(el, "안건명", "법령해석례명"),
                ident=_first(el, "안건번호", "해석례일련번호"),
                date=_first(el, "회신일자", "해석일자"),
                source=_first(el, "해석기관명", "질의기관명"),
                url=_portal_link(_first(el, "법령해석례상세링크", "상세링크"), oc),
            )
        else:  # law
            hit = LawHit(
                kind="법령",
                title=_first(el, "법령명한글", "법령명"),
                ident=_first(el, "공포번호"),
                date=_first(el, "시행일자"),
                source=_first(el, "소관부처명", "제개정구분명"),
                url=_portal_link(_first(el, "법령상세링크"), oc),
            )
        if hit.title:
            hits.append(hit)
    return hits


def research_issue(keywords: str, *, per_target: int = 2, use_cache: bool = True) -> dict:
    """한 쟁점에 대해 판례·해석례·법령을 함께 조회(예규·판례·질의해석 검토).

    반환: {'판례': [LawHit...], '법령해석례': [...], '법령': [...]}. 일부 target 실패는
    그 target 만 빈 목록(부분 degrade) — 전체를 막지 않되, 호출측이 '조회 불가'를 표기할 수 있게
    예외는 삼키지 않고 target별로 분리 수집한다."""
    out: dict[str, list] = {"판례": [], "법령해석례": [], "법령": []}
    errors: list[str] = []
    for target in ("prec", "expc", "law"):
        try:
            out[_KIND[target]] = search(target, keywords, display=per_target, use_cache=use_cache)
        except LawOpenError as exc:
            errors.append(str(exc))
    out["_errors"] = errors
    return out
