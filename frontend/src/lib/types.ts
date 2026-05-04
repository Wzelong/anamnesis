export interface Run {
  id: string
  patient_id: string | null
  patient_name: string | null
  status: "empty" | "running" | "pending" | "in_review" | "resolved"
  total_proposals: number
  pending_proposals: number
  pending_by_tier: Partial<Record<"ATTENTION" | "REVIEW" | "CONFIDENT", number>>
  pending_by_classification: Partial<Record<"NEW" | "UPDATING" | "CONFLICTING", number>>
  started_at: string | null
  duration_ms: number | null
  total_tokens: number
  total_cost_usd: number
  total_documents: number
}

export interface Proposal {
  id: string
  run_id: string
  resource_type: string
  classification: "NEW" | "UPDATING" | "CONFLICTING"
  confidence_tier: "CONFIDENT" | "REVIEW" | "ATTENTION"
  confidence_score: number
  status: "pending" | "accepted" | "rejected"
  display_label: string
  flags: string[]
}

export interface ProposalDetail extends Proposal {
  resource: Record<string, unknown>
  citations: ResolvedCitation[]
  classification_reasoning: string
  extraction_reasoning: string
  merge_reasoning: string | null
  confidence_breakdown: ConfidenceBreakdown | null
  chart_matches: ChartMatch[]
  supersedes: string[]
  reviewed_at: string | null
  reviewed_by: string | null
  rejection_reason: string | null
  provenance_resource: Record<string, unknown> | null
  write_result: {
    resource_ref: string | null
    provenance_ref: string | null
    superseded_ref: string | null
  } | null
}

export interface ConfidenceAxis {
  score: number
  weight: number
  contribution: number
  reason: string
}

export interface ConfidenceBreakdown {
  certainty: ConfidenceAxis
  coding: ConfidenceAxis
}

export interface ResolvedCitation {
  document_id: string
  sentence_numbers: number[]
  char_start: number
  char_end: number
  text: string
}

export interface ChartMatch {
  resource_id: string
  display: string
  match_type: "exact_code" | "ingredient" | "display_text"
  resource?: Record<string, unknown> | null
}

export interface SourceDocument {
  id: string
  type: string
  date: string
  author: string
  text: string
  encounter_id: string | null
}

export type ChatRole = "user" | "assistant" | "tool"

export interface ProposedEdit {
  proposalId: string
  resource: Record<string, unknown>
  rationale: string
  status: "pending" | "applied" | "dismissed"
}

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  toolName?: string
  toolArgs?: Record<string, unknown>
  toolStatus?: "pending" | "ok" | "error"
  toolSummary?: string
  toolCallId?: string
  proposedEdit?: ProposedEdit
}

export interface ChartContext {
  patient: Record<string, unknown>
  conditions: Array<Record<string, unknown>>
  medications: Array<Record<string, unknown>>
  allergies: Array<Record<string, unknown>>
  observations: Array<Record<string, unknown>>
  procedures: Array<Record<string, unknown>>
  family_history: Array<Record<string, unknown>>
  encounters: Array<Record<string, unknown>>
  practitioners: Array<Record<string, unknown>>
  organizations: Array<Record<string, unknown>>
  documents: Array<Record<string, unknown>>
  provenances: Array<Record<string, unknown>>
  source: string
  fetched_at: string
  live: boolean
  token_expires_at: string | null
}
