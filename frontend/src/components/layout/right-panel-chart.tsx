"use client"

import { useMemo } from "react"
import { cn } from "@/lib/utils"
import {
  type FhirResource,
  addressLine,
  ageFromBirth,
  codeableDisplay,
  encounterType,
  humanName,
  mrnFromIdentifiers,
  npiFromIdentifiers,
  provenanceTargets,
  referenceDisplay,
  resourceDate,
  resourceDisplayName,
  shortDate,
  stateLabel,
  telecomFor,
} from "@/lib/fhir-summary"
import type { ChartContext, ChartMatch } from "@/lib/types"
import { Disclosure } from "@/components/ui/disclosure"

interface Props {
  chart: ChartContext | null
  classification: "NEW" | "UPDATING" | "CONFLICTING"
  chartMatches: ChartMatch[]
}

const CLINICAL_SECTIONS: Array<{
  key: keyof ChartContext
  label: string
  defaultOpen: boolean
}> = [
  { key: "conditions", label: "Conditions", defaultOpen: true },
  { key: "medications", label: "Medications", defaultOpen: true },
  { key: "allergies", label: "Allergies", defaultOpen: true },
  { key: "observations", label: "Observations", defaultOpen: false },
  { key: "procedures", label: "Procedures", defaultOpen: false },
  { key: "family_history", label: "Family History", defaultOpen: false },
]

function isInactive(r: FhirResource): boolean {
  const s = stateLabel(r).toLowerCase()
  return s === "resolved" || s === "inactive" || s === "remission" || s === "stopped" ||
    s === "completed" || s === "cancelled" || s === "entered-in-error"
}

function sortByDateDesc(a: FhirResource, b: FhirResource): number {
  const da = resourceDate(a)
  const db = resourceDate(b)
  return (db || "").localeCompare(da || "")
}

export function RightPanelChart({ chart, classification, chartMatches }: Props) {
  const highlightedIds = useMemo(
    () => new Set(
      classification === "CONFLICTING" ? chartMatches.map((m) => m.resource_id) : [],
    ),
    [classification, chartMatches],
  )
  const orgIndex = useMemo(
    () => buildOrgIndex(chart?.organizations ?? []),
    [chart?.organizations],
  )
  const refIndex = useMemo(() => buildRefIndex(chart), [chart])

  if (!chart) {
    return <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">Loading…</div>
  }

  const encounters = [...chart.encounters].sort(sortByDateDesc)

  return (
    <div className="flex-1 min-h-0 overflow-auto px-3 py-3 flex flex-col gap-4">
      <PersonHero patient={chart.patient} />

      {CLINICAL_SECTIONS.map((section) => {
        const items = (chart[section.key] as FhirResource[]) || []
        if (items.length === 0) return null
        const active = items.filter((r) => !isInactive(r)).sort(sortByDateDesc)
        const inactive = items.filter((r) => isInactive(r)).sort(sortByDateDesc)
        const sorted = [...active, ...inactive]
        const hasHighlight = sorted.some((r) => highlightedIds.has(r.id as string))
        const open = section.defaultOpen || hasHighlight
        return (
          <Disclosure
            key={section.key}
            title={`${section.label} (${items.length})`}
            defaultOpen={open}
          >
            <div className="flex flex-col gap-1">
              {sorted.map((r, i) => (
                <ChartRow key={(r.id as string) || i} resource={r} highlighted={highlightedIds.has(r.id as string)} />
              ))}
            </div>
          </Disclosure>
        )
      })}

      {encounters.length > 0 && (
        <Disclosure title={`Encounters (${encounters.length})`} defaultOpen={false}>
          <div className="flex flex-col gap-1">
            {encounters.map((e, i) => (
              <EncounterRow
                key={(e.id as string) || i}
                resource={e}
                orgIndex={orgIndex}
              />
            ))}
          </div>
        </Disclosure>
      )}

      {chart.documents.length > 0 && (
        <Disclosure title={`Documents (${chart.documents.length})`} defaultOpen={false}>
          <div className="flex flex-col gap-1">
            {[...chart.documents].sort(sortByDateDesc).map((d, i) => (
              <DocumentRow key={(d.id as string) || i} resource={d} refIndex={refIndex} />
            ))}
          </div>
        </Disclosure>
      )}

      {chart.provenances.length > 0 && (
        <Disclosure title={`Provenance (${chart.provenances.length})`} defaultOpen={false}>
          <div className="flex flex-col gap-1">
            {[...chart.provenances].sort(sortByDateDesc).map((p, i) => (
              <ProvenanceRow key={(p.id as string) || i} resource={p} refIndex={refIndex} />
            ))}
          </div>
        </Disclosure>
      )}

      {chart.practitioners.length > 0 && (
        <Disclosure title={`Care Team (${chart.practitioners.length})`} defaultOpen={false}>
          <div className="flex flex-col gap-1">
            {chart.practitioners.map((p, i) => <PractitionerRow key={(p.id as string) || i} resource={p} />)}
          </div>
        </Disclosure>
      )}
    </div>
  )
}

