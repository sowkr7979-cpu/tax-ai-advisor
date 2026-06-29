"""Cluster B — 세무 워크스페이스 · 대상 (docs/04 §1-B, §2).

Client-owned tax working set. Every record propagates the isolation key.
"""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from .base import ClientScopedModel, TIWModel


class Jurisdiction(TIWModel):
    jurisdiction_id: str
    tax_type: str            # e.g. 법인세
    authority: str           # 관할 (국세청/지방청)


class TaxWorkspace(ClientScopedModel):
    workspace_id: str
    matter_id: str = Field(..., min_length=1)


class TaxYear(ClientScopedModel):
    tax_year_id: str
    workspace_id: str
    fiscal_year: int          # 귀속연도
    jurisdiction_id: str


class TrialBalance(ClientScopedModel):
    trial_balance_id: str
    workspace_id: str
    tax_year_id: str


class AccountLedger(ClientScopedModel):
    ledger_id: str
    workspace_id: str
    account_code: str


class PriorReturn(ClientScopedModel):
    prior_return_id: str
    workspace_id: str
    tax_year_id: str


class FinancialStatement(ClientScopedModel):
    fs_id: str
    workspace_id: str
    tax_year_id: str
    statement_type: Optional[str] = None  # BS|PL|CF
