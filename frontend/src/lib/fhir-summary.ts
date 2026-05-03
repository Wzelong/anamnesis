export type FhirResource = Record<string, unknown>

export interface SummaryRow {
  label: string
  value: string
}

export function summarize(r: FhirResource): SummaryRow[] {
  const type = r.resourceType as string
  switch (type) {
    case "Condition":
      return summarizeCondition(r)
    case "MedicationRequest":
      return summarizeMedication(r)
    case "AllergyIntolerance":
      return summarizeAllergy(r)
    case "Observation":
      return summarizeObservation(r)
    case "Procedure":
      return summarizeProcedure(r)
    case "FamilyMemberHistory":
      return summarizeFamilyHistory(r)
    default:
      return [{ label: "Resource", value: type || "unknown" }]
  }
}

export function stateLabel(r: FhirResource): string {
  const type = r.resourceType
  if (type === "Condition") {
    const cs = r.clinicalStatus as { coding?: Array<{ code?: string }> } | undefined
    return cs?.coding?.[0]?.code || "active"
  }
  if (type === "AllergyIntolerance") {
    const cs = r.clinicalStatus as { coding?: Array<{ code?: string }> } | undefined
    return cs?.coding?.[0]?.code || codeableDisplay(r.code) || "active"
  }
  if (type === "MedicationRequest" || type === "Observation" || type === "Procedure") {
    return (r.status as string) || ""
  }
  return ""
}

export function codeableDisplay(cc: unknown): string {
  if (!cc || typeof cc !== "object") return ""
  const obj = cc as { text?: string; coding?: Array<{ display?: string; code?: string }> }
  if (obj.text) return obj.text
  const c = obj.coding?.[0]
  return c?.display || c?.code || ""
}

export function referenceDisplay(ref: unknown): string {
  if (!ref || typeof ref !== "object") return ""
  const r = ref as { display?: string; reference?: string }
  return r.display || r.reference || ""
}

export function shortDate(iso: string | undefined | null): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
}

export function doseSummary(r: FhirResource): string {
  const di = (r.dosageInstruction as Array<Record<string, unknown>>) || []
  if (di.length === 0) return ""
  const first = di[0]
  if (first.text) return first.text as string
  const dr = (first.doseAndRate as Array<Record<string, unknown>>)?.[0]
  const q = dr?.doseQuantity as { value?: number; unit?: string } | undefined
  if (q?.value !== undefined) return `${q.value} ${q.unit || ""}`.trim()
  return ""
}

export function observationValue(r: FhirResource): string {
  const vq = r.valueQuantity as { value?: number; unit?: string } | undefined
  if (vq?.value !== undefined) return `${vq.value} ${vq.unit || ""}`.trim()
  const vs = r.valueString as string | undefined
  if (vs) return vs
  const vcc = codeableDisplay(r.valueCodeableConcept)
  if (vcc) return vcc
  return ""
}

export function resourceDisplayName(r: FhirResource): string {
  const type = r.resourceType
  if (type === "MedicationRequest") return codeableDisplay(r.medicationCodeableConcept) || referenceDisplay(r.medicationReference)
  if (type === "AllergyIntolerance" || type === "Condition" || type === "Procedure" || type === "Observation") {
    return codeableDisplay(r.code)
  }
  if (type === "FamilyMemberHistory") return codeableDisplay(r.relationship)
  if (type === "DocumentReference") return codeableDisplay(r.type) || "Document"
  if (type === "Provenance") {
    const targets = r.target as Array<Record<string, unknown>> | undefined
    const first = targets?.[0]
    return referenceDisplay(first) || "Provenance"
  }
  return ""
}

export function provenanceTargets(r: FhirResource): string[] {
  const targets = r.target as Array<Record<string, unknown>> | undefined
  if (!targets) return []
  return targets
    .map((t) => (t.reference as string) || "")
    .filter(Boolean)
}

export function humanName(name: unknown): string {
  if (!name) return ""
  const arr = Array.isArray(name) ? name : [name]
  for (const n of arr as Array<Record<string, unknown>>) {
    const prefix = (n.prefix as string[] | undefined)?.join(" ") || ""
    const given = (n.given as string[] | undefined)?.join(" ") || ""
    const family = (n.family as string) || ""
    const joined = [prefix, given, family].filter(Boolean).join(" ").trim()
    if (joined) return joined
    const text = (n.text as string) || ""
    if (text) return text
  }
  return ""
}

export function ageFromBirth(birthDate: string | undefined | null): string {
  if (!birthDate) return ""
  const d = new Date(birthDate)
  if (isNaN(d.getTime())) return ""
  const now = new Date()
  let age = now.getFullYear() - d.getFullYear()
  const m = now.getMonth() - d.getMonth()
  if (m < 0 || (m === 0 && now.getDate() < d.getDate())) age--
  return String(age)
}

export function mrnFromIdentifiers(identifier: unknown): string {
  if (!Array.isArray(identifier)) return ""
  for (const id of identifier as Array<Record<string, unknown>>) {
    const type = id.type as { coding?: Array<{ code?: string }>; text?: string } | undefined
    const code = type?.coding?.[0]?.code
    if (code === "MR" || type?.text?.toLowerCase().includes("medical record")) {
      return (id.value as string) || ""
    }
  }
  const first = (identifier as Array<Record<string, unknown>>)[0]
  return (first?.value as string) || ""
}

