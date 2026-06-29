"""Cluster A — 테넌시 · 신원 (docs/04 §1-A, §2).

Tenant ⊃ Client ⊃ Engagement ⊃ Matter. Access is evaluated via RoleAssignment
(User × Role × scope), NOT via a global Role node (SEC-012).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field, model_validator

from .base import NonBlankStr, ScopeType, TIWModel, utc_now
from datetime import datetime


class Tenant(TIWModel):
    """Deployment unit = 법인/펌 (top of the isolation hierarchy)."""

    tenant_id: str
    name: str
    deployment_policy: Optional[str] = None  # SaaS|private_endpoint|on_prem|region (SEC-014)


class Client(TIWModel):
    """자문 고객사(납세자) — the top isolation OWNER (docs/04 §2)."""

    client_id: NonBlankStr  # whitespace-only 격리키 거부 (SEC-001)
    tenant_id: str
    name: str


class Engagement(TIWModel):
    engagement_id: str
    client_id: NonBlankStr  # whitespace-only 격리키 거부 (SEC-001)
    name: str


class Matter(TIWModel):
    matter_id: NonBlankStr  # whitespace-only 스코프키 거부
    engagement_id: str
    client_id: NonBlankStr  # whitespace-only 격리키 거부 (SEC-001)
    title: str


class RoleName(str, Enum):
    CPA = "CPA"
    TAX_LAWYER = "TaxLawyer"
    REVIEWER = "Reviewer"
    MANAGER = "Manager"
    ADMIN = "Admin"
    CLIENT_FACING = "ClientFacing"


class User(TIWModel):
    user_id: str
    tenant_id: str
    display_name: str
    active: bool = True  # SCIM lifecycle; deactivated → access revoked (SEC-013)


class Permission(TIWModel):
    permission_id: str
    action: str  # view|search|generate|export|approve|delete
    description: Optional[str] = None


class Role(TIWModel):
    """A set of permissions. Role is NOT a hierarchy node (docs/01 §4)."""

    role_id: str
    name: RoleName
    permission_ids: list[str] = Field(default_factory=list)


class RoleAssignment(TIWModel):
    """User × Role granted within EXACTLY ONE scope (Matter XOR Engagement).

    # SEC-012 권한은 RoleAssignment로 평가 — 전역 Role만으론 접근 불가
    """

    assignment_id: str
    user_id: str
    role_id: str
    scope_type: ScopeType
    scope_id: NonBlankStr  # whitespace-only 스코프키 거부
    client_id: NonBlankStr  # isolation key propagated (whitespace-only 거부, SEC-001)
    expires_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _exactly_one_scope(self) -> "RoleAssignment":
        # scope_type + scope_id together bind to one scope; enforced by required fields.
        if not self.scope_id:
            raise ValueError("SEC-012: RoleAssignment requires a concrete scope_id")
        return self


class AuditLog(TIWModel):
    """Append-only, tamper-evident (SEC-017). Carries client_id for T1b."""

    log_id: str
    actor: str
    action: str
    target_type: str
    target_id: str
    client_id: Optional[str] = None  # None only for system/shared-resource events
    result: str = "OK"
    ts: datetime = Field(default_factory=utc_now)
