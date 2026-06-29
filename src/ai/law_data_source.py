"""src/ai/law_data_source.py — LawDataSource abstraction (slice ① 법령 코어).

# API-002  LawDataSource 추상화 + fallback(법제처/국세법령정보)
# API-003  as-of-date 시행일 버전 조회 (2개 연도 질의 → 다른 버전)
# API-004  외부 응답을 SourceSnapshot(content_hash)로 녹화 (재현성/결정적 replay)
# PROV-003/012  ProvisionVersion 시행일 버전 + effective_from inclusive

DESIGN DECISION (docs/07 §3, PROMPT.md §0):
  Channel ① is *designed* as korean-law-mcp, but MCP protocol wiring is heavy.
  So the WORKING backend here is the 법제처 국가법령정보 OpenAPI (DRF), exposed
  behind the ``LawDataSource`` interface as the PRIMARY implementation
  (``MOLEGLawDataSource``).  ``KoreanLawMCPSource`` is the by-design primary
  channel but ships UNWIRED (interface + TODO).  ``FallbackLawDataSource``
  expresses the API-003 chain [MCP → 법제처]: MCP is tried first, raises
  ``LawSourceUnavailable`` (not wired), and the 법제처 backend answers.

VERSION PINNING (API-003):  the DRF endpoint
  ``lawService.do?target=eflaw&LM=<법령명>&efYd=<YYYYMMDD>`` returns the law
  version *in force on* ``efYd`` — verified live: efYd=20200101 → 제25조 '접대비',
  efYd=20240101 → 제25조 '기업업무추진비'.  One call ⇒ correct 시행일 버전.

REPRODUCIBILITY (API-004):  every live response is recorded as a raw fixture +
  a SourceSnapshot ``content_hash``.  Tests REPLAY from fixtures with NO network.
  A missing fixture or a hash mismatch is FAIL-CLOSED (``LawSourceUnavailable`` /
  ``NotReproducible``) — never a silent pass (docs/09 §2, PROMPT.md §4).

This module imports NOTHING heavy at import time; ``requests``/``dotenv`` are
lazy-imported only inside the live RECORD path, so the deterministic harness runs
hermetically on the core install (pydantic+pyyaml).
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable

from contract.cluster_d_provenance import ProvisionVersion, SourceSnapshot

# repo root = .../src/ai/law_data_source.py → parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURES_DIR = _REPO_ROOT / "tests" / "fixtures" / "law"

_DRF_BASE = "https://www.law.go.kr/DRF"
PUBLISHER = "법제처 국가법령정보센터"


# --------------------------------------------------------------------------- #
# Errors (fail-closed surface)
# --------------------------------------------------------------------------- #
class LawSourceError(RuntimeError):
    """Base error for the law data source layer."""


class LawSourceUnavailable(LawSourceError):
    """Backend not wired / fixture missing / network down → try fallback or fail."""


class NotReproducible(LawSourceError):
    """Recorded fixture hash does not match its bytes (API-004 reproducibility)."""


class ProvisionNotFound(LawSourceError):
    """The requested article does not exist in the resolved version body."""


# --------------------------------------------------------------------------- #
# Request / response value objects
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DrfRequest:
    """A canonical DRF request (secret OC excluded — it never enters the key)."""

    endpoint: str               # "lawSearch" | "lawService"
    params: dict                # excludes OC; type=XML implied

    @property
    def key(self) -> str:
        body = "__".join(f"{k}={self.params[k]}" for k in sorted(self.params))
        return f"{self.endpoint}__{body}"

    @property
    def filename(self) -> str:
        ef = self.params.get("efYd")
        slug = self.endpoint + (f"_ef{ef}" if ef else "_search")
        digest = hashlib.sha1(self.key.encode("utf-8")).hexdigest()[:10]
        return f"{slug}_{digest}.xml"

    def url_redacted(self) -> str:
        qs = "&".join(f"{k}={v}" for k, v in {**self.params, "type": "XML", "OC": "***"}.items())
        return f"{_DRF_BASE}/{self.endpoint}.do?{qs}"


@dataclass(frozen=True)
class RawResponse:
    content: bytes
    content_hash: str
    url_redacted: str
    origin: str                 # "fixture" | "live"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- #
# Transports (replay = hermetic default; record = one-time live)
# --------------------------------------------------------------------------- #
class ReplayTransport:
    """Resolves DRF requests from recorded fixtures (NO network).

    Fail-closed: a request with no fixture raises ``LawSourceUnavailable``; a
    fixture whose bytes no longer hash to the recorded value raises
    ``NotReproducible`` (API-004)."""

    def __init__(self, fixtures_dir: Path = DEFAULT_FIXTURES_DIR) -> None:
        self._dir = Path(fixtures_dir)
        self._manifest_path = self._dir / "manifest.json"
        self._manifest: dict = {}
        if self._manifest_path.exists():
            self._manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))

    def resolve(self, req: DrfRequest) -> RawResponse:
        entry = self._manifest.get(req.key)
        if entry is None:
            raise LawSourceUnavailable(
                f"no recorded fixture for request '{req.key}' "
                f"(run scripts/record_law_fixtures.py once to record it)"
            )
        path = self._dir / entry["file"]
        if not path.exists():
            raise LawSourceUnavailable(f"fixture file missing: {entry['file']}")
        content = path.read_bytes()
        digest = _sha256(content)
        if digest != entry["content_hash"]:
            raise NotReproducible(
                f"fixture {entry['file']} hash mismatch: recorded {entry['content_hash'][:12]} "
                f"!= actual {digest[:12]} — refusing to replay tampered snapshot"
            )
        return RawResponse(content, digest, entry.get("url_redacted", ""), origin="fixture")


class RecordingTransport:
    """Performs the live DRF call and records raw bytes + manifest entry.

    Used ONCE to seed fixtures (PROMPT.md: 라이브 호출은 녹화용 최소 호출만).
    ``requests`` is preferred but falls back to stdlib ``urllib`` so the recorder
    runs even on the core install; the OC key is read from env (LAW_OC), never
    hardcoded (infra/config/vendors.yaml: korean_law_mcp.* / env-var names)."""

    def __init__(self, fixtures_dir: Path = DEFAULT_FIXTURES_DIR, oc: Optional[str] = None,
                 timeout: int = 40) -> None:
        self._dir = Path(fixtures_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout
        self._oc = oc or self._load_oc()
        if not self._oc:
            raise LawSourceUnavailable("LAW_OC not set (.env) — cannot record live fixtures")
        self._manifest_path = self._dir / "manifest.json"
        self._manifest: dict = {}
        if self._manifest_path.exists():
            self._manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))

    @staticmethod
    def _load_oc() -> Optional[str]:
        import os

        oc = os.environ.get("LAW_OC")
        if oc:
            return oc.strip()
        # lazy dotenv (kept out of the hermetic path)
        env_path = _REPO_ROOT / ".env"
        if not env_path.exists():
            return None
        try:  # pragma: no cover - convenience
            from dotenv import dotenv_values  # type: ignore

            return (dotenv_values(env_path) or {}).get("LAW_OC", "").strip() or None
        except Exception:  # noqa: BLE001 - stdlib fallback parser
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("LAW_OC="):
                    return line.split("=", 1)[1].strip().strip('"').strip() or None
        return None

    def _http_get(self, url: str) -> bytes:
        try:  # pragma: no cover - network
            import requests  # type: ignore

            resp = requests.get(url, timeout=self._timeout)
            resp.raise_for_status()
            return resp.content
        except ImportError:  # pragma: no cover - stdlib fallback
            import urllib.request

            with urllib.request.urlopen(url, timeout=self._timeout) as r:  # noqa: S310
                return r.read()

    def resolve(self, req: DrfRequest) -> RawResponse:  # pragma: no cover - live
        from urllib.parse import urlencode

        params = {**req.params, "OC": self._oc, "type": "XML"}
        url = f"{_DRF_BASE}/{req.endpoint}.do?{urlencode(params)}"
        content = self._http_get(url)
        # SECRET REDACTION: DRF search responses echo the OC inside 법령상세링크
        # URLs. Strip the key BEFORE hashing/writing so no secret enters a
        # committed fixture (PROMPT.md 비밀키 금지). The redacted bytes ARE the
        # snapshot; content_hash pins them, so replay stays reproducible.
        content = content.replace(self._oc.encode("utf-8"), b"***")
        digest = _sha256(content)
        fname = req.filename
        (self._dir / fname).write_bytes(content)
        self._manifest[req.key] = {
            "file": fname,
            "content_hash": digest,
            "params": req.params,
            "url_redacted": req.url_redacted(),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "bytes": len(content),
        }
        self._manifest_path.write_text(
            json.dumps(self._manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return RawResponse(content, digest, req.url_redacted(), origin="live")


# --------------------------------------------------------------------------- #
# Lookup result
# --------------------------------------------------------------------------- #
@dataclass
class ProvisionLookupResult:
    provision_version: ProvisionVersion
    snapshot: SourceSnapshot
    law_id: str
    law_name: str
    article_label: str
    article_title: str
    as_of_date: date
    search_found: bool
    backend: str
    fallback_chain: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Abstraction (API-002)
# --------------------------------------------------------------------------- #
@runtime_checkable
class LawDataSource(Protocol):
    """getProvision(법령, 조문, asOfDate) → version-pinned ProvisionVersion.

    Implementations are interchangeable behind this interface (docs/07 §3): the
    upper layers never know whether the answer came from MCP or 법제처."""

    name: str

    def lookup_provision(
        self, law_name: str, article_label: str, as_of_date: date
    ) -> ProvisionLookupResult: ...


# --------------------------------------------------------------------------- #
# XML parsing helpers (법제처 DRF schema)
# --------------------------------------------------------------------------- #
_ARTICLE_RE = re.compile(r"제\s*(\d+)\s*조(?:의\s*(\d+))?")


def _parse_article_label(label: str) -> tuple[str, Optional[str]]:
    """'제25조' → ('25', None); '제24조의2' → ('24', '2')."""
    m = _ARTICLE_RE.search(label)
    if not m:
        raise ValueError(f"unparseable article label: {label!r}")
    return m.group(1), m.group(2)


def _text(elem: Optional[ET.Element]) -> str:
    return (elem.text or "").strip() if elem is not None else ""


def _yyyymmdd_to_date(s: str) -> Optional[date]:
    s = (s or "").strip()
    if len(s) != 8 or not s.isdigit():
        return None
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _unit_article_text(unit: ET.Element) -> str:
    """Flatten a 조문단위 to readable pinpoint-preserving text (조문내용 + 항/호/목)."""
    parts: list[str] = []
    content = _text(unit.find("조문내용"))
    if content:
        parts.append(content)
    for hang in unit.findall("항"):
        ht = _text(hang.find("항내용"))
        if ht:
            parts.append(ht)
        for ho in hang.findall("호"):
            parts.append(_text(ho.find("호내용")))
            for mok in ho.findall("목"):
                parts.append(_text(mok.find("목내용")))
    return "\n".join(p for p in parts if p)


# --------------------------------------------------------------------------- #
# PRIMARY working backend — 법제처 국가법령정보 OpenAPI (DRF)
# --------------------------------------------------------------------------- #
class MOLEGLawDataSource:
    """법제처 DRF backend (API-002 fallback / working primary).

    Flow: ① lawSearch(target=law, query=법령명) → confirm law exists + 법령ID
          (search-recall signal) → ② lawService(target=eflaw, LM, efYd=as_of)
          → as-of 시행일 version body → ③ parse the requested 조문단위 →
          ProvisionVersion + SourceSnapshot(content_hash). Deterministic on a
          ReplayTransport (no network)."""

    name = "법제처(MOLEG) DRF"

    def __init__(self, transport: Optional[object] = None) -> None:
        self._transport = transport or ReplayTransport()

    # -- public ----------------------------------------------------------- #
    def lookup_provision(
        self, law_name: str, article_label: str, as_of_date: date
    ) -> ProvisionLookupResult:
        search_found, law_id = self._search(law_name)
        body = self._fetch_efbody(law_name, as_of_date)
        root = ET.fromstring(body.content)
        basic = root.find("기본정보")
        if basic is None:
            raise ProvisionNotFound(f"no 기본정보 in body for {law_name} efYd={as_of_date}")
        resolved_law_id = _text(basic.find("법령ID")) or law_id
        effective_from = _yyyymmdd_to_date(_text(basic.find("시행일자")))
        promulgated = _yyyymmdd_to_date(_text(basic.find("공포일자")))
        promulg_no = _text(basic.find("공포번호"))
        resolved_name = _text(basic.find("법령명_한글")) or law_name

        unit = self._find_article(root, article_label)
        title = _text(unit.find("조문제목"))
        text = _unit_article_text(unit) or _text(unit.find("조문내용"))
        if not text:
            raise ProvisionNotFound(f"empty article text for {law_name} {article_label}")
        if effective_from is None:
            # fail-closed: a version with no 시행일 cannot be pinned (PROV-016)
            raise ProvisionNotFound(
                f"{law_name} {article_label}: missing 시행일자 — cannot pin version"
            )

        ef_str = effective_from.strftime("%Y%m%d")
        snapshot = SourceSnapshot(
            snapshot_id=f"snap_{resolved_name}_{article_label}_{ef_str}",
            url=body.url_redacted,
            canonical_title=f"{resolved_name} {article_label} ({title})",
            publisher=PUBLISHER,
            published_date=promulgated,
            effective_date=effective_from,
            extraction_method="API_XML",
            content_hash=body.content_hash,
            official=True,
        )
        provision_version = ProvisionVersion(
            provision_version_id=f"pv_{resolved_name}_{article_label}_{ef_str}",
            provision_id=f"{resolved_law_id}_{article_label}",
            text=text,
            promulgated_date=promulgated,
            effective_from=effective_from,
            effective_to=None,  # eflaw returns the version in force AT as_of (window open end)
            amended_by=(f"공포번호 제{promulg_no}호" if promulg_no else None),
            snapshot_id=snapshot.snapshot_id,
            hash=_sha256(text.encode("utf-8")),
        )
        return ProvisionLookupResult(
            provision_version=provision_version,
            snapshot=snapshot,
            law_id=resolved_law_id,
            law_name=resolved_name,
            article_label=article_label,
            article_title=title,
            as_of_date=as_of_date,
            search_found=search_found,
            backend=self.name,
        )

    # -- internals -------------------------------------------------------- #
    def _search(self, law_name: str) -> tuple[bool, str]:
        """target=law name search → (found?, 법령ID). A miss is not fatal here
        (the efbody call still pins the version); it only lowers search-recall."""
        req = DrfRequest("lawSearch", {"target": "law", "query": law_name})
        try:
            raw = self._transport.resolve(req)
        except LawSourceUnavailable:
            return False, ""
        root = ET.fromstring(raw.content)
        for law in root.findall("law"):
            if _text(law.find("법령명한글")) == law_name:
                return True, _text(law.find("법령ID"))
        return False, ""

    def _fetch_efbody(self, law_name: str, as_of_date: date) -> RawResponse:
        ef = as_of_date.strftime("%Y%m%d")
        req = DrfRequest("lawService", {"target": "eflaw", "LM": law_name, "efYd": ef})
        return self._transport.resolve(req)

    def _find_article(self, root: ET.Element, article_label: str) -> ET.Element:
        want_no, want_branch = _parse_article_label(article_label)
        for unit in root.iter("조문단위"):
            no = _text(unit.find("조문번호"))
            branch = _text(unit.find("조문가지번호")) or None
            if no == want_no and (want_branch is None or branch == want_branch):
                return unit
        raise ProvisionNotFound(f"article {article_label} not found in body")


# --------------------------------------------------------------------------- #
# By-design primary channel — korean-law-mcp (UNWIRED interface, TODO)
# --------------------------------------------------------------------------- #
class KoreanLawMCPSource:
    """# TODO(API-002): wire korean-law-mcp as the by-design primary channel ①.
    Ships UNWIRED so `lookup_provision` raises ``LawSourceUnavailable`` and the
    FallbackLawDataSource degrades to 법제처 (API-003)."""

    name = "korean-law-mcp"

    def __init__(self, endpoint: Optional[str] = None) -> None:
        self.endpoint = endpoint

    def lookup_provision(
        self, law_name: str, article_label: str, as_of_date: date
    ) -> ProvisionLookupResult:
        raise LawSourceUnavailable(
            "korean-law-mcp backend not wired (slice ① TODO) — falling back to 법제처"
        )


# --------------------------------------------------------------------------- #
# Fallback chain (API-003): MCP → 법제처. Circuit-degrade, recorded.
# --------------------------------------------------------------------------- #
class FallbackLawDataSource:
    """Tries each source in order; on LawSourceUnavailable degrades to the next
    (API-003/API-007). Records which backend answered + the attempted chain so a
    fallback is auditable (docs/07 §4)."""

    name = "LawDataSource(fallback)"

    def __init__(self, sources: list) -> None:
        if not sources:
            raise ValueError("FallbackLawDataSource needs at least one source")
        self._sources = sources

    def lookup_provision(
        self, law_name: str, article_label: str, as_of_date: date
    ) -> ProvisionLookupResult:
        chain: list[str] = []
        last: Optional[LawSourceError] = None
        for src in self._sources:
            chain.append(src.name)
            try:
                result = src.lookup_provision(law_name, article_label, as_of_date)
                result.fallback_chain = chain
                return result
            except LawSourceUnavailable as exc:
                last = exc
                continue
        raise LawSourceUnavailable(
            f"all law sources exhausted {chain}: {last}"
        )


def default_law_source(fixtures_dir: Path = DEFAULT_FIXTURES_DIR) -> FallbackLawDataSource:
    """Production-shaped chain [MCP(unwired) → 법제처(replay)]. The 법제처 backend
    answers from recorded fixtures (hermetic)."""
    return FallbackLawDataSource(
        [KoreanLawMCPSource(), MOLEGLawDataSource(transport=ReplayTransport(fixtures_dir))]
    )
