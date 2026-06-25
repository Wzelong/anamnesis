import { useEffect, useRef, useState } from "react"
import { ChevronDown, ExternalLink, Lock, TriangleAlert } from "lucide-react"
import type { Preset } from "../types"
import {
  BASE_IG,
  IG_CATALOG,
  codingSystemsFor,
  fixedGroupsFor,
  igById,
  inclusionFor,
  profileGroupsFor,
  profileLabel,
} from "../lib/ig-catalog"
import { shortLabel } from "../lib/systems"
import { RT_LABEL } from "../lib/proposal-meta"
import { cn } from "../lib/cn"
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip"

const CAPTURES: Record<string, string> = {
  Condition: "Problems, diagnoses",
  Observation: "Labs, vitals, social history",
  MedicationRequest: "Medications",
  Procedure: "Procedures, surgeries",
  AllergyIntolerance: "Allergies, intolerances",
  FamilyMemberHistory: "Family history",
}

export function ConformanceSection({
  preset,
  onPatch,
}: {
  preset: Preset
  onPatch: (patch: Partial<Preset>) => void
}) {
  const base = igById(preset.ig.base) ?? IG_CATALOG.base[0]
  const specialtyId = preset.ig.specialty ?? null
  const types = Object.keys(base.resources)
  const [sel, setSel] = useState<string>(types[0] ?? "")
  const rt = types.includes(sel) ? sel : (types[0] ?? "")

  const required = inclusionFor(preset, rt) === "required"
  const enabledOf = (t: string) =>
    inclusionFor(preset, t) === "required" || (preset.resources[t]?.enabled ?? base.resources[t].defaultEnabled)
  const enabled = enabledOf(rt)

  const setSpecialty = (id: string | null) =>
    onPatch({ ig: { base: preset.ig.base || BASE_IG, specialty: id } })

  const toggle = (next: boolean) => {
    const resources = { ...preset.resources }
    if (next === base.resources[rt].defaultEnabled) delete resources[rt]
    else resources[rt] = { enabled: next }
    onPatch({ resources })
  }

  return (
    <div className="flex-1 min-h-0 flex">
      <section className="w-1/2 shrink-0 border-r flex flex-col min-h-0">
        <header className="h-10 shrink-0 border-b px-3 flex items-center min-w-0">
          <h2 className="text-sm font-semibold">Implementation Guide</h2>
        </header>

        <div className="flex-1 min-h-0 overflow-y-auto px-3 py-3 space-y-4">
          <section className="space-y-2">
            <Label>Base</Label>
            <div className="flex items-center gap-2.5 rounded-md border bg-muted/40 px-3 py-2">
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{base.title}</div>
                <div className="text-[11px] text-muted-foreground">Base substrate. Not configurable in v1.</div>
              </div>
              <Lock className="size-3 text-muted-foreground shrink-0" />
            </div>
          </section>

          <section className="space-y-2">
            <Label>Specialty overlay</Label>
            <div className="rounded-md border divide-y">
              <SpecialtyRow selected={specialtyId === null} title="None" subtitle="US Core only" onClick={() => setSpecialty(null)} />
              {IG_CATALOG.specialties.map((s) => (
                <SpecialtyRow
                  key={s.id}
                  selected={specialtyId === s.id}
                  title={s.title}
                  subtitle={`layers on ${(s.dependsOn ?? [BASE_IG]).join(", ")}`}
                  onClick={() => setSpecialty(s.id)}
                />
              ))}
            </div>
            {specialtyId && igById(specialtyId)?.gaps?.length ? (
              <div className="flex items-start gap-2 rounded-md border bg-muted/40 px-3 py-2 text-[11px]">
                <TriangleAlert className="size-3.5 text-muted-foreground shrink-0 mt-px" />
                <div className="space-y-0.5 min-w-0">
                  <div className="font-medium text-foreground">Coding gaps</div>
                  <div className="text-muted-foreground">{igById(specialtyId)!.gaps!.join(", ")} — no retriever yet.</div>
                </div>
              </div>
            ) : null}
          </section>
        </div>
      </section>

      <ProfileDetail
        preset={preset}
        rt={rt}
        types={types}
        enabledOf={enabledOf}
        onSelect={setSel}
        enabled={enabled}
        required={required}
        onToggle={toggle}
      />
    </div>
  )
}