function DocumentRow({ resource, refIndex }: { resource: FhirResource; refIndex: Map<string, string> }) {
  const name = resourceDisplayName(resource) || "Document"
  const date = shortDate(resourceDate(resource))
  const authors = resource.author as Array<Record<string, unknown>> | undefined
  const author = authors?.[0] ? resolveRef(authors[0], refIndex) : ""
  return (
    <div className="flex items-baseline gap-2 text-xs leading-snug py-0.5">
      <span className="flex-1 min-w-0 truncate text-foreground">{name}</span>
      {author && <span className="shrink-0 text-muted-foreground truncate max-w-[40%]">{author}</span>}
      {date && <span className="shrink-0 text-muted-foreground/70 tabular-nums">{date}</span>}
    </div>
  )
}

function ProvenanceRow({ resource, refIndex }: { resource: FhirResource; refIndex: Map<string, string> }) {
  const targets = provenanceTargets(resource)
  const primary = targets[0] ? labelForRef(targets[0], refIndex) : "—"
  const more = targets.length > 1 ? ` +${targets.length - 1}` : ""
  const agents = (resource.agent as Array<Record<string, unknown>> | undefined) ?? []
  let attester = ""
  for (const a of agents) {
    const t = a.type as { coding?: Array<{ code?: string }> } | undefined
    if (t?.coding?.[0]?.code === "attester") {
      attester = resolveRef(a.who, refIndex)
      break
    }
  }
  if (!attester && agents[0]) attester = resolveRef(agents[0].who, refIndex)
  const date = shortDate(resourceDate(resource))
  return (
    <div className="flex items-baseline gap-2 text-xs leading-snug py-0.5">
      <span className="flex-1 min-w-0 truncate text-foreground">
        {primary}{more}
      </span>
      {attester && <span className="shrink-0 text-muted-foreground truncate max-w-[40%]">{attester}</span>}
      {date && <span className="shrink-0 text-muted-foreground/70 tabular-nums">{date}</span>}
    </div>
  )
}

function buildRefIndex(chart: ChartContext | null): Map<string, string> {
  const map = new Map<string, string>()
  if (!chart) return map

  const sections: Array<[string, Array<Record<string, unknown>>]> = [
    ["Patient", [chart.patient]],
    ["Condition", chart.conditions],
    ["MedicationRequest", chart.medications],
    ["AllergyIntolerance", chart.allergies],
    ["Observation", chart.observations],
    ["Procedure", chart.procedures],
    ["FamilyMemberHistory", chart.family_history],
    ["Encounter", chart.encounters],
    ["DocumentReference", chart.documents],
  ]
  for (const [type, list] of sections) {
    for (const r of list) {
      const id = r?.id as string | undefined
      if (!id) continue
      const label = type === "Patient"
        ? humanName(r.name) || "Patient"
        : type === "DocumentReference"
        ? codeableDisplay(r.type) || "Document"
        : type === "Encounter"
        ? encounterType(r) || "Encounter"
        : resourceDisplayName(r) || type
      map.set(`${type}/${id}`, label)
    }
  }
  for (const p of chart.practitioners) {
    const id = p?.id as string | undefined
    if (id) map.set(`Practitioner/${id}`, humanName(p.name) || "Practitioner")
  }
  for (const o of chart.organizations) {
    const id = o?.id as string | undefined
    if (id) map.set(`Organization/${id}`, ((o as Record<string, unknown>).name as string) || "Organization")
  }
  return map
}

function labelForRef(ref: string, refIndex: Map<string, string>): string {
  const hit = refIndex.get(ref)
  if (hit) return hit
  const slash = ref.indexOf("/")
  if (slash > 0) return ref.slice(0, slash)
  return ref
}

