"""src/chunking.py — structure-aware splitting (RAG-002/015/017, docs/05 §5-§6).

법령은 하나의 splitter로 자르면 조문 경계가 깨진다(docs/05 §1). 그래서 법령 본문을
**조 > 항 > 호 > 목** 단위로 분할하고, 각 chunk에 인용·시점·격리 메타를 박는다:

  * ``source_locator``  — 조/항/호/목 pinpoint (RAG-017 구조 필드, "법령에 따라" 수준 X)
  * ``effective_from/to`` · ``promulgated_date`` — 시점 유효성 필터의 근거 (RAG-005)
  * ``doc_type`` · ``tax_type`` — 메타 필터
  * ``client_id`` · ``confidentiality_level`` — 격리 라우팅 (SEC-003)
  * ``content_hash`` — 재현성

PARENT-CHILD (docs/05 §5): the 조문 PARENT carries the full 조문 본문 (the unit used
to GROUND the answer); the 항/호/목 CHILDREN are smaller citation-level units with
their own locators. Retrieval can hit a child and EXPAND to its parent.

REUSE/BYTE-IDENTITY: the parent's text + 시행일/공포일 come from the TESTED
``MOLEGLawDataSource.lookup_provision`` path (the same 법제처 fixture + parsing slice①
uses), so the parent 조문 text is byte-identical to what the slice① generator/judge
see — the citation-grounded answer reuses that exact provision (no drift).
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

from contract.base import ConfidentialityLevel
from contract.cluster_c_documents import Chunk
from src.ai.law_data_source import (
    DEFAULT_FIXTURES_DIR,
    DrfRequest,
    MOLEGLawDataSource,
    ProvisionLookupResult,
    ReplayTransport,
)

_OPEN_EF = 99991231   # sentinel "currently in force" / non-temporal (client memo)
_ARTICLE_RE = re.compile(r"제\s*(\d+)\s*조(?:의\s*(\d+))?")


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _text(elem: Optional[ET.Element]) -> str:
    return (elem.text or "").strip() if elem is not None else ""


def _parse_article_no(label: str) -> tuple[str, Optional[str]]:
    m = _ARTICLE_RE.search(label)
    if not m:
        raise ValueError(f"unparseable article label: {label!r}")
    return m.group(1), m.group(2)


def _ef_int(d: Optional[date], default: int = 0) -> int:
    return int(d.strftime("%Y%m%d")) if d else default


# --------------------------------------------------------------------------- #
# Chunk value object
# --------------------------------------------------------------------------- #
@dataclass
class RagChunk:
    """A retrievable, citation-bearing unit with isolation + temporal metadata."""

    chunk_id: str
    text: str
    doc_type: str                                  # 법령 | 메모 | 재무 | 계약 ...
    confidentiality_level: ConfidentialityLevel
    client_id: Optional[str]
    source_locator: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None            # exclusive; set by index when versions overlap
    promulgated_date: Optional[date] = None
    tax_type: Optional[str] = None
    content_hash: str = ""
    parent_id: Optional[str] = None                # None = parent / standalone
    # law-chunk linkage (None for client chunks)
    law_name: Optional[str] = None
    article_label: Optional[str] = None
    article_title: Optional[str] = None
    provision_version_id: Optional[str] = None
    lookup: Optional[ProvisionLookupResult] = None  # parent law chunk only (for grounding)

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = _sha256(self.text)

    @property
    def is_law(self) -> bool:
        return self.doc_type == "법령"

    @property
    def is_parent(self) -> bool:
        return self.parent_id is None

    def ef_from_int(self) -> int:
        return _ef_int(self.effective_from, default=0)

    def ef_to_int(self) -> int:
        return _ef_int(self.effective_to, default=_OPEN_EF)

    def valid_at(self, as_of: date) -> bool:
        """RAG-005 시점 유효성: effective_from ≤ as_of < effective_to."""
        a = int(as_of.strftime("%Y%m%d"))
        return self.ef_from_int() <= a < self.ef_to_int()

    def to_contract_chunk(self, document_version_id: str = "dv1") -> Chunk:
        """Validate against the contract (RAG-002/017 + SEC-001/003 at construction)."""
        return Chunk(
            chunk_id=self.chunk_id,
            document_version_id=document_version_id,
            chunk_text=self.text,
            chunk_type=self.doc_type,
            source_locator=self.source_locator,
            effective_from=self.effective_from,
            effective_to=self.effective_to,
            tax_type=self.tax_type,
            confidentiality_level=self.confidentiality_level,
            client_id=self.client_id,
            content_hash=self.content_hash,
        )


@dataclass
class LawChunkSet:
    """One 조문's parent + 항/호/목 children + the version-pinned lookup."""

    parent: RagChunk
    children: list[RagChunk] = field(default_factory=list)

    @property
    def all_chunks(self) -> list[RagChunk]:
        return [self.parent, *self.children]