function ProfileDetail({
  preset,
  rt,
  types,
  enabledOf,
  onSelect,
  enabled,
  required,
  onToggle,
}: {
  preset: Preset
  rt: string
  types: string[]
  enabledOf: (rt: string) => boolean
  onSelect: (rt: string) => void
  enabled: boolean
  required: boolean
  onToggle: (next: boolean) => void
}) {
  const inclusion = inclusionFor(preset, rt)
  const profileGroups = profileGroupsFor(preset, rt)
  const systems = codingSystemsFor(preset, rt)
  const fixedGroups = fixedGroupsFor(preset, rt)
  const igTitle = preset.ig.specialty ? igById(preset.ig.specialty)?.title : undefined

  return (
    <section className="flex-1 min-w-0 flex flex-col min-h-0">
      <header className="h-10 shrink-0 border-b px-3 flex items-center gap-2 min-w-0">
        <ResourceSelect types={types} active={rt} enabledOf={enabledOf} onSelect={onSelect} />
        <Pill>{inclusion}</Pill>
        <div className="flex-1" />
        <Switch
          checked={enabled}
          disabled={required}
          onChange={onToggle}
          title={required ? `Required by ${igTitle ?? "the IG"}` : enabled ? "Extracted" : "Not extracted"}
        />
      </header>

      <div className="flex-1 min-h-0 overflow-y-auto px-3 py-3 space-y-4">
        <p className="text-xs text-muted-foreground">{CAPTURES[rt] ?? ""}</p>

        <Group title="Profiles">
          {profileGroups.length === 0 ? (
            <Note>No profile constraints — plain {RT_LABEL[rt] ?? rt} resource.</Note>
          ) : (
            profileGroups.map((g) => (
              <div key={g.title} className="space-y-1">
                <GroupSub>{g.title}</GroupSub>
                <div className="rounded-md border divide-y">
                  {g.profiles.map((url) => (
                    <a
                      key={url}
                      href={url}
                      target="_blank"
                      rel="noreferrer"
                      className="group flex items-center gap-2 px-3 py-1.5 hover:bg-muted/40 transition-colors"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="text-sm capitalize truncate">{profileLabel(url)}</div>
                        <div className="text-[11px] text-muted-foreground truncate font-mono">{url}</div>
                      </div>
                      <ExternalLink className="size-3 text-muted-foreground shrink-0 opacity-0 group-hover:opacity-100" />
                    </a>
                  ))}
                </div>
              </div>
            ))
          )}
        </Group>

        <Group title="Coding systems">
          {systems.length === 0 ? (
            <Note>None bound.</Note>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {systems.map((s) => (
                <span key={s} className="rounded-md border bg-muted/40 px-2 py-0.5 text-[11px] font-medium">
                  {shortLabel(s)}
                </span>
              ))}
            </div>
          )}
        </Group>

        {fixedGroups.length > 0 && (
          <Group title="Fixed codes">
            {fixedGroups.map((g) => (
              <div key={g.title} className="space-y-1">
                <GroupSub>{g.title}</GroupSub>
                <div className="rounded-md border divide-y">
                  {g.codes.map((c) => (
                    <div key={c.system + c.code} className="flex items-center gap-2 px-3 py-1.5">
                      <div className="flex-1 min-w-0">
                        <div className="text-sm truncate">{c.display || c.code}</div>
                        <div className="text-[11px] text-muted-foreground truncate">
                          {shortLabel(c.system)} <span className="font-mono">{c.code}</span>
                        </div>
                      </div>
                      <Lock className="size-3 text-muted-foreground shrink-0" />
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </Group>
        )}
      </div>
    </section>
  )
}

function ResourceSelect({
  types,
  active,
  enabledOf,
  onSelect,
}: {
  types: string[]
  active: string
  enabledOf: (rt: string) => boolean
  onSelect: (rt: string) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])

  return (
    <div className="relative min-w-0" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 text-sm font-semibold cursor-pointer hover:opacity-80 outline-none max-w-full"
      >
        <span className="truncate max-w-[140px]">{RT_LABEL[active] ?? active ?? "Resource"}</span>
        <ChevronDown className="size-3.5 text-muted-foreground shrink-0" />
      </button>

      {open && (
        <div className="absolute left-0 top-8 z-20 w-56 rounded-md border bg-card text-card-foreground shadow-md p-1">
          {types.map((rt) => {
            const enabled = enabledOf(rt)
            return (
              <div
                key={rt}
                onClick={() => { onSelect(rt); setOpen(false) }}
                className={cn(
                  "flex items-center gap-2 rounded px-2 py-1.5 text-xs cursor-pointer",
                  active === rt ? "bg-muted font-medium" : "hover:bg-accent",
                  !enabled && "text-muted-foreground",
                )}
              >
                <span className="truncate flex-1 text-left">{RT_LABEL[rt] ?? rt}</span>
                <span className={cn(
                  "shrink-0 text-[10px] font-medium uppercase tracking-wide",
                  enabled ? "text-primary" : "text-muted-foreground/60",
                )}>
                  {enabled ? "On" : "Off"}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
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
        "w-full flex items-center gap-2.5 px-3 py-2 text-left cursor-pointer transition-colors hover:bg-muted/50",
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

function Switch({
  checked,
  disabled,
  onChange,
  title,
}: {
  checked: boolean
  disabled?: boolean
  onChange: (next: boolean) => void
  title?: string
}) {
  const btn = (
    <button
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative h-5 w-9 rounded-full transition-colors shrink-0",
        checked ? "bg-primary" : "bg-muted-foreground/30",
        disabled ? "opacity-60 cursor-not-allowed" : "cursor-pointer",
      )}
    >
      <span className={cn("absolute top-0.5 left-0.5 size-4 rounded-full bg-background transition-transform", checked && "translate-x-4")} />
    </button>
  )
  if (!title) return btn
  return (
    <Tooltip>
      <TooltipTrigger asChild>{btn}</TooltipTrigger>
      <TooltipContent side="bottom" sideOffset={4}>{title}</TooltipContent>
    </Tooltip>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return <h2 className="text-xs font-medium text-muted-foreground">{children}</h2>
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-1.5">
      <Label>{title}</Label>
      {children}
    </section>
  )
}

function GroupSub({ children }: { children: React.ReactNode }) {
  return <div className="text-[11px] font-medium text-muted-foreground/80 px-0.5">{children}</div>
}

function Pill({ children }: { children: React.ReactNode }) {
  return (
    <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
      {children}
    </span>
  )
}

function Note({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] text-muted-foreground">{children}</p>
}
