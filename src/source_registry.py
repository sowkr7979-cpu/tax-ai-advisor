"""src/source_registry.py — version-object registry + citation verification (P1-1).

# HALU-003 G2 인용검증: 존재(existence) + (source_kind ↔ source_object_id) 정합
# PROV-002 Citation은 객체ID로 해석되어야 한다 (raw URL/자유텍스트 금지 — contract에서 강제)

A ``Citation`` carries ``(source_kind, source_object_id)``. The contract already
forbids a raw URL there, but it does NOT guarantee the id actually RESOLVES to a
registered source object of the matching kind. This registry closes that gap
(codex P1-1): a citation pointing at a non-existent id, or at an id whose real
kind differs from the cited kind, is REJECTED — i.e. fabrication.

This is deterministic and connects to the FABRICATED_CITATION hard gate (cap 60,
docs/09 §2): the slice harness raises that gate when any answer citation fails
verification. Fail-closed: an unverifiable citation is NOT trusted.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from contract.base import SourceKind
from contract.cluster_d_provenance import (
    CasePrecedent,
    ProvisionVersion,
    Ruling,
    SourceSnapshot,
)
from contract.cluster_f_qa import Citation

# Map each citable kind → (object type, id attribute).
_KIND_SPEC: dict[SourceKind, tuple[type, str]] = {
    SourceKind.PROVISION_VERSION: (ProvisionVersion, "provision_version_id"),
    SourceKind.RULING: (Ruling, "ruling_id"),
    SourceKind.CASE_PRECEDENT: (CasePrecedent, "case_id"),
    SourceKind.SOURCE_SNAPSHOT: (SourceSnapshot, "snapshot_id"),
}


class VerificationStatus(str, Enum):
    OK = "OK"
    NOT_FOUND = "NOT_FOUND"          # id does not exist → fabrication
    KIND_MISMATCH = "KIND_MISMATCH"  # id exists but under a different kind → fabrication


class CitationVerificationError(RuntimeError):
    """Raised at a citation-EMITTING boundary when a Citation fails registry
    verification (NOT_FOUND / KIND_MISMATCH).

    Fail-closed (codex P1-B): an unverifiable citation must be REFUSED at the API
    boundary that produces it — not only flagged inside the eval harness — so a
    non-eval consumer can never obtain a citation that bypassed the registry.
    Carries the underlying ``CitationVerification`` for callers that want detail.
    """

    def __init__(self, verification: "CitationVerification") -> None:
        self.verification = verification
        super().__init__(f"{verification.status.value}: {verification.detail}")


@dataclass(frozen=True)
class CitationVerification:
    citation_id: str
    status: VerificationStatus
    detail: str

    @property
    def ok(self) -> bool:
        return self.status is VerificationStatus.OK

    @property
    def is_fabrication(self) -> bool:
        return self.status in (VerificationStatus.NOT_FOUND, VerificationStatus.KIND_MISMATCH)


class SourceRegistry:
    """In-memory registry of version-pinned source objects, keyed by
    (kind, object_id). Citation verification resolves against it."""

    def __init__(self) -> None:
        # (kind, object_id) -> object
        self._store: dict[tuple[SourceKind, str], object] = {}
        # object_id -> kind, to detect kind mismatches (same id, wrong kind)
        self._id_kind: dict[str, SourceKind] = {}

    # -- registration ----------------------------------------------------- #
    def register(self, obj: object) -> tuple[SourceKind, str]:
        for kind, (cls, id_attr) in _KIND_SPEC.items():
            if isinstance(obj, cls):
                object_id = getattr(obj, id_attr)
                self._store[(kind, object_id)] = obj
                self._id_kind[object_id] = kind
                return kind, object_id
        raise TypeError(f"not a citable version source object: {type(obj).__name__}")

    def register_all(self, objects) -> None:
        for obj in objects:
            self.register(obj)

    def get(self, kind: SourceKind, object_id: str) -> Optional[object]:
        return self._store.get((kind, object_id))

    def __contains__(self, key: tuple[SourceKind, str]) -> bool:
        return key in self._store

    def __len__(self) -> int:
        return len(self._store)

    # -- verification (G2) ------------------------------------------------ #
    def verify_citation(self, citation: Citation) -> CitationVerification:
        key = (citation.source_kind, citation.source_object_id)
        if key in self._store:
            return CitationVerification(citation.citation_id, VerificationStatus.OK,
                                        "resolved to registered source object")
        # id exists but under another kind → kind/id inconsistency (fabrication)
        existing_kind = self._id_kind.get(citation.source_object_id)
        if existing_kind is not None and existing_kind != citation.source_kind:
            return CitationVerification(
                citation.citation_id,
                VerificationStatus.KIND_MISMATCH,
                f"id {citation.source_object_id!r} is registered as {existing_kind.value}, "
                f"not {citation.source_kind.value}",
            )
        return CitationVerification(
            citation.citation_id,
            VerificationStatus.NOT_FOUND,
            f"no source object for ({citation.source_kind.value}, {citation.source_object_id!r}) "
            f"— fabricated/unregistered citation",
        )

    def verify_all(self, citations) -> list[CitationVerification]:
        return [self.verify_citation(c) for c in citations]

    def require_citation(self, citation: Citation) -> CitationVerification:
        """Verify a citation and RAISE ``CitationVerificationError`` on fabrication
        (NOT_FOUND / KIND_MISMATCH). Use this at any boundary that emits/returns a
        citation so the registry check cannot be bypassed (codex P1-B)."""
        verification = self.verify_citation(citation)
        if verification.is_fabrication:
            raise CitationVerificationError(verification)
        return verification
