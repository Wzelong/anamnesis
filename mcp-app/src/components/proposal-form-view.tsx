import { useState } from "react"
import { CalendarIcon } from "lucide-react"
import { RESOURCE_LABEL } from "../lib/proposal-meta"
import { cn } from "../lib/cn"
import { Input } from "./ui/input"
import { Textarea } from "./ui/textarea"
import { Label } from "./ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { Popover, PopoverContent, PopoverTrigger } from "./ui/popover"
import { Calendar } from "./ui/calendar"
import { Button } from "./ui/button"

type FhirResource = Record<string, unknown>
type Mode = "view" | "edit"

interface Props {
  resource: FhirResource
  mode?: Mode
  source?: string
  onChange?: (next: FhirResource) => void
}

type EditSpec =
  | { kind: "text"; onChange: (v: string) => void }
  | { kind: "number"; onChange: (v: number | null) => void }
  | { kind: "select"; options: string[]; onChange: (v: string) => void }
  | { kind: "date"; onChange: (v: string) => void }
  | { kind: "textarea"; onChange: (v: string) => void }
  | { kind: "codepair"; code: string; display: string; onChange: (code: string, display: string) => void }

interface Row {
  label: string
  value: string
  edit?: EditSpec
  kind?: "header" | "meta"
}

const SKIP_FIELDS = new Set([
  "id", "meta", "resourceType", "text", "extension", "modifierExtension",
  "implicitRules", "language", "contained",
])

const SYSTEM_LABEL: Record<string, string> = {
  "http://snomed.info/sct": "SNOMED CT",
  "http://hl7.org/fhir/sid/icd-10-cm": "ICD-10-CM",
  "http://hl7.org/fhir/sid/icd-10": "ICD-10",
  "http://hl7.org/fhir/sid/icd-9-cm": "ICD-9-CM",
  "http://www.nlm.nih.gov/research/umls/rxnorm": "RxNorm",
  "http://loinc.org": "LOINC",
  "http://unitsofmeasure.org": "UCUM",
  "http://hl7.org/fhir/sid/cvx": "CVX",
  "http://hl7.org/fhir/sid/ndc": "NDC",
  "http://www.ama-assn.org/go/cpt": "CPT",
}

function systemLabel(system: string | undefined): string {
  if (!system) return "Code"
  if (SYSTEM_LABEL[system]) return SYSTEM_LABEL[system]
  if (system.startsWith("http://terminology.hl7.org/CodeSystem/")) {
    return system.replace("http://terminology.hl7.org/CodeSystem/", "")
  }
  return system.split("/").pop() || system
}

const FIELD_LABEL: Record<string, string> = {
  clinicalStatus: "Clinical status", verificationStatus: "Verification",
  onsetDateTime: "Onset", onsetAge: "Onset age", onsetPeriod: "Onset",
  recordedDate: "Recorded", effectiveDateTime: "Effective", effectivePeriod: "Effective",
  performedDateTime: "Performed", performedPeriod: "Performed", authoredOn: "Authored",
  bodySite: "Body site", dosageInstruction: "Dosage",
  medicationCodeableConcept: "Medication", medicationReference: "Medication",
  valueQuantity: "Value", valueCodeableConcept: "Value", valueString: "Value",
  valueBoolean: "Value", valueInteger: "Value", valueDateTime: "Value",
  manifestation: "Manifestation", reaction: "Reaction", recorder: "Recorder",
  asserter: "Asserter", recordedAge: "Age recorded",
}

