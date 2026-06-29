"""src/ai/tavily_client.py — Tavily web-search adapter (docs/06, docs/07).

# WEB-002/003: official-source biased discovery (include_domains = 공식 도메인)
# WEB-005:     record every result as a SourceSnapshot (raw + content_hash)
# API-001/006/007/008: adapter boundary · rate-limit/timeout/fail-closed · cost log

RECORD/REPLAY transport seam mirroring ``src/ai/law_data_source.py`` and
``src/ai/llm_client.py``:

  * ``ReplayTavilyTransport``    — hermetic replay from ``tests/fixtures/web/`` with
    NO network and NO API key. DEFAULT for tests/CI and ``python -m tiw.eval``.
    A missing fixture is FAIL-CLOSED (``WebSearchUnavailable``); a hash-mismatched
    fixture is ``WebNotReproducible`` — never a silent pass (PROMPT.md §4-5).
  * ``RecordingTavilyTransport`` — performs ONE live ``POST api.tavily.com/search``
    and records the raw response (bytes + content_hash) to a fixture. Used only by
    ``scripts/record_web_fixtures.py`` (라이브 호출은 녹화 목적 1회만).

KEY HANDLING (PROMPT.md 비밀키 금지): the API key is read from env
(``TAVILY_API_KEY``) / ``.env`` and sent in the ``Authorization: Bearer`` header —
NEVER written to a fixture, manifest, or log. The recorder additionally redacts
the key from the response bytes BEFORE hashing (defensive; the key is not normally
echoed). The request BODY is built in-process as UTF-8 JSON (한글 쿼리 cp949 깨짐
방지 — never pass Korean through a shell CLI).

This module imports nothing heavy at import time; ``requests``/``urllib`` are
lazy-imported only inside the live recording path, so the deterministic harness
runs hermetically on the core install (pydantic+pyyaml).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .base import AdapterConfigError  # noqa: F401  (kept importable for back-compat)

# repo root = .../src/ai/tavily_client.py → parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEB_FIXTURES_DIR = _REPO_ROOT / "tests" / "fixtures" / "web"

_TAVILY_URL = "https://api.tavily.com/search"

# Official Korean tax/law authorities (docs/06 §4 허용·우선). Discovery is biased to
# these via ``include_domains``; the post-retrieval Source Policy (src.web_research)
# re-checks the RETURNED url against this set (WEB-007 사후 필터).
OFFICIAL_DOMAINS: tuple[str, ...] = (
    "nts.go.kr",     # 국세청
    "law.go.kr",     # 법제처 국가법령정보센터
    "moef.go.kr",    # 기획재정부
    "tt.go.kr",      # 조세심판원
    "scourt.go.kr",  # 대법원
)

PUBLISHER_BY_DOMAIN: dict[str, str] = {
    "nts.go.kr": "국세청",
    "law.go.kr": "법제처 국가법령정보센터",
    "moef.go.kr": "기획재정부",
    "tt.go.kr": "조세심판원",
    "scourt.go.kr": "대법원",
}


# --------------------------------------------------------------------------- #
# Errors (fail-closed surface)
# --------------------------------------------------------------------------- #
class WebSearchError(RuntimeError):
    """Base error for the web-search adapter layer."""


class WebSearchUnavailable(WebSearchError):
    """Backend not wired / fixture missing / key absent / network down → fail-closed."""


class WebNotReproducible(WebSearchError):
    """Recorded fixture hash does not match its bytes (replay integrity)."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def registrable_domain(url: str) -> str:
    """Best-effort registrable host for an http(s) url (no external deps).

    Returns the host's last two labels for normal domains and last three for the
    Korean ``*.go.kr`` second-level pattern, so ``txsi.hometax.go.kr`` →
    ``hometax.go.kr`` but ``www.nts.go.kr`` → ``nts.go.kr``. Used by the Source
    Policy filter to map a returned url to an official authority."""
    u = (url or "").strip().lower()
    if "://" in u:
        u = u.split("://", 1)[1]
    host = u.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    host = host.split("@")[-1].split(":")[0]
    labels = [p for p in host.split(".") if p]
    if len(labels) <= 2:
        return ".".join(labels)
    # go.kr / co.kr / or.kr style second-level TLD → keep three labels
    if labels[-1] == "kr" and labels[-2] in {"go", "co", "or", "ne", "re", "pe"}:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def official_domain_of(url: str) -> Optional[str]:
    """The official authority domain a url belongs to, or None if non-official.

    Matches by SUFFIX on the registrable domain so subdomains of an authority
    (e.g. ``txsi.hometax.go.kr`` is NOT an authority here, but ``www.nts.go.kr`` is)
    resolve correctly. Only the explicit OFFICIAL_DOMAINS authorities qualify."""
    reg = registrable_domain(url)
    host = (url or "").strip().lower()
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].split(":")[0]
    for dom in OFFICIAL_DOMAINS:
        if reg == dom or host == dom or host.endswith("." + dom):
            return dom
    return None


