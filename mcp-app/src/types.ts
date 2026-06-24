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
  conformance?: Conformance | null
  provenance_resource?: Record<string, unknown>
  write_result?: { resource_ref?: string; provenance_ref?: string } | null
}

export interface ConformanceIssue {
  severity: string
  path: string
  message: string
}

export interface Conformance {
  valid: boolean
  level: string
  issues: ConformanceIssue[]
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

export interface UserRecognition {
  user_key: string
  display_name: string | null
  is_returning: boolean
  seen_count: number
  first_seen_at: string
  last_seen_at: string
  config: Record<string, unknown>
}

export interface PatientHeader {
  patient_id: string
  patient_name: string | null
  birth_date: string | null
  sex?: string | null
  mrn?: string | null
  user?: UserRecognition | null
  byok_enabled?: boolean
}

// A secret field is never sent in plaintext; the server redacts it to presence.
export interface RedactedSecret {
  set: boolean
  last4: string | null
}

export interface UserConfig {
  byok?: {
    gemini_api_key?: RedactedSecret | null
    umls_api_key?: RedactedSecret | null
  } | null
  active_preset_id?: string
  presets?: Preset[]
  [k: string]: unknown
}

export type Code = { system: string; code: string; display?: string }

// A Preset stores SPARSE overrides over the resolved IG; absent keys fall back
// to the IG defaults (see lib/ig-catalog.ts) at resolve time.
export interface Preset {
  id: string
  name: string
  ig: { base: string; specialty: string | null }
  resources: Record<string, { enabled: boolean }>
  coding: Record<string, CodingOverride>
  prompts: Record<string, PromptOverride>          // extract lane (parse)
  capture_prompts?: Record<string, PromptOverride> // capture lane (scan routing)
  extensions: UserExtension[]
}

export interface CodingOverride {
  systems?: string[]
  subset?: Code[] | null
  query_rules?: QueryRule[]
}

export interface QueryRule {
  from: string
  to: string
}

export interface PromptVersion {
  version: number
  text: string
  note?: string
  test_notes_ref?: string | null
}

export interface PromptOverride {
  active_version: number
  versions: PromptVersion[]
}

export type ExtensionDatatype =
  | "code" | "string" | "CodeableConcept" | "Quantity" | "boolean" | "integer" | "dateTime"

export interface UserExtension {
  id: string
  name: string
  attach_to: string
  url: string
  datatype: ExtensionDatatype
  binding?: { codes?: Code[] } | null
  prompt_fragment: { text: string; version: number }
}

export interface IgResourceDefault {
  inclusion: "required" | "supported" | "optional"
  profiles: string[]
  coding: { systems: string[]; valueSets?: string[] }
  defaultEnabled: boolean
}

export interface IgDef {
  id: string
  title: string
  dependsOn?: string[]
  resources: Record<string, IgResourceDefault>
  // Coding systems this IG needs that the pipeline has no retriever for yet
  // (e.g. mCODE's ICD-O-3, AJCC). Surfaced in the IG section, never silently dropped.
  gaps?: string[]
}

export interface IgCatalog {
  base: IgDef[]
  specialties: IgDef[]
}

export interface UsageSummary {
  runs: number
  total_cost_usd: number
  input_tokens: number
  output_tokens: number
}

export interface UsageRunRow {
  id: string
  ts: string
  model: string | null
  input_tokens: number
  output_tokens: number
  cost_usd: number
  duration_ms: number | null
  doc_count: number
  status: string
}

export interface UsageData {
  summary: UsageSummary
  runs: UsageRunRow[]
}

export interface PresetMeta {
  id: string
  name: string
}

export interface StageProgress {
  stage: string
  index: number
  total: number
}