const CONDITION_CLINICAL = ["active", "recurrence", "relapse", "inactive", "remission", "resolved"]
const CONDITION_VERIFICATION = ["unconfirmed", "provisional", "differential", "confirmed", "refuted", "entered-in-error"]
const MED_STATUS = ["active", "on-hold", "cancelled", "completed", "entered-in-error", "stopped", "draft", "unknown"]
const MED_INTENT = ["proposal", "plan", "order", "original-order", "reflex-order", "filler-order", "instance-order", "option"]
const OBS_STATUS = ["registered", "preliminary", "final", "amended", "corrected", "cancelled", "entered-in-error", "unknown"]
const PROC_STATUS = ["preparation", "in-progress", "not-done", "on-hold", "stopped", "completed", "entered-in-error", "unknown"]
const ALLERGY_TYPE = ["allergy", "intolerance"]
const ALLERGY_CATEGORY = ["food", "medication", "environment", "biologic"]
const ALLERGY_CRITICALITY = ["low", "high", "unable-to-assess"]

export function ProposalFormView({ resource, mode = "view", source, onChange }: Props) {
  const rows = buildRows(resource, onChange ?? (() => {}))
  if (source) rows.push({ label: "Source", value: source })
  if (rows.length === 0) {
    return <div className="text-sm text-muted-foreground italic">No fields</div>
  }
  if (mode === "edit") {
    return (
      <div className="flex flex-col gap-4">
        {rows.filter((r) => r.kind !== "meta").map((row, i) => <EditRow key={i} row={row} />)}
      </div>
    )
  }
  return (
    <dl className="flex flex-col gap-1.5">
      {rows.map((row, i) => <ViewRow key={i} row={row} />)}
    </dl>
  )
}

function ViewRow({ row }: { row: Row }) {
  if (row.kind === "header") return <RowHeader label={row.label} />
  if (!row.value) return null
  return (
    <div className="grid grid-cols-[140px_1fr] gap-3 items-baseline">
      <dt className="text-xs text-muted-foreground">{row.label}</dt>
      <dd className="text-sm min-w-0 break-words">{row.value}</dd>
    </div>
  )
}

function EditRow({ row }: { row: Row }) {
  if (row.kind === "header") return <RowHeader label={row.label} />
  return (
    <div className="space-y-1.5">
      <Label className="text-xs text-muted-foreground">{row.label}</Label>
      {row.edit ? (
        <EditInput edit={row.edit} value={row.value} />
      ) : (
        <div className="text-sm text-muted-foreground break-words">{row.value || <span className="italic">—</span>}</div>
      )}
    </div>
  )
}

function RowHeader({ label }: { label: string }) {
  return (
    <div>
      <span className="inline-block px-1.5 py-0.5 rounded bg-muted text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
    </div>
  )
}

function EditInput({ edit, value }: { edit: EditSpec; value: string }) {
  if (edit.kind === "select") {
    return (
      <Select value={value || undefined} onValueChange={(v) => edit.onChange(v)}>
        <SelectTrigger className="w-full text-sm"><SelectValue placeholder="Select…" /></SelectTrigger>
        <SelectContent>
          {edit.options.map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
        </SelectContent>
      </Select>
    )
  }
  if (edit.kind === "textarea") {
    return (
      <Textarea
        value={value}
        onChange={(e) => edit.onChange(e.target.value)}
        rows={2}
        className="text-sm min-h-[60px] resize-none"
      />
    )
  }
  if (edit.kind === "codepair") {
    return (
      <div className="flex gap-2">
        <Input
          value={edit.code}
          onChange={(e) => edit.onChange(e.target.value, edit.display)}
          placeholder="Code"
          className="w-28 shrink-0 text-sm font-mono"
        />
        <Input
          value={edit.display}
          onChange={(e) => edit.onChange(edit.code, e.target.value)}
          placeholder="Display"
          className="flex-1 text-sm"
        />
      </div>
    )
  }
  if (edit.kind === "number") {
    return (
      <Input
        type="number"
        value={value}
        onChange={(e) => { const n = parseFloat(e.target.value); edit.onChange(isNaN(n) ? null : n) }}
        className="text-sm"
      />
    )
  }
  if (edit.kind === "date") {
    return <DateInput value={value} onChange={(v) => edit.onChange(v)} />
  }
  return (
    <Input type="text" value={value} onChange={(e) => edit.onChange(e.target.value)} className="text-sm" />
  )
}

function DateInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false)
  const parsed = value ? new Date(value + "T00:00:00") : undefined
  const valid = parsed && !isNaN(parsed.getTime()) ? parsed : undefined
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" className={cn("w-full justify-start text-sm font-normal", !valid && "text-muted-foreground")}>
          <CalendarIcon className="size-3.5" />
          {valid ? valid.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "Pick a date"}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar
          mode="single"
          selected={valid}
          onSelect={(d) => {
            if (d) {
              const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
              onChange(iso)
            }
            setOpen(false)
          }}
          autoFocus
        />
      </PopoverContent>
    </Popover>
  )
}

