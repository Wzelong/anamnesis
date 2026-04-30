export interface Run {
  id: string
  patient_id: string | null
  patient_name: string | null
  status: "empty" | "pending" | "in_review" | "resolved"
  total_proposals: number
  pending_proposals: number
  started_at: string | null
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
  chart_matches: ChartMatch[]
  supersedes: string[]
  conflicts_with: string[]
  reviewed_at: string | null
  reviewed_by: string | null
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
}
