"""Cluster E — 세무 분석 (docs/04 §1-E, §2).

TaxIssue → (RiskItem | StrategyOption) → EvidenceLink. Client-scoped.
"""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from .base import ClientScopedModel


class FactPattern(ClientScopedModel):
    # client-scoped: 고객 사실관계 → 격리키 NOT NULL 전파 (SEC-001)
    fact_pattern_id: str
    description: str


class TaxIssue(ClientScopedModel):
    issue_id: str
    workspace_id: str
    fact_pattern_id: str
    title: str


class RiskItem(ClientScopedModel):
    risk_id: str
    issue_id: str
    description: str
    severity: str = "MEDIUM"        # LOW|MEDIUM|HIGH
    requires_review: bool = False   # HIGH risk → CPA review escalation (HALU-009)


class StrategyOption(ClientScopedModel):
    """선택지 (보수/중립/적극). Compared in the OUT- comparison table."""

    option_id: str
    issue_id: str
    stance: str                     # CONSERVATIVE|NEUTRAL|AGGRESSIVE
    tax_effect: Optional[str] = None
    taxation_logic: Optional[str] = None    # 과세논리
    defense_logic: Optional[str] = None     # 방어논리


class EvidenceLink(ClientScopedModel):
    evidence_link_id: str
    target_kind: str   # RISK_ITEM|STRATEGY_OPTION
    target_id: str
    citation_id: Optional[str] = None