function buildRows(resource: FhirResource, onChange: (next: FhirResource) => void): Row[] {
  const rt = resource.resourceType
  const resourceTypeRow: Row = {
    label: "ResourceType",
    value: typeof rt === "string" ? (RESOURCE_LABEL[rt] ?? rt) : "",
    kind: "meta",
  }
  let curated: Row[] = []
  const consumed = new Set<string>(["resourceType"])
  switch (rt) {
    case "Condition":
      curated = conditionRows(resource, onChange)
      addAll(consumed, ["code", "clinicalStatus", "verificationStatus", "onsetDateTime", "recordedDate", "severity", "subject", "encounter", "note"])
      break
    case "MedicationRequest":
      curated = medicationRequestRows(resource, onChange)
      addAll(consumed, ["medicationCodeableConcept", "medicationReference", "dosageInstruction", "status", "intent", "authoredOn", "subject", "requester", "encounter", "note"])
      break
    case "Observation":
      curated = observationRows(resource, onChange)
      addAll(consumed, ["code", "component", "valueQuantity", "valueCodeableConcept", "valueString", "status", "effectiveDateTime", "subject", "encounter", "method"])
      break
    case "Procedure":
      curated = procedureRows(resource, onChange)
      addAll(consumed, ["code", "status", "performedDateTime", "bodySite", "subject", "encounter"])
      break
    case "AllergyIntolerance":
      curated = allergyRows(resource, onChange)
      addAll(consumed, ["code", "type", "category", "criticality", "reaction", "recordedDate", "patient"])
      break
    case "FamilyMemberHistory":
      curated = familyHistoryRows(resource, onChange)
      addAll(consumed, ["relationship", "patient", "condition", "bornDate"])
      break
    default:
      return [resourceTypeRow, ...genericRows(resource, onChange)]
  }
  const extras = genericRows(
    Object.fromEntries(Object.entries(resource).filter(([k]) => !consumed.has(k))),
    (next) => onChange({ ...resource, ...next }),
  )
  return [resourceTypeRow, ...curated, ...extras]
}

function addAll(set: Set<string>, keys: string[]) {
  for (const k of keys) set.add(k)
}

function conditionRows(r: FhirResource, onChange: (n: FhirResource) => void): Row[] {
  const setField = (key: string) => (next: unknown) => onChange({ ...r, [key]: next })
  return [
    ...ccRowWithCodings("Condition", r.code, setField("code")),
    statusCcRow("Clinical status", r.clinicalStatus, setField("clinicalStatus"), CONDITION_CLINICAL),
    statusCcRow("Verification", r.verificationStatus, setField("verificationStatus"), CONDITION_VERIFICATION),
    dateRow("Onset", r.onsetDateTime as string | undefined, setField("onsetDateTime")),
    dateRow("Recorded", r.recordedDate as string | undefined, setField("recordedDate")),
    ...ccRowWithCodings("Severity", r.severity, setField("severity")),
    refRow("Subject", r.subject),
    refRow("Encounter", r.encounter),
    noteRow("Note", r.note, setField("note")),
  ].filter(Boolean) as Row[]
}

