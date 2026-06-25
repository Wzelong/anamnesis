import { Lock, TriangleAlert } from "lucide-react"
import type { IgDef, Preset } from "../types"
import { BASE_IG, IG_CATALOG, igById } from "../lib/ig-catalog"
import { cn } from "../lib/cn"

export function IgSection({
  preset,
  onChange,
}: {
  preset: Preset
  onChange: (specialtyId: string | null) => void
}) {
  const base = igById(preset.ig.base) ?? IG_CATALOG.base[0]
  const specialtyId = preset.ig.specialty ?? null
  const specialty = specialtyId ? igById(specialtyId) : undefined

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="px-3 py-3 space-y-5 max-w-md">
      <div className="space-y-0.5">
        <h2 className="text-base font-semibold">FHIR IG</h2>
        <p className="text-xs text-muted-foreground">The implementation guide the pipeline conforms to.</p>
      </div>
      <section className="space-y-2">
        <Label>Base</Label>
        <div className="flex items-center gap-2.5 rounded-md border bg-muted/40 px-3 py-2.5">
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium truncate">{base.title}</div>
            <div className="text-[11px] text-muted-foreground">mCODE's substrate. Not configurable in v1.</div>
          </div>
          <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-foreground border rounded-full px-2 py-0.5 shrink-0">
            <Lock className="size-3" /> Pinned
          </span>
        </div>
      </section>

      <section className="space-y-2">
        <Label>Specialty overlay</Label>
        <div className="rounded-md border divide-y">
          <SpecialtyRow selected={specialtyId === null} title="None" subtitle="US Core only" onClick={() => onChange(null)} />
          {IG_CATALOG.specialties.map((s) => (
            <SpecialtyRow
              key={s.id}
              selected={specialtyId === s.id}
              title={s.title}
              subtitle={`layers on ${(s.dependsOn ?? [BASE_IG]).join(", ")}`}
              onClick={() => onChange(s.id)}
            />
          ))}
        </div>
      </section>

      {specialty && <Effect base={base} specialty={specialty} />}
      </div>
    </div>
  )
}

function Effect({ base, specialty }: { base: IgDef; specialty: IgDef }) {
  const rows = Object.entries(specialty.resources)
    .map(([rt, sp]) => {
      const b = base.resources[rt]
      const inclusion = b && b.inclusion !== sp.inclusion ? `${b.inclusion} → ${sp.inclusion}` : null
      const added = sp.profiles.filter((p) => !(b?.profiles ?? []).includes(p))
      return { rt, inclusion, added }
    })
    .filter((r) => r.inclusion || r.added.length)

  return (
    <section className="space-y-2">
      <Label>Effect on this preset</Label>
      <div className="rounded-md border divide-y">
        {rows.map((r) => (
          <div key={r.rt} className="flex items-center gap-2 px-3 py-2 text-xs">
            <span className="font-medium w-28 shrink-0 truncate">{r.rt}</span>
            {r.inclusion && <span className="text-muted-foreground">{r.inclusion}</span>}
            {r.added.length > 0 && (
              <span className="text-muted-foreground ml-auto shrink-0" title={r.added.map(profileLabel).join("\n")}>
                +{r.added.length} profile{r.added.length > 1 ? "s" : ""}
              </span>
            )}
          </div>
        ))}
      </div>
      {specialty.gaps?.length ? (
        <div className="flex items-start gap-2 rounded-md border bg-muted/40 px-3 py-2 text-[11px]">
          <TriangleAlert className="size-3.5 text-muted-foreground shrink-0 mt-px" />
          <div className="space-y-0.5 min-w-0">
            <div className="font-medium text-foreground">Coding gaps</div>
            <div className="text-muted-foreground">{specialty.gaps.join(", ")} — no retriever yet.</div>
          </div>
        </div>
      ) : null}
    </section>
  )
}

function SpecialtyRow({
  selected,
  title,
  subtitle,
  onClick,
}: {
  selected: boolean
  title: string
  subtitle: string
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full flex items-center gap-2.5 px-3 py-2.5 text-left cursor-pointer transition-colors hover:bg-muted/50",
        selected && "bg-muted/40",
      )}
    >
      <span className={cn("size-4 rounded-full border flex items-center justify-center shrink-0", selected ? "border-primary" : "border-muted-foreground/40")}>
        {selected && <span className="size-2 rounded-full bg-primary" />}
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium truncate">{title}</div>
        <div className="text-[11px] text-muted-foreground truncate">{subtitle}</div>
      </div>
    </button>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return <h2 className="text-xs font-medium text-muted-foreground">{children}</h2>
}

function profileLabel(url: string): string {
  const slug = url.split("/").pop() ?? url
  return slug.replace(/^(mcode|us-core)-/, "").replace(/-/g, " ")
}
