export interface ResolvedCitation {
  document_id: string
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
  encounter_id?: string | null
}

export interface Proposal {
  id: string
  run_id: string
  resource_type: string
  classification: string
  confidence_tier: string
  confidence_score: number
  status: string
  display_label: string
  flags: string[]
  conflict_group_id: string | null
  resource: Record<string, unknown>
  citations: ResolvedCitation[]
  classification_reasoning: string
  extraction_reasoning: string
  merge_reasoning?: string | null
  confidence_breakdown?: ConfidenceBreakdown | null
  chart_matches: ChartMatch[]
  supersedes: string[]
  provenance_resource?: Record<string, unknown>
  write_result?: { resource_ref?: string; provenance_ref?: string } | null
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

export interface RunStats {
  duration_ms: number | null
  total_cost_usd: number
}

export interface ExtractionResult {
  run_id: string
  patient_id: string
  documents: SourceDocument[]
  proposals: Proposal[]
  stats?: RunStats
}

export interface PatientHeader {
  patient_id: string
  patient_name: string | null
  birth_date: string | null
  sex?: string | null
  mrn?: string | null
}

export interface StageProgress {
  stage: string
  index: number
  total: number
}
