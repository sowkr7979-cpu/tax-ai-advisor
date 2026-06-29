"""contract/ — ERD clusters A~I as pydantic v2 schemas (docs/04).

Enforces the 3 invariants at type/runtime level:
  ① 격리키 전파 (SEC-001)       — contract.base.ClientScopedModel, Chunk/Document validators
  ② 인용=버전객체 (HALU-003)    — contract.cluster_f_qa.Citation (XOR, no raw URL)
  ③ 시점 유효성 (PROV-012)      — contract.base.ApplicableBasis on Citation
"""

from __future__ import annotations

from .base import (  # noqa: F401
    ApplicableBasis,
    AlignmentStatus,
    BasisKind,
    ClientScopedModel,
    ConfidentialityLevel,
    IndexScope,
    ScopeType,
    SourceAnswerStatus,
    SourceKind,
    SourceType,
    TIWModel,
)
from .cluster_a_tenancy import (  # noqa: F401
    AuditLog,
    Client,
    Engagement,
    Matter,
    Permission,
    Role,
    RoleAssignment,
    RoleName,
    Tenant,
    User,
)
from .cluster_b_workspace import (  # noqa: F401
    AccountLedger,
    FinancialStatement,
    Jurisdiction,
    PriorReturn,
    TaxWorkspace,
    TaxYear,
    TrialBalance,
)
from .cluster_c_documents import (  # noqa: F401
    Chunk,
    Document,
    DocumentVersion,
    Embedding,
    EmbeddingModel,
    RetentionPolicy,
    SourceLicense,
    VectorIndex,
)
from .cluster_d_provenance import (  # noqa: F401
    CasePrecedent,
    EffectiveDatePeriod,
    LegalProvision,
    LegalSource,
    ProvisionVersion,
    Ruling,
    SourceSnapshot,
    TransitionRule,
)
from .cluster_e_analysis import (  # noqa: F401
    EvidenceLink,
    FactPattern,
    RiskItem,
    StrategyOption,
    TaxIssue,
)
from .cluster_f_qa import (  # noqa: F401
    AnswerRun,
    Citation,
    Claim,
    ClaimAlignment,
    ConfidenceScore,
    ConflictFlag,
    ConflictResolution,
    EvidenceBundle,
    Question,
    RetrievalRun,
    RetrievedEvidence,
    SourceAnswer,
    SynthesisOpinion,
)
from .cluster_g_agents import (  # noqa: F401
    AgentRun,
    ModelVersion,
    PromptVersion,
    ToolCall,
)
from .cluster_h_review import (  # noqa: F401
    ClientDeliverable,
    Correction,
    DraftPackage,
    FinalMemo,
    GateType,
    ReleaseAuthorization,
    Review,
    ReviewHistory,
    ReviewItem,
    ReviewItemCategory,
    ReviewerDecision,
    TaxMemory,
)
from .cluster_i_eval import (  # noqa: F401
    CorpusDoc,
    EvaluationCase,
    FailureMode,
    GoldQuery,
    RubricResult,
    Score,
    TargetKind,
    Visibility,
)
