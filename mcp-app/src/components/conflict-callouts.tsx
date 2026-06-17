import { useState } from "react"
import { ChevronDown } from "lucide-react"
import { cn } from "../lib/cn"
import { type FhirResource, type SummaryRow, stateLabel, summarize } from "../lib/fhir-summary"
import type { ChartMatch, Proposal } from "../types"

// --- Conflict with the existing chart (Chart → Proposed) -----------------

export function ProposalConflictCallout({
  proposed,
  matches,
  mode,
}: {
  proposed: FhirResource
  matches: ChartMatch[]
  mode: "UPDATING" | "CONFLICTING"
}) {
  const real = matches.filter((m) => m.resource)
  if (real.length === 0) return null

  const toLabel = stateLabel(proposed)
  const firstChart = real[0].resource as FhirResource
  const fromLabel = stateLabel(firstChart)
  const hasDelta = fromLabel && toLabel && fromLabel !== toLabel
  const plural = real.length > 1

  const heading = mode === "UPDATING" ? "Updates a chart record" : "Contradicts the chart"
  const footer = mode === "UPDATING"
    ? `On accept, the existing ${plural ? "records are" : "record is"} updated in place — the prior version is retained in history.`
    : `On accept, this finding is added alongside the existing ${plural ? "records" : "record"} and flagged for reconciliation. The existing ${plural ? "records are" : "record is"} not changed.`

  return (
    <div className={cn(
      "rounded-md border px-3 py-2.5",
      mode === "CONFLICTING" ? "border-destructive/30 bg-destructive/5" : "border-border bg-muted/30",
    )}>
      <div className={cn(
        "text-[10px] font-medium uppercase tracking-wider mb-2.5",
        mode === "CONFLICTING" ? "text-destructive" : "text-muted-foreground",
      )}>
        {heading}
      </div>
      {hasDelta && (
        <div className="text-xs font-mono text-foreground mb-2.5">
          {fromLabel} <span className="text-muted-foreground mx-1">→</span> {toLabel}
        </div>
      )}
      <div className="grid gap-3 grid-cols-1 sm:grid-cols-2">
        <div className="flex flex-col gap-0">
          {real.length === 1 ? (
            <SideCard label="Chart" rows={summarize(firstChart)} />
          ) : (
            <ChartStack matches={real} />
          )}
        </div>
        <SideCard label="Proposed" rows={summarize(proposed)} />
      </div>
      <div className="mt-2.5 text-[11px] text-muted-foreground">{footer}</div>
    </div>
  )
}

function ChartStack({ matches }: { matches: ChartMatch[] }) {
  const [expandedSet, setExpandedSet] = useState<Set<number>>(() => new Set([0]))
  const toggle = (i: number) =>
    setExpandedSet((prev) => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })

  return (
    <div className="rounded-sm border border-border overflow-hidden bg-muted/50">
      {matches.map((m, i) => {
        const chart = m.resource as FhirResource
        const rows = summarize(chart)
        const expanded = expandedSet.has(i)
        return (
          <div key={`${m.resource_id}-${i}`} className={cn("px-2.5 py-2", i > 0 && "border-t border-border")}>
            <div className="flex items-center gap-1.5 cursor-pointer select-none" onClick={() => toggle(i)}>
              <ChevronDown className={cn("size-3 text-muted-foreground transition-transform", !expanded && "-rotate-90")} />
              <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground flex-1">
                Chart ({i + 1})
              </span>
              {!expanded && rows.length > 0 && (
                <span className="text-[10px] text-muted-foreground truncate max-w-[120px]">{rows[0].value}</span>
              )}
            </div>
            {expanded && rows.length > 0 && (
              <div className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-xs mt-1.5">
                {rows.map((r, j) => <FragmentRow key={j} label={r.label} value={r.value} />)}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// --- Conflict with another proposal in the run ---------------------------

export function InterProposalConflictCallout({
  current,
  proposals,
  onOpenSibling,
}: {
  current: Proposal
  proposals: Proposal[]
  onOpenSibling: (id: string) => void
}) {
  const siblings = proposals.filter(
    (p) => p.conflict_group_id && p.conflict_group_id === current.conflict_group_id && p.id !== current.id,
  )
  if (siblings.length === 0) return null

  const currentState = stateLabel(current.resource as FhirResource)

  return (
    <div className="rounded-md border border-border bg-muted/30 px-3 py-2.5">
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mb-2.5">
        Conflicts with another proposal
      </div>
      <div className="flex flex-col gap-3.5">
        {siblings.map((sib) => {
          const sibState = inferState(sib)
          const hasDelta = currentState && sibState && currentState !== sibState
          return (
            <div key={sib.id} className="flex flex-col gap-2.5">
              {hasDelta && (
                <div className="text-xs font-mono text-foreground">
                  {currentState} <span className="text-muted-foreground mx-1">vs</span> {sibState}
                </div>
              )}
              <div className="grid gap-3 grid-cols-1 sm:grid-cols-2">
                <SideCard label="This proposal" rows={summarize(current.resource as FhirResource)} />
                <SideCard label="Conflicting proposal" rows={siblingRows(sib)} onClick={() => onOpenSibling(sib.id)} />
              </div>
            </div>
          )
        })}
      </div>
      <div className="mt-2.5 text-[11px] text-muted-foreground">
        Accepting this proposal will automatically reject the conflicting one.
      </div>
    </div>
  )
}

function inferState(p: Proposal): string {
  for (const f of p.flags || []) {
    if (f.startsWith("Inter-note conflict:")) continue
    if (f.toLowerCase().includes("stopped") || f.toLowerCase().includes("discontinued")) return "stopped"
  }
  return p.classification === "CONFLICTING" ? "stopped" : "active"
}

function siblingRows(p: Proposal): SummaryRow[] {
  return [
    { label: "Medication", value: p.display_label },
    { label: "Classification", value: p.classification === "CONFLICTING" ? "Conflicts with chart" : p.classification === "UPDATING" ? "Updates chart" : "New" },
    { label: "Status", value: p.status },
  ]
}

// --- shared ---------------------------------------------------------------

function SideCard({ label, rows, onClick }: { label: string; rows: SummaryRow[]; onClick?: () => void }) {
  if (rows.length === 0) return null
  return (
    <div
      className={cn("rounded-sm border border-border px-2.5 py-2 bg-muted/50", onClick && "cursor-pointer hover:bg-muted/80 transition-colors")}
      onClick={onClick}
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">{label}</span>
        {onClick && <span className="text-[10px] text-muted-foreground">View →</span>}
      </div>
      <div className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-xs">
        {rows.map((r, i) => <FragmentRow key={i} label={r.label} value={r.value} />)}
      </div>
    </div>
  )
}

function FragmentRow({ label, value }: SummaryRow) {
  return (
    <>
      <div className="text-muted-foreground">{label}</div>
      <div className="text-foreground break-words">{value}</div>
    </>
  )
}