# --------------------------------------------------------------------------- #
# Law (법령) structure-aware chunker — 조 > 항 > 호 > 목
# --------------------------------------------------------------------------- #
def chunk_provision(
    law_name: str,
    article_label: str,
    effective_year: int,
    *,
    doc_id: Optional[str] = None,
    tax_type: Optional[str] = None,
    transport: Optional[object] = None,
    fixtures_dir: Path = DEFAULT_FIXTURES_DIR,
) -> LawChunkSet:
    """Chunk one 조문 (as-of ``effective_year``) into a parent + 항/호/목 children.

    The PARENT text/dates come from the tested ``MOLEGLawDataSource`` path; the
    children are re-parsed from the SAME 시행일 본문 XML (structure preserved)."""
    transport = transport or ReplayTransport(fixtures_dir)
    as_of = date(effective_year, 1, 1)
    moleg = MOLEGLawDataSource(transport=transport)
    lookup = moleg.lookup_provision(law_name, article_label, as_of)
    pv = lookup.provision_version
    cid = doc_id or f"law_{law_name}_{article_label}_{pv.effective_from:%Y%m%d}"

    parent = RagChunk(
        chunk_id=cid,
        text=pv.text,
        doc_type="법령",
        confidentiality_level=ConfidentialityLevel.L0_PUBLIC,
        client_id=None,
        source_locator=f"{lookup.law_name} {article_label}",
        effective_from=pv.effective_from,
        effective_to=pv.effective_to,           # may be tightened by the index builder
        promulgated_date=pv.promulgated_date,
        tax_type=tax_type,
        content_hash=pv.hash or _sha256(pv.text),
        law_name=lookup.law_name,
        article_label=article_label,
        article_title=lookup.article_title,
        provision_version_id=pv.provision_version_id,
        lookup=lookup,
    )

    children = _split_article_units(
        transport, law_name, as_of, article_label, parent
    )
    return LawChunkSet(parent=parent, children=children)


def _split_article_units(
    transport: object, law_name: str, as_of: date, article_label: str, parent: RagChunk
) -> list[RagChunk]:
    """Re-parse the 시행일 본문 XML and emit a child chunk per 항(그리고 호/목 묶음)."""
    ef = as_of.strftime("%Y%m%d")
    req = DrfRequest("lawService", {"target": "eflaw", "LM": law_name, "efYd": ef})
    raw = transport.resolve(req)
    root = ET.fromstring(raw.content)
    want_no, want_branch = _parse_article_no(article_label)
    unit = None
    for u in root.iter("조문단위"):
        no = _text(u.find("조문번호"))
        branch = _text(u.find("조문가지번호")) or None
        if no == want_no and (want_branch is None or branch == want_branch):
            unit = u
            break
    if unit is None:
        return []

    children: list[RagChunk] = []
    base_locator = parent.source_locator or f"{law_name} {article_label}"

    def _child(suffix_locator: str, text: str, idx: str) -> RagChunk:
        return RagChunk(
            chunk_id=f"{parent.chunk_id}#{idx}",
            text=text,
            doc_type="법령",
            confidentiality_level=ConfidentialityLevel.L0_PUBLIC,
            client_id=None,
            source_locator=suffix_locator,
            effective_from=parent.effective_from,
            effective_to=parent.effective_to,
            promulgated_date=parent.promulgated_date,
            tax_type=parent.tax_type,
            parent_id=parent.chunk_id,
            law_name=parent.law_name,
            article_label=parent.article_label,
            article_title=parent.article_title,
            provision_version_id=parent.provision_version_id,
        )

    hangs = unit.findall("항")
    if not hangs:
        # 항이 없는 단문 조문 → 조문 자체가 자연 경계(작은 조문은 병합) — child 없음.
        return []
    for hi, hang in enumerate(hangs, start=1):
        parts: list[str] = []
        ht = _text(hang.find("항내용"))
        if ht:
            parts.append(ht)
        ho_locators: list[str] = []
        for ho in hang.findall("호"):
            hot = _text(ho.find("호내용"))
            if hot:
                parts.append(hot)
            for mok in ho.findall("목"):
                mt = _text(mok.find("목내용"))
                if mt:
                    parts.append(mt)
            ho_locators.append(_text(ho.find("호번호")))
        body = "\n".join(p for p in parts if p).strip()
        if not body:
            continue
        locator = f"{base_locator} 제{hi}항"
        if any(ho_locators):
            locator += " (호·목 포함)"
        children.append(_child(locator, body, f"항{hi}"))
    return children


# --------------------------------------------------------------------------- #
# Client (고객자료) chunker — short memos are a single chunk (docs/05 §5)
# --------------------------------------------------------------------------- #
def chunk_client_doc(
    *,
    doc_id: str,
    text: str,
    client_id: Optional[str],
    confidentiality_level: ConfidentialityLevel,
    doc_type: str = "메모",
    tax_type: Optional[str] = None,
) -> RagChunk:
    """A client memo/financial unit. Routing/isolation is enforced downstream by
    ``src.isolation.classify_target_scope`` (this only carries the metadata)."""
    return RagChunk(
        chunk_id=doc_id,
        text=text,
        doc_type=doc_type,
        confidentiality_level=confidentiality_level,
        client_id=client_id,
        source_locator=None,
        effective_from=None,            # non-temporal → always valid (ef_to sentinel)
        effective_to=None,
        tax_type=tax_type,
        content_hash=_sha256(text),
    )
