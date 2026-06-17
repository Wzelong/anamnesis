export type FhirResource = Record<string, unknown>

export interface SummaryRow {
  label: string
  value: string
}

export function summarize(r: FhirResource): SummaryRow[] {
  switch (r.resourceType as string) {
    case "Condition": return summarizeCondition(r)
    case "MedicationRequest": return summarizeMedication(r)
    case "AllergyIntolerance": return summarizeAllergy(r)
    case "Observation": return summarizeObservation(r)
    case "Procedure": return summarizeProcedure(r)
    case "FamilyMemberHistory": return summarizeFamilyHistory(r)
    default: return [{ label: "Resource", value: (r.resourceType as string) || "unknown" }]
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

function codeableDisplay(cc: unknown): string {
  if (!cc || typeof cc !== "object") return ""
  const obj = cc as { text?: string; coding?: Array<{ display?: string; code?: string }> }
  if (obj.text) return obj.text
  const c = obj.coding?.[0]
  return c?.display || c?.code || ""
}

function referenceDisplay(ref: unknown): string {
  if (!ref || typeof ref !== "object") return ""
  const r = ref as { display?: string; reference?: string }
  return r.display || r.reference || ""
}

function shortDate(iso: string | undefined | null): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
}

function doseSummary(r: FhirResource): string {
  const di = (r.dosageInstruction as Array<Record<string, unknown>>) || []
  if (di.length === 0) return ""
  const first = di[0]
  if (first.text) return first.text as string
  const dr = (first.doseAndRate as Array<Record<string, unknown>>)?.[0]
  const q = dr?.doseQuantity as { value?: number; unit?: string } | undefined
  if (q?.value !== undefined) return `${q.value} ${q.unit || ""}`.trim()
  return ""
}

function observationValue(r: FhirResource): string {
  const vq = r.valueQuantity as { value?: number; unit?: string } | undefined
  if (vq?.value !== undefined) return `${vq.value} ${vq.unit || ""}`.trim()
  const vs = r.valueString as string | undefined
  if (vs) return vs
  return codeableDisplay(r.valueCodeableConcept)
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
    const names = conditions.map((c) => codeableDisplay(c.code)).filter(Boolean).join(", ")
    if (names) rows.push({ label: "Conditions", value: names })
  }
  return rows
}