function medicationRequestRows(r: FhirResource, onChange: (n: FhirResource) => void): Row[] {
  const setField = (key: string) => (next: unknown) => onChange({ ...r, [key]: next })
  const medCC = r.medicationCodeableConcept
  const medRows = medCC
    ? ccRowWithCodings("Medication", medCC, setField("medicationCodeableConcept"))
    : (() => { const ref = refRow("Medication", r.medicationReference); return ref ? [ref] : [] })()
  return [
    ...medRows,
    dosageRow("Dosage", r.dosageInstruction, setField("dosageInstruction")),
    selectRow("Status", r.status as string, MED_STATUS, setField("status")),
    selectRow("Intent", r.intent as string, MED_INTENT, setField("intent")),
    dateRow("Authored", r.authoredOn as string | undefined, setField("authoredOn")),
    refRow("Subject", r.subject),
    refRow("Requester", r.requester),
    refRow("Encounter", r.encounter),
    noteRow("Note", r.note, setField("note")),
  ].filter(Boolean) as Row[]
}

function observationRows(r: FhirResource, onChange: (n: FhirResource) => void): Row[] {
  const setField = (key: string) => (next: unknown) => onChange({ ...r, [key]: next })
  const rows: Row[] = []
  rows.push(...ccRowWithCodings("Observation", r.code, setField("code")))
  const components = Array.isArray(r.component) ? (r.component as Array<Record<string, unknown>>) : []
  if (components.length > 0) {
    components.forEach((comp, i) => {
      const label = getCC(comp.code) || `Component ${i + 1}`
      const value = getQuantityString(comp.valueQuantity) || getCC(comp.valueCodeableConcept)
      const qty = comp.valueQuantity as Record<string, unknown> | undefined
      rows.push({
        label, value,
        edit: qty ? { kind: "text", onChange: (raw: string) => {
          const parsed = parseQuantity(raw)
          if (parsed) { const next = [...components]; next[i] = { ...comp, valueQuantity: { ...(qty ?? {}), ...parsed } }; onChange({ ...r, component: next }) }
        } } : undefined,
      })
      rows.push(...codingRows(comp.code))
    })
  } else {
    push(rows, valueRow("Value", r, setField))
  }
  push(rows, selectRow("Status", r.status as string, OBS_STATUS, setField("status")))
  push(rows, dateRow("Effective", r.effectiveDateTime as string | undefined, setField("effectiveDateTime")))
  push(rows, refRow("Subject", r.subject))
  push(rows, refRow("Encounter", r.encounter))
  rows.push(...ccRowWithCodings("Method", r.method, setField("method")))
  return rows
}

function procedureRows(r: FhirResource, onChange: (n: FhirResource) => void): Row[] {
  const setField = (key: string) => (next: unknown) => onChange({ ...r, [key]: next })
  const bodySites = Array.isArray(r.bodySite) ? (r.bodySite as unknown[]) : []
  const rows: Row[] = []
  rows.push(...ccRowWithCodings("Procedure", r.code, setField("code")))
  push(rows, selectRow("Status", r.status as string, PROC_STATUS, setField("status")))
  push(rows, dateRow("Performed", r.performedDateTime as string | undefined, setField("performedDateTime")))
  if (bodySites[0]) {
    rows.push(...ccRowWithCodings("Body site", bodySites[0], (next) => onChange({ ...r, bodySite: [next, ...bodySites.slice(1)] })))
  }
  push(rows, refRow("Subject", r.subject))
  push(rows, refRow("Encounter", r.encounter))
  return rows
}