export function npiFromIdentifiers(identifier: unknown): string {
  if (!Array.isArray(identifier)) return ""
  for (const id of identifier as Array<Record<string, unknown>>) {
    const system = (id.system as string) || ""
    if (system.includes("us-npi")) return (id.value as string) || ""
  }
  return ""
}

export function addressLine(address: unknown): string {
  if (!Array.isArray(address) || address.length === 0) return ""
  const a = address[0] as Record<string, unknown>
  const line = (a.line as string[] | undefined)?.join(", ") || ""
  const cityState = [a.city, a.state].filter(Boolean).join(", ")
  return [line, cityState].filter(Boolean).join(" · ")
}

export function telecomFor(telecom: unknown, system: string): string {
  if (!Array.isArray(telecom)) return ""
  const match = (telecom as Array<Record<string, unknown>>).find((t) => t.system === system)
  return (match?.value as string) || ""
}

export function resourceDate(r: FhirResource): string {
  const type = r.resourceType
  if (type === "Condition") return (r.onsetDateTime as string) || (r.recordedDate as string) || ""
  if (type === "MedicationRequest") return (r.authoredOn as string) || ""
  if (type === "AllergyIntolerance") return (r.recordedDate as string) || ""
  if (type === "Observation") return (r.effectiveDateTime as string) || ""
  if (type === "Procedure") return (r.performedDateTime as string) || ""
  if (type === "Encounter") {
    const period = r.period as { start?: string; end?: string } | undefined
    return period?.start || ""
  }
  if (type === "DocumentReference") return (r.date as string) || ""
  if (type === "Provenance") return (r.recorded as string) || ""
  return ""
}

export function encounterType(r: FhirResource): string {
  const types = r.type as Array<Record<string, unknown>> | undefined
  if (!types || types.length === 0) {
    const cls = r.class as { display?: string; code?: string } | undefined
    return cls?.display || cls?.code || ""
  }
  return codeableDisplay(types[0])
}

function summarizeCondition(r: FhirResource): SummaryRow[] {
  const rows: SummaryRow[] = []
  const name = codeableDisplay(r.code)
  if (name) rows.push({ label: "Condition", value: name })
  rows.push({ label: "Status", value: stateLabel(r) })
  const onset = (r.onsetDateTime as string) || ""
  if (onset) rows.push({ label: "Onset", value: shortDate(onset) })
  const recorded = (r.recordedDate as string) || ""
  if (recorded) rows.push({ label: "Recorded", value: shortDate(recorded) })
  const recorder = referenceDisplay(r.recorder)
  if (recorder) rows.push({ label: "Recorder", value: recorder })
  return rows
}

function summarizeMedication(r: FhirResource): SummaryRow[] {
  const rows: SummaryRow[] = []
  const name = codeableDisplay(r.medicationCodeableConcept)
  if (name) rows.push({ label: "Medication", value: name })
  rows.push({ label: "Status", value: (r.status as string) || "active" })
  const dose = doseSummary(r)
  if (dose) rows.push({ label: "Dose", value: dose })
  const authored = (r.authoredOn as string) || ""
  if (authored) rows.push({ label: "Prescribed", value: shortDate(authored) })
  const requester = referenceDisplay(r.requester)
  if (requester) rows.push({ label: "Prescriber", value: requester })
  return rows
}

function summarizeAllergy(r: FhirResource): SummaryRow[] {
  const rows: SummaryRow[] = []
  const name = codeableDisplay(r.code)
  if (name) rows.push({ label: "Substance", value: name })
  const cs = r.clinicalStatus as { coding?: Array<{ code?: string }> } | undefined
  rows.push({ label: "Status", value: cs?.coding?.[0]?.code || "active" })
  const crit = r.criticality as string | undefined
  if (crit) rows.push({ label: "Criticality", value: crit })
  const recorded = (r.recordedDate as string) || ""
  if (recorded) rows.push({ label: "Recorded", value: shortDate(recorded) })
  return rows
}

function summarizeObservation(r: FhirResource): SummaryRow[] {
  const rows: SummaryRow[] = []
  const name = codeableDisplay(r.code)
  if (name) rows.push({ label: "Observation", value: name })
  const value = observationValue(r)
  if (value) rows.push({ label: "Value", value })
  rows.push({ label: "Status", value: (r.status as string) || "" })
  const eff = (r.effectiveDateTime as string) || ""
  if (eff) rows.push({ label: "Recorded", value: shortDate(eff) })
  return rows
}

function summarizeProcedure(r: FhirResource): SummaryRow[] {
  const rows: SummaryRow[] = []
  const name = codeableDisplay(r.code)
  if (name) rows.push({ label: "Procedure", value: name })
  rows.push({ label: "Status", value: (r.status as string) || "" })
  const performed = (r.performedDateTime as string) || ""
  if (performed) rows.push({ label: "Performed", value: shortDate(performed) })
  return rows
}

function summarizeFamilyHistory(r: FhirResource): SummaryRow[] {
  const rows: SummaryRow[] = []
  const rel = codeableDisplay(r.relationship)
  if (rel) rows.push({ label: "Relationship", value: rel })
  const conditions = (r.condition as Array<Record<string, unknown>>) || []
  if (conditions.length > 0) {
    const names = conditions
      .map((c) => codeableDisplay(c.code))
      .filter(Boolean)
      .join(", ")
    if (names) rows.push({ label: "Conditions", value: names })
  }
  return rows
}