# --------------------------------------------------------------------------- #
# Request / response value objects
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TavilyRequest:
    """A canonical, hashable Tavily search request. The key pins (query,
    max_results, include_domains, search_depth) so the SAME query deterministically
    resolves to the SAME fixture between record and replay."""

    query: str
    max_results: int = 8
    include_domains: tuple[str, ...] = OFFICIAL_DOMAINS
    search_depth: str = "advanced"
    topic: str = "general"

    def _canonical(self) -> str:
        return json.dumps(
            {
                "query": self.query,
                "max_results": self.max_results,
                "include_domains": sorted(self.include_domains),
                "search_depth": self.search_depth,
                "topic": self.topic,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @property
    def key(self) -> str:
        return hashlib.sha256(self._canonical().encode("utf-8")).hexdigest()

    @property
    def filename(self) -> str:
        return f"tavily_{self.key[:16]}.json"

    def body(self) -> dict:
        """The live POST body (built in-process as UTF-8). ``include_raw_content``
        pulls the ORIGINAL page text, not just a snippet (docs/06 §6 원문 추출)."""
        return {
            "query": self.query,
            "max_results": self.max_results,
            "include_domains": list(self.include_domains),
            "include_raw_content": True,
            "search_depth": self.search_depth,
            "topic": self.topic,
        }


@dataclass(frozen=True)
class TavilyResult:
    """One search hit. ``content`` is the ORIGINAL extracted text (raw_content when
    present, else the snippet) — docs/06 §6 snippet 금지."""

    title: str
    url: str
    content: str
    score: float
    published_date: Optional[str]
    domain: str
    official: bool
    content_hash: str

    @property
    def publisher(self) -> Optional[str]:
        dom = official_domain_of(self.url)
        return PUBLISHER_BY_DOMAIN.get(dom) if dom else None


@dataclass
class TavilyResponse:
    query: str
    results: list[TavilyResult]
    origin: str              # "fixture" | "live"
    content_hash: str
    retrieved_at: Optional[str] = None   # ISO ts (manifest recorded_at on replay) — reproducible
    raw: dict = field(default_factory=dict)


def _parse_results(payload: dict) -> list[TavilyResult]:
    out: list[TavilyResult] = []
    for r in payload.get("results", []) or []:
        url = str(r.get("url", "")).strip()
        # original text first (include_raw_content), fall back to snippet
        content = str(r.get("raw_content") or r.get("content") or "").strip()
        dom = official_domain_of(url)
        out.append(
            TavilyResult(
                title=str(r.get("title", "")).strip(),
                url=url,
                content=content,
                score=float(r.get("score", 0.0) or 0.0),
                published_date=(str(r["published_date"]).strip() if r.get("published_date") else None),
                domain=dom or registrable_domain(url),
                official=dom is not None,
                content_hash=_sha256(content.encode("utf-8")),
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Transports
# --------------------------------------------------------------------------- #
class ReplayTavilyTransport:
    """Resolves a ``TavilyRequest`` from a recorded fixture (NO network/key).

    Fail-closed: no fixture → ``WebSearchUnavailable``; tampered bytes (hash
    mismatch) → ``WebNotReproducible``."""

    def __init__(self, fixtures_dir: Path = DEFAULT_WEB_FIXTURES_DIR) -> None:
        self._dir = Path(fixtures_dir)
        self._manifest_path = self._dir / "manifest.json"
        self._manifest: dict = {}
        if self._manifest_path.exists():
            self._manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))

    def resolve(self, req: TavilyRequest) -> TavilyResponse:
        entry = self._manifest.get(req.key)
        if entry is None:
            raise WebSearchUnavailable(
                f"no recorded Tavily fixture for query {req.query!r} (key {req.key[:12]}…) — "
                f"run scripts/record_web_fixtures.py once to record it"
            )
        path = self._dir / entry["file"]
        if not path.exists():
            raise WebSearchUnavailable(f"Tavily fixture file missing: {entry['file']}")
        content = path.read_bytes()
        digest = _sha256(content)
        if digest != entry["content_hash"]:
            raise WebNotReproducible(
                f"Tavily fixture {entry['file']} hash mismatch: recorded "
                f"{entry['content_hash'][:12]} != actual {digest[:12]} — refusing tampered replay"
            )
        # FAIL-CLOSED provenance (codex P1): retrieved_at MUST come from the recorded
        # manifest so the SourceSnapshot.retrieved_at is reproducible — never a
        # wall-clock now() on the replay path. A fixture missing / with an unparseable
        # recorded_at is refused (non-reproducible provenance).
        recorded_at = entry.get("recorded_at")
        if not recorded_at:
            raise WebNotReproducible(
                f"Tavily fixture {entry['file']} missing recorded_at — "
                f"non-reproducible retrieved_at provenance"
            )
        try:
            datetime.fromisoformat(recorded_at)
        except (TypeError, ValueError) as exc:
            raise WebNotReproducible(
                f"Tavily fixture {entry['file']} recorded_at {recorded_at!r} unparseable"
            ) from exc
        payload = json.loads(content.decode("utf-8"))
        return TavilyResponse(
            query=req.query,
            results=_parse_results(payload),
            origin="fixture",
            content_hash=digest,
            retrieved_at=recorded_at,   # reproducible retrieved_at (replay)
            raw=payload,
        )


class RecordingTavilyTransport:  # pragma: no cover - live, one-time recording only
    """Performs the live Tavily call and records the raw response to a fixture.

    Reads ``TAVILY_API_KEY`` from env/.env (never hardcoded), sends it in the
    Authorization header, and writes ONLY OC-free response bytes. Rate-limit /
    timeout / HTTP errors are fail-closed (``WebSearchUnavailable``)."""

    def __init__(self, fixtures_dir: Path = DEFAULT_WEB_FIXTURES_DIR,
                 api_key_env: str = "TAVILY_API_KEY", timeout: int = 40) -> None:
        self._dir = Path(fixtures_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout
        self._api_key_env = api_key_env
        self._key = self._load_key(api_key_env)
        if not self._key:
            raise WebSearchUnavailable(
                f"{api_key_env} not set (.env) — cannot record live Tavily fixtures"
            )
        self._manifest_path = self._dir / "manifest.json"
        self._manifest: dict = {}
        if self._manifest_path.exists():
            self._manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))

    @staticmethod
    def _load_key(env_name: str) -> Optional[str]:
        import os

        key = os.environ.get(env_name)
        if key:
            return key.strip()
        env_path = _REPO_ROOT / ".env"
        if not env_path.exists():
            return None
        try:
            from dotenv import dotenv_values  # type: ignore

            return (dotenv_values(env_path) or {}).get(env_name, "").strip() or None
        except Exception:  # noqa: BLE001 - stdlib fallback parser
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith(f"{env_name}="):
                    return line.split("=", 1)[1].strip().strip('"').strip() or None
        return None

    def _http_post(self, body: dict) -> bytes:
        # body is built/serialized in-process as UTF-8 (NEVER via shell — cp949).
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }
        try:
            import requests  # type: ignore

            resp = requests.post(_TAVILY_URL, data=data, headers=headers, timeout=self._timeout)
            if resp.status_code == 429:
                raise WebSearchUnavailable("Tavily rate-limited (HTTP 429) — fail-closed")
            resp.raise_for_status()
            return resp.content
        except WebSearchError:
            raise
        except ImportError:  # stdlib fallback
            import urllib.error
            import urllib.request

            req = urllib.request.Request(_TAVILY_URL, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as r:  # noqa: S310
                    return r.read()
            except urllib.error.HTTPError as exc:  # noqa: PERF203
                if exc.code == 429:
                    raise WebSearchUnavailable("Tavily rate-limited (HTTP 429) — fail-closed") from exc
                raise WebSearchUnavailable(f"Tavily HTTP {exc.code} — fail-closed") from exc
            except urllib.error.URLError as exc:
                raise WebSearchUnavailable(f"Tavily network error — fail-closed: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - requests-side network/timeout
            raise WebSearchUnavailable(f"Tavily request failed — fail-closed: {exc}") from exc

    def resolve(self, req: TavilyRequest) -> TavilyResponse:
        content = self._http_post(req.body())
        # SECRET REDACTION (defensive): strip the key from the bytes BEFORE hashing
        # so no secret can ever enter a committed fixture, even if echoed.
        content = content.replace(self._key.encode("utf-8"), b"***")
        digest = _sha256(content)
        fname = req.filename
        (self._dir / fname).write_bytes(content)
        self._manifest[req.key] = {
            "file": fname,
            "content_hash": digest,
            "query": req.query,
            "include_domains": sorted(req.include_domains),
            "max_results": req.max_results,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "bytes": len(content),
        }
        self._manifest_path.write_text(
            json.dumps(self._manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        payload = json.loads(content.decode("utf-8"))
        return TavilyResponse(
            query=req.query, results=_parse_results(payload), origin="live",
            content_hash=digest,
            retrieved_at=self._manifest[req.key]["recorded_at"], raw=payload,
        )


# --------------------------------------------------------------------------- #
# Client facade
# --------------------------------------------------------------------------- #
class TavilyClient:
    """Tavily web-search client over a record/replay transport.

    DEFAULT transport is REPLAY (hermetic, no key) so the eval harness and tests
    are deterministic and offline. Pass a ``RecordingTavilyTransport`` only from
    the one-time recording script."""

    def __init__(self, api_key_env: str = "TAVILY_API_KEY",
                 transport: Optional[object] = None,
                 include_domains: tuple[str, ...] = OFFICIAL_DOMAINS,
                 max_results: int = 8) -> None:
        self.api_key_env = api_key_env
        self.transport = transport or ReplayTavilyTransport()
        self.include_domains = tuple(include_domains)
        self.max_results = max_results
        self.calls: list[TavilyResponse] = []  # in-process call log (docs/07 §2)

    def search(self, query: str, max_results: Optional[int] = None,
               include_domains: Optional[tuple[str, ...]] = None) -> TavilyResponse:
        req = TavilyRequest(
            query=query,
            max_results=max_results or self.max_results,
            include_domains=tuple(include_domains if include_domains is not None else self.include_domains),
        )
        resp = self.transport.resolve(req)
        self.calls.append(resp)
        return resp


def default_tavily_client(fixtures_dir: Path = DEFAULT_WEB_FIXTURES_DIR,
                          include_domains: tuple[str, ...] = OFFICIAL_DOMAINS) -> TavilyClient:
    """Hermetic replay client (no key/network). Fail-closed on missing fixtures."""
    return TavilyClient(transport=ReplayTavilyTransport(fixtures_dir),
                        include_domains=include_domains)


__all__ = [
    "OFFICIAL_DOMAINS", "PUBLISHER_BY_DOMAIN", "registrable_domain", "official_domain_of",
    "TavilyRequest", "TavilyResult", "TavilyResponse",
    "ReplayTavilyTransport", "RecordingTavilyTransport", "TavilyClient", "default_tavily_client",
    "WebSearchError", "WebSearchUnavailable", "WebNotReproducible",
]