function allergyRows(r: FhirResource, onChange: (n: FhirResource) => void): Row[] {
  const setField = (key: string) => (next: unknown) => onChange({ ...r, [key]: next })
  const reaction = Array.isArray(r.reaction) ? (r.reaction as Array<Record<string, unknown>>) : []
  const manifestation = reaction[0] ? getCC((reaction[0].manifestation as unknown[])?.[0]) : ""
  return [
    ...ccRowWithCodings("Substance", r.code, setField("code")),
    selectRow("Type", r.type as string, ALLERGY_TYPE, setField("type")),
    selectRow("Category", Array.isArray(r.category) ? ((r.category as string[])[0] ?? "") : "", ALLERGY_CATEGORY, (v) => onChange({ ...r, category: v ? [v] : [] })),
    selectRow("Criticality", r.criticality as string, ALLERGY_CRITICALITY, setField("criticality")),
    {
      label: "Reaction", value: manifestation,
      edit: { kind: "text", onChange: (raw: string) => {
        const arr = [...reaction]
        const m = Array.isArray(arr[0]?.manifestation) ? (arr[0].manifestation as unknown[]) : []
        const firstM = (m[0] as Record<string, unknown>) ?? {}
        arr[0] = { ...(arr[0] ?? {}), manifestation: [{ ...firstM, text: raw }, ...m.slice(1)] }
        onChange({ ...r, reaction: arr })
      } },
    },
    dateRow("Recorded", r.recordedDate as string | undefined, setField("recordedDate")),
    refRow("Patient", r.patient),
  ].filter(Boolean) as Row[]
}

function familyHistoryRows(r: FhirResource, onChange: (n: FhirResource) => void): Row[] {
  const setField = (key: string) => (next: unknown) => onChange({ ...r, [key]: next })
  const conditions = Array.isArray(r.condition) ? (r.condition as Array<Record<string, unknown>>) : []
  const first = conditions[0] ?? {}
  const updateFirst = (patch: Record<string, unknown>) =>
    onChange({ ...r, condition: conditions.length > 0 ? [{ ...first, ...patch }, ...conditions.slice(1)] : [patch] })
  const onsetAge = first.onsetAge as Record<string, unknown> | undefined
  return [
    ...ccRowWithCodings("Relationship", r.relationship, setField("relationship")),
    refRow("Patient", r.patient),
    ...ccRowWithCodings("Condition", first.code, (next) => updateFirst({ code: next })),
    {
      label: "Onset age", value: onsetAge?.value !== undefined ? `${onsetAge.value}` : "",
      edit: { kind: "number", onChange: (n: number | null) => updateFirst({
        onsetAge: n == null ? undefined : { value: n, unit: onsetAge?.unit ?? "a", system: "http://unitsofmeasure.org", code: "a" },
      }) },
    },
    dateRow("Born", r.bornDate as string | undefined, setField("bornDate")),
  ].filter(Boolean) as Row[]
}

function genericRows(r: FhirResource, onChange: (n: FhirResource) => void): Row[] {
  const rows: Row[] = []
  for (const [k, v] of Object.entries(r)) {
    if (SKIP_FIELDS.has(k)) continue
    pushFlat(rows, humanize(k), v, (next) => onChange({ ...r, [k]: next }))
  }
  return rows
}

function pushFlat(rows: Row[], label: string, value: unknown, setField: (n: unknown) => void) {
  if (value === null || value === undefined) return
  if (typeof value !== "object") {
    rows.push({
      label, value: String(value),
      edit: typeof value === "number" ? { kind: "number", onChange: (v) => setField(v) } : { kind: "text", onChange: (v) => setField(v) },
    })
    return
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return
    value.forEach((item, i) => {
      pushFlat(rows, value.length > 1 ? `${label} ${i + 1}` : label, item, (next) => { const arr = [...value]; arr[i] = next; setField(arr) })
    })
    return
  }
  if (isCC(value)) { push(rows, ccRow(label, value, setField)); return }
  if (isQuantity(value)) { rows.push({ label, value: getQuantityString(value) }); return }
  if (isReference(value)) { push(rows, refRow(label, value)); return }
  if (isPeriod(value)) {
    const p = value as Record<string, unknown>
    const start = typeof p.start === "string" ? formatDate(p.start) : ""
    const end = typeof p.end === "string" ? formatDate(p.end) : ""
    rows.push({ label, value: start && end ? `${start} – ${end}` : start || end })
    return
  }
  for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
    if (SKIP_FIELDS.has(k)) continue
    pushFlat(rows, `${label} · ${humanize(k)}`, v, (next) => setField({ ...(value as Record<string, unknown>), [k]: next }))
  }
}