const UUID_LIKE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function resolveRef(who: unknown, refIndex: Map<string, string>): string {
  if (!who || typeof who !== "object") return ""
  const w = who as { display?: string; reference?: string }
  if (w.reference) {
    const fromIndex = refIndex.get(w.reference)
    if (fromIndex) return fromIndex
  }
  if (w.display && !UUID_LIKE.test(w.display) && !w.display.includes("/")) return w.display
  if (w.reference) return labelForRef(w.reference, refIndex)
  return ""
}

function PersonHero({ patient }: { patient: Record<string, unknown> }) {
  const name = humanName(patient.name) || "Unknown"
  const sex = typeof patient.gender === "string" ? patient.gender[0]?.toUpperCase() : ""
  const age = ageFromBirth(patient.birthDate as string | undefined)
  const dob = shortDate(patient.birthDate as string | undefined)
  const mrn = mrnFromIdentifiers(patient.identifier)
  const address = addressLine(patient.address)
  const phone = telecomFor(patient.telecom, "phone")
  const email = telecomFor(patient.telecom, "email")

  const ident = [age && `${age}${sex || ""}`, dob && `DOB ${dob}`, mrn && `MRN ${mrn}`]
    .filter(Boolean)
    .join(" · ")
  const contact = [address, phone, email].filter(Boolean).join(" · ")

  return (
    <div className="space-y-1 pb-1">
      <div className="text-sm font-semibold">{name}</div>
      {ident && <div className="text-xs text-muted-foreground">{ident}</div>}
      {contact && <div className="text-xs text-muted-foreground">{contact}</div>}
    </div>
  )
}

function ChartRow({ resource, highlighted }: { resource: FhirResource; highlighted: boolean }) {
  const name = resourceDisplayName(resource) || "Untitled"
  const status = stateLabel(resource)
  const date = shortDate(resourceDate(resource))
  const muted = !highlighted && isInactive(resource)
  return (
    <div
      className={cn(
        "flex items-baseline gap-2 text-xs leading-snug py-0.5 px-2 -mx-2 rounded-sm",
        highlighted && "bg-destructive/10 py-1",
        muted && "text-muted-foreground",
      )}
    >
      <span className="flex-1 min-w-0 truncate text-foreground">{name}</span>
      {status && <span className="shrink-0 text-muted-foreground">{status}</span>}
      {date && <span className="shrink-0 text-muted-foreground/70 tabular-nums">{date}</span>}
    </div>
  )
}

function buildOrgIndex(organizations: Array<Record<string, unknown>>): Map<string, string> {
  const map = new Map<string, string>()
  for (const o of organizations) {
    const id = o.id as string | undefined
    const name = (o.name as string) || ""
    if (id && name) map.set(id, name)
  }
  return map
}

function EncounterRow({ resource, orgIndex }: { resource: FhirResource; orgIndex: Map<string, string> }) {
  const date = shortDate(resourceDate(resource))
  const type = encounterType(resource)
  const participants = (resource.participant as Array<Record<string, unknown>>) || []
  const who = participants.length > 0 ? referenceDisplay((participants[0] as Record<string, unknown>).individual) : ""
  const sp = resource.serviceProvider as { reference?: string; display?: string } | undefined
  const orgName = orgIndex.get((sp?.reference || "").replace(/^Organization\//, "")) || sp?.display || ""
  return (
    <div className="flex items-baseline gap-2 text-xs leading-snug py-0.5">
      <span className="shrink-0 text-muted-foreground tabular-nums w-20">{date}</span>
      <span className="flex-1 min-w-0 truncate text-foreground">{type || "Encounter"}</span>
      {orgName && <span className="shrink-0 text-muted-foreground truncate max-w-[40%]">{orgName}</span>}
      {who && <span className="shrink-0 text-muted-foreground truncate">{who}</span>}
    </div>
  )
}

function PractitionerRow({ resource }: { resource: FhirResource }) {
  const name = humanName(resource.name)
  const npi = npiFromIdentifiers(resource.identifier)
  return (
    <div className="flex items-baseline gap-2 text-xs leading-snug py-0.5">
      <span className="flex-1 min-w-0 truncate text-foreground">{name || "Practitioner"}</span>
      {npi && <span className="shrink-0 text-muted-foreground/70 tabular-nums">NPI {npi}</span>}
    </div>
  )
}

