"""Cluster D — 법령 출처 · provenance (docs/04 §1-D, §3, §3-1).

These are the version-pinned source objects a Citation may point at (invariant ②).
They are SHARED reference knowledge (no client_id).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import Field

from .base import TIWModel, utc_now


class LegalSource(TIWModel):
    legal_source_id: str
    name: str            # 법인세법 / 시행령 / 시행규칙 / 고시
    authority_rank: int  # 1=법률 … (lower = higher authority); see rules/source_priority.md


class LegalProvision(TIWModel):
    """조문 (e.g. 법인세법 제24조)."""

    provision_id: str
    legal_source_id: str
    article_label: str   # "제24조"


class EffectiveDatePeriod(TIWModel):
    period_id: str
    effective_from: date
    effective_to: Optional[date] = None  # exclusive; None = currently in force


class ProvisionVersion(TIWModel):
    """시행일 버전 — invariant ③ as-of selection target (docs/04 §3-1)."""

    provision_version_id: str
    provision_id: str
    text: str
    promulgated_date: Optional[date] = None
    effective_from: date
    effective_to: Optional[date] = None
    amended_by: Optional[str] = None
    amendment_reason: Optional[str] = None
    snapshot_id: Optional[str] = None
    hash: Optional[str] = None


class TransitionRule(TIWModel):
    rule_id: str
    provision_version_id: str
    applies_when: str
    rule_text: str
    machine_condition: Optional[str] = None


class Ruling(TIWModel):
    """예규 · 질의회신 (interpretive authority, not law-overriding)."""

    ruling_id: str
    provision_id: Optional[str] = None
    document_number: str
    title: str
    issued_date: Optional[date] = None


class CasePrecedent(TIWModel):
    """판례 · 심판례."""

    case_id: str
    provision_id: Optional[str] = None
    case_number: str
    court: Optional[str] = None
    decided_date: Optional[date] = None


class SourceSnapshot(TIWModel):
    """Web/external capture — the ONLY place a raw URL is allowed to live
    (invariant ②: a Citation cites this object, never a bare URL)."""

    snapshot_id: str
    url: str
    canonical_title: str
    publisher: Optional[str] = None
    published_date: Optional[date] = None
    effective_date: Optional[date] = None
    retrieved_at: datetime = Field(default_factory=utc_now)
    extraction_method: str = "HTML"  # HTML|PDF|HWP|OCR
    content_hash: Optional[str] = None
    official: bool = False