function ccRow(label: string, cc: unknown, setField?: (next: unknown) => void): Row | null {
  if (!cc || typeof cc !== "object") return null
  const obj = cc as Record<string, unknown>
  const text = getCC(obj)
  if (!text && !setField) return null
  return {
    label, value: text,
    edit: setField ? { kind: "text", onChange: (raw: string) => setField({ ...obj, text: raw }) } : undefined,
  }
}

function codingRows(cc: unknown, setField?: (next: unknown) => void): Row[] {
  if (!cc || typeof cc !== "object") return []
  const obj = cc as Record<string, unknown>
  const arr = Array.isArray(obj.coding) ? (obj.coding as Array<Record<string, unknown>>) : []
  const multiple = arr.length > 1
  return arr.map((c, i) => {
    const code = typeof c.code === "string" ? c.code : ""
    const display = typeof c.display === "string" ? c.display : ""
    const system = typeof c.system === "string" ? c.system : ""
    if (!code && !display && !setField) return null
    const value = code && display ? `${code} · ${display}` : code || display
    const label = multiple ? `Coding ${i + 1}` : systemLabel(system)
    return {
      label, value,
      edit: setField ? {
        kind: "codepair", code, display,
        onChange: (newCode: string, newDisplay: string) => {
          const next = [...arr]
          next[i] = { ...c, code: newCode.trim() || undefined, display: newDisplay.trim() || undefined }
          setField({ ...obj, coding: next })
        },
      } : undefined,
    } as Row
  }).filter((x): x is Row => x !== null)
}

function ccRowWithCodings(label: string, cc: unknown, setField?: (next: unknown) => void): Row[] {
  const main = ccRow(label, cc, setField)
  const codings = codingRows(cc, setField)
  return main ? [main, ...codings] : codings
}

function statusCcRow(label: string, cc: unknown, setField: (next: unknown) => void, options: string[]): Row | null {
  const obj = (cc && typeof cc === "object" ? cc : {}) as Record<string, unknown>
  const coding = Array.isArray(obj.coding) ? obj.coding : []
  const first = (coding[0] as Record<string, unknown>) ?? {}
  const code = typeof first.code === "string" ? first.code : ""
  if (!code && Object.keys(obj).length === 0) return null
  return {
    label, value: code,
    edit: { kind: "select", options, onChange: (v) => setField({ ...obj, coding: [{ ...first, code: v }, ...coding.slice(1)] }) },
  }
}

function dateRow(label: string, value: string | undefined, setField: (next: unknown) => void): Row | null {
  if (!value && !setField) return null
  return { label, value: value ?? "", edit: { kind: "date", onChange: (v) => setField(v || undefined) } }
}

function selectRow(label: string, value: string | undefined, options: string[], setField: (next: unknown) => void): Row {
  return { label, value: value ?? "", edit: { kind: "select", options, onChange: (v) => setField(v) } }
}

function refRow(label: string, ref: unknown): Row | null {
  if (!ref || typeof ref !== "object") return null
  const obj = ref as Record<string, unknown>
  const value = (typeof obj.display === "string" ? obj.display : "") || (typeof obj.reference === "string" ? obj.reference : "")
  return value ? { label, value } : null
}

function dosageRow(label: string, dosage: unknown, setField: (next: unknown) => void): Row | null {
  const arr = Array.isArray(dosage) ? (dosage as Array<Record<string, unknown>>) : []
  const first = arr[0] ?? {}
  const text = typeof first.text === "string" ? first.text : ""
  if (!text && arr.length === 0) return null
  return { label, value: text, edit: { kind: "textarea", onChange: (raw) => setField([{ ...first, text: raw }, ...arr.slice(1)]) } }
}

