// 백엔드 산출 fixture(JSON) 스키마 — src/draft.py · src/draft_demo.py 와 정합.

export interface IntakeTurn {
  role: "bot" | "user";
  text: string;
  status: string; // 수집 | 없음 | 모름 | ""
}

export interface InputMaterial {
  name: string;
  status: string; // 수집 | 없음 | 모름 | 결손
  confidentiality: string;
}

export interface Intake {
  goal: string;
  company: string;
  early_stopped: boolean;
  turns: IntakeTurn[];
  checklist: InputMaterial[];
  closing_scope: string;
  deficits: string[];
  limits: string[];
}

export interface StrategyOption {
  option_key: string; // 보수 | 중립 | 적극
  label: string;
  expected_tax_burden: string;
  tax_risk: string;
  defensibility: string;
  required_evidence: string;
  cpa_review_point: string;
  citation_ids: string[];
}

export interface CitationView {
  citation_id: string;
  label: string;
  source_kind: string;
  locator: string;
  quote: string;
  as_of: string;
  basis_kind: string;
  authority_rank: number | null;
  href: string;
}

export interface Risk {
  title: string;
  description: string;
  severity: string;
  citation_ids: string[];
}

export interface Opportunity {
  title: string;
  description: string;
  citation_ids: string[];
}

export interface IssueMemo {
  topic: string;
  analysis: string;
  citation_ids: string[];
  escalation: string;
}

export interface ReviewItem {
  item_id: string;
  category: string;
  description: string;
  gate: string | null;
  severity: string;
  requires_warning: boolean;
}

// OUT-007(변경②): 종합 전 채널별 독립 결과(①법령MCP·②내부RAG·③웹).
export interface ChannelResult {
  channel: string; // ① ② ③
  source_label: string;
  status: string; // ANSWERED | SILENT | ERROR | BLOCKED
  answered: boolean;
  answer_excerpt: string;
  citation_locators: string[];
}

// OUT-008/HALU-015(변경③): 추론 트레이스 + 법령 추적(§10 Mermaid 도식 자료원).
export interface ReasoningStep {
  seq: number;
  stage: string; // INTAKE | ISSUE_SPOTTING | RESEARCH_CH1_LAW | ... | SYNTHESIS | STRATEGY | DRAFT
  decision: string;
  citation_locators: string[];
  refs: Record<string, string>;
}

export interface LawTraceEntry {
  issue: string;
  law_name: string;
  article: string;
  as_of: string;
  basis_kind: string;
  locator: string;
  quote_excerpt: string;
}

export interface ReasoningTrace {
  steps: ReasoningStep[];
  law_trace: LawTraceEntry[];
}

export interface Draft {
  matter_id: string;
  client_id: string;
  company_name: string;
  fiscal_year: string;
  as_of_date: string;
  review_scope: string;
  high_risk: boolean;
  data_limits: string[];
  sections: string[];
  executive_summary: string;
  input_materials: InputMaterial[];
  risks: Risk[];
  opportunities: Opportunity[];
  strategy_options: StrategyOption[];
  issue_memos: IssueMemo[];
  citations: CitationView[];
  additional_requests: string[];
  review_items: ReviewItem[];
  conclusion: string;
  recommended_order: string[];
  synthesis_opinion: string;
  channel_results: ChannelResult[]; // OUT-007(변경②) §8
  reasoning_trace: ReasoningTrace | null; // OUT-008(변경③) §10
}

export interface Fixture {
  intake: Intake;
  draft: Draft;
}
