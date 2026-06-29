"""3대 불변식(docs/04 §0) + 핵심 구조 제약을 런타임으로 강제하는지 검증."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from contract.base import ApplicableBasis, BasisKind, ConfidentialityLevel, IndexScope, SourceKind
from contract.cluster_a_tenancy import Client, Engagement, Matter, RoleAssignment
from contract.cluster_c_documents import Chunk, Document, VectorIndex
from contract.cluster_e_analysis import FactPattern
from contract.cluster_f_qa import AnswerRun, Citation, RetrievedEvidence
from contract.cluster_h_review import FinalMemo


# --- 불변식 ① 격리키 전파 (SEC-001) -------------------------------------- #
def test_client_scoped_chunk_requires_client_id():
    with pytest.raises(ValidationError):
        Chunk(
            chunk_id="c1",
            document_version_id="dv1",
            chunk_text="고객 원장",
            chunk_type="재무",
            confidentiality_level=ConfidentialityLevel.L3_CLIENT,
            client_id=None,  # NULL 격리키 → 거부
        )


def test_shared_chunk_must_not_carry_client_id():
    with pytest.raises(ValidationError):
        Chunk(
            chunk_id="c2",
            document_version_id="dv1",
            chunk_text="법령 원문",
            chunk_type="법령",
            confidentiality_level=ConfidentialityLevel.L0_PUBLIC,
            client_id="client_A",  # 공유지식에 테넌트 키 금지
        )


def test_client_scoped_model_rejects_blank_key():
    with pytest.raises(ValidationError):
        AnswerRun(answer_run_id="ar1", question_id="q1", client_id="   ")


def test_client_document_requires_key():
    with pytest.raises(ValidationError):
        Document(
            document_id="d1",
            title="원장",
            confidentiality_level=ConfidentialityLevel.L4_RESTRICTED,
            client_id=None,
        )


def test_role_assignment_scopes_with_key():
    ra = RoleAssignment(
        assignment_id="a1",
        user_id="u1",
        role_id="r1",
        scope_type="MATTER",
        scope_id="m1",
        client_id="client_A",
    )
    assert ra.client_id == "client_A"


# --- P1-2 공백/whitespace-only 격리키·스코프키 거부 ---------------------- #
def test_client_rejects_blank_client_id():
    with pytest.raises(ValidationError):
        Client(client_id="   ", tenant_id="t1", name="X")  # whitespace-only 격리키


def test_engagement_rejects_blank_client_id():
    with pytest.raises(ValidationError):
        Engagement(engagement_id="e1", client_id=" ", name="X")


def test_matter_rejects_blank_matter_id():
    with pytest.raises(ValidationError):
        Matter(matter_id="   ", engagement_id="e1", client_id="client_A", title="t")


def test_role_assignment_rejects_blank_scope_id():
    with pytest.raises(ValidationError):
        RoleAssignment(
            assignment_id="a1",
            user_id="u1",
            role_id="r1",
            scope_type="MATTER",
            scope_id="   ",  # whitespace-only 스코프키
            client_id="client_A",
        )


# --- P1-3 FactPattern 격리키 전파 (client-scoped) ----------------------- #
def test_factpattern_requires_client_id():
    with pytest.raises(ValidationError):
        FactPattern(fact_pattern_id="fp1", description="고객 사실관계")  # client_id 누락


def test_factpattern_rejects_blank_client_id():
    with pytest.raises(ValidationError):
        FactPattern(fact_pattern_id="fp1", description="사실관계", client_id="   ")


def test_factpattern_accepts_client_id():
    fp = FactPattern(fact_pattern_id="fp1", description="사실관계", client_id="client_A")
    assert fp.client_id == "client_A"


# --- 불변식 ② 인용=버전객체 (HALU-003) ----------------------------------- #
def _basis() -> ApplicableBasis:
    return ApplicableBasis(basis_kind=BasisKind.FISCAL_YEAR, as_of_date=date(2024, 1, 1))


def test_citation_points_at_version_object():
    cit = Citation(
        citation_id="cit1",
        source_answer_id="sa1",
        source_kind=SourceKind.PROVISION_VERSION,
        source_object_id="pv_법인세법_25_2024",
        applicable_basis=_basis(),
    )
    assert cit.source_object_id.startswith("pv_")


def test_citation_rejects_raw_url():
    with pytest.raises(ValidationError):
        Citation(
            citation_id="cit2",
            source_answer_id="sa1",
            source_kind=SourceKind.SOURCE_SNAPSHOT,
            source_object_id="https://law.go.kr/제25조",  # raw URL 금지
            applicable_basis=_basis(),
        )


def test_citation_rejects_empty_source_object():
    with pytest.raises(ValidationError):
        Citation(
            citation_id="cit3",
            source_answer_id="sa1",
            source_kind=SourceKind.RULING,
            source_object_id="",
            applicable_basis=_basis(),
        )


# --- 불변식 ③ 시점 유효성 (PROV-012) ------------------------------------- #
def test_citation_requires_applicable_basis():
    with pytest.raises(ValidationError):
        Citation(
            citation_id="cit4",
            source_answer_id="sa1",
            source_kind=SourceKind.PROVISION_VERSION,
            source_object_id="pv1",
            # applicable_basis 누락 → 시점 없는 인용 거부
        )


# --- 구조 제약 ----------------------------------------------------------- #
def test_vector_index_tenant_requires_client_id():
    with pytest.raises(ValidationError):
        VectorIndex(index_id="ix1", scope=IndexScope.TENANT, embedding_model="m", client_id=None)


def test_vector_index_shared_forbids_client_id():
    with pytest.raises(ValidationError):
        VectorIndex(
            index_id="ix2", scope=IndexScope.SHARED, embedding_model="m", client_id="client_A"
        )


def test_retrieved_evidence_exactly_one_source():
    with pytest.raises(ValidationError):
        RetrievedEvidence(evidence_id="e1", chunk_id="c1", snapshot_id="s1")  # 두 출처 → 거부
    ok = RetrievedEvidence(evidence_id="e2", chunk_id="c1")
    assert ok.chunk_id == "c1"


def test_finalmemo_requires_approval():
    with pytest.raises(ValidationError):
        FinalMemo(
            final_memo_id="fm1",
            draft_id="d1",
            decision_id="dec1",
            approved=False,  # HITL 미승인 → FinalMemo 금지
            client_id="client_A",
        )