function noteRow(label: string, notes: unknown, setField?: (next: unknown) => void): Row | null {
  const arr = Array.isArray(notes) ? (notes as Array<Record<string, unknown>>) : []
  const first = arr[0] ?? {}
  const text = typeof first.text === "string" ? first.text : ""
  if (!text && !setField) return null
  return {
    label, value: text,
    edit: setField ? { kind: "textarea", onChange: (raw: string) => {
      if (!raw && arr.length === 0) { setField(undefined); return }
      setField([{ ...first, text: raw }, ...arr.slice(1)])
    } } : undefined,
  }
}

function valueRow(label: string, r: FhirResource, setField: (key: string) => (n: unknown) => void): Row | null {
  const qty = r.valueQuantity as Record<string, unknown> | undefined
  if (qty) {
    return { label, value: getQuantityString(qty), edit: { kind: "text", onChange: (raw) => { const parsed = parseQuantity(raw); if (parsed) setField("valueQuantity")({ ...qty, ...parsed }) } } }
  }
  const cc = r.valueCodeableConcept
  if (cc) return ccRow(label, cc, setField("valueCodeableConcept"))
  const str = r.valueString
  if (typeof str === "string") return { label, value: str, edit: { kind: "text", onChange: (v) => setField("valueString")(v) } }
  return null
}

function getCC(cc: unknown): string {
  if (!cc) return ""
  if (typeof cc === "string") return cc
  if (typeof cc !== "object") return ""
  const obj = cc as Record<string, unknown>
  if (typeof obj.text === "string" && obj.text) return obj.text
  if (Array.isArray(obj.coding)) {
    for (const c of obj.coding) {
      const coding = c as Record<string, unknown>
      if (typeof coding.display === "string" && coding.display) return coding.display
      if (typeof coding.code === "string" && coding.code) return coding.code
    }
  }
  return ""
}

function getQuantityString(q: unknown): string {
  if (!q || typeof q !== "object") return ""
  const obj = q as Record<string, unknown>
  if (obj.value === undefined || obj.value === null) return ""
  return `${obj.value}${obj.unit ? ` ${obj.unit}` : ""}`
}

function isCC(v: unknown): boolean {
  if (!v || typeof v !== "object") return false
  const obj = v as Record<string, unknown>
  return Array.isArray(obj.coding) || typeof obj.text === "string"
}

function isQuantity(v: unknown): boolean {
  if (!v || typeof v !== "object") return false
  const obj = v as Record<string, unknown>
  return "value" in obj && (typeof obj.value === "number" || obj.value === undefined)
    && (typeof obj.unit === "string" || typeof obj.code === "string" || obj.unit === undefined)
}

function isReference(v: unknown): boolean {
  if (!v || typeof v !== "object") return false
  const obj = v as Record<string, unknown>
  return typeof obj.reference === "string" || typeof obj.display === "string"
}

function isPeriod(v: unknown): boolean {
  if (!v || typeof v !== "object") return false
  const obj = v as Record<string, unknown>
  return typeof obj.start === "string" || typeof obj.end === "string"
}

function parseQuantity(s: string): { value?: number; unit?: string } | null {
  const trimmed = s.trim()
  if (!trimmed) return { value: undefined, unit: undefined }
  const match = trimmed.match(/^(-?\d+(?:\.\d+)?)\s*(.*)$/)
  if (!match) return null
  const value = parseFloat(match[1])
  if (isNaN(value)) return null
  return { value, unit: match[2].trim() || undefined }
}

function formatDate(s: string): string {
  const d = new Date(s)
  if (isNaN(d.getTime())) return s
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
}

function humanize(key: string): string {
  if (FIELD_LABEL[key]) return FIELD_LABEL[key]
  return key.replace(/([A-Z])/g, " $1").toLowerCase().replace(/^./, (c) => c.toUpperCase()).trim()
}

function push<T>(arr: T[], item: T | null | undefined) {
  if (item) arr.push(item)
}
