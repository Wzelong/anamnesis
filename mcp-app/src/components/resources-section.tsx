import { TriangleAlert } from "lucide-react"
import type { Preset } from "../types"
import { IG_CATALOG, igById } from "../lib/ig-catalog"
import { cn } from "../lib/cn"

type Row = { rt: string; captures: string; required: boolean; enabled: boolean; defaultEnabled: boolean }

const CAPTURES: Record<string, string> = {
  Condition: "Problems, diagnoses",
  Observation: "Labs, vitals, social history",
  MedicationRequest: "Medications",
  Procedure: "Procedures, surgeries",
  AllergyIntolerance: "Allergies, intolerances",
  FamilyMemberHistory: "Family history",
}

export function ResourcesSection({
  preset,
  onChange,
}: {
  preset: Preset
  onChange: (resources: Preset["resources"]) => void
}) {
  const base = igById(preset.ig.base) ?? IG_CATALOG.base[0]
  const specialty = preset.ig.specialty ? igById(preset.ig.specialty) : undefined

  const rows: Row[] = Object.entries(base.resources).map(([rt, def]) => ({
    rt,
    captures: CAPTURES[rt] ?? "",
    required: (specialty?.resources[rt]?.inclusion ?? def.inclusion) === "required",
    enabled: preset.resources[rt]?.enabled ?? def.defaultEnabled,
    defaultEnabled: def.defaultEnabled,
  }))

  const onCount = rows.filter((r) => r.enabled).length
  const conflicts = rows.filter((r) => r.required && !r.enabled).map((r) => r.rt)

  function toggle(row: Row, next: boolean) {
    const resources = { ...preset.resources }
    if (next === row.defaultEnabled) delete resources[row.rt]
    else resources[row.rt] = { enabled: next }
    onChange(resources)
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="px-3 py-3 space-y-3 max-w-md">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">Resources</h2>
          <span className="text-xs text-muted-foreground tabular-nums">{onCount} of {rows.length} on</span>
        </div>
        <p className="text-xs text-muted-foreground">Which clinical facts the agent may extract from a note.</p>

        <div className="rounded-md border divide-y">
          {rows.map((r) => (
            <div key={r.rt} className={cn("flex items-center gap-3 px-3 py-2.5", !r.enabled && "opacity-55")}>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{r.rt}</div>
                <div className="text-[11px] text-muted-foreground truncate">{r.captures}</div>
              </div>
              <Switch checked={r.enabled} onChange={(v) => toggle(r, v)} />
            </div>
          ))}
        </div>

        {conflicts.length > 0 && (
          <div className="flex items-start gap-2 rounded-md border bg-muted/40 px-3 py-2 text-[11px]">
            <TriangleAlert className="size-3.5 text-muted-foreground shrink-0 mt-px" />
            <div className="text-muted-foreground">
              {conflicts.join(", ")} {conflicts.length > 1 ? "are" : "is"} required by mCODE. Off here means
              {conflicts.length > 1 ? " they" : " it"} won't be produced, so output won't meet mCODE's required set.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function Switch({ checked, onChange }: { checked: boolean; onChange: (next: boolean) => void }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative h-5 w-9 rounded-full transition-colors shrink-0 cursor-pointer",
        checked ? "bg-primary" : "bg-muted-foreground/30",
      )}
    >
      <span className={cn("absolute top-0.5 left-0.5 size-4 rounded-full bg-background transition-transform", checked && "translate-x-4")} />
    </button>
  )
}
