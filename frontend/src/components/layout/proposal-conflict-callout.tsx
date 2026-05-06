"use client"

import { useState } from "react"
import { ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"
import { useAppStore } from "@/lib/store"
import type { ChartMatch } from "@/lib/types"
import { type FhirResource, type SummaryRow, stateLabel, summarize } from "@/lib/fhir-summary"

interface Props {
  proposed: FhirResource
  matches: ChartMatch[]
}

export function ProposalConflictCallout({ proposed, matches }: Props) {
  const rightTab = useAppStore((s) => s.rightTab)
  const linked = rightTab === "chart"
  const real = matches.filter((m) => m.resource)
  if (real.length === 0) return null

  const toLabel = stateLabel(proposed)
  const firstChart = real[0].resource as FhirResource
  const fromLabel = stateLabel(firstChart)
  const hasDelta = fromLabel && toLabel && fromLabel !== toLabel

  return (
    <div className="mb-4 rounded-md border border-border bg-muted/30 px-3 py-2.5">
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mb-2.5">
        Conflicts with chart
      </div>
      {hasDelta && (
        <div className="text-xs font-mono text-foreground mb-2.5">
          {fromLabel} <span className="text-muted-foreground mx-1">→</span> {toLabel}
        </div>
      )}
      <div className={cn("grid gap-3", "grid-cols-1 sm:grid-cols-2")}>
        <div className="flex flex-col gap-0">
          {real.length === 1 ? (
            <SideCard label="Chart" rows={summarize(firstChart)} highlighted={linked} />
          ) : (
            <ChartStack matches={real} highlighted={linked} />
          )}
        </div>
        <SideCard label="Proposed" rows={summarize(proposed)} highlighted={false} />
      </div>
      <div className="mt-2.5 text-[11px] text-muted-foreground">
        On accept, {real.length > 1 ? "these chart records" : "this chart record"} will be retired and superseded.
      </div>
    </div>
  )
}

function ChartStack({ matches, highlighted }: { matches: ChartMatch[]; highlighted: boolean }) {
  const [expandedSet, setExpandedSet] = useState<Set<number>>(() => new Set([0]))

  const toggle = (i: number) => {
    setExpandedSet((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })
  }

  return (
    <div className={cn("rounded-sm border border-border overflow-hidden", highlighted ? "bg-destructive/10" : "bg-muted/50")}>
      {matches.map((m, i) => {
        const chart = m.resource as FhirResource
        const rows = summarize(chart)
        const expanded = expandedSet.has(i)
        return (
          <div
            key={`${m.resource_id}-${i}`}
            className={cn("px-2.5 py-2", i > 0 && "border-t border-border")}
          >
            <div
              className="flex items-center gap-1.5 cursor-pointer select-none"
              onClick={() => toggle(i)}
            >
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
                {rows.map((r, j) => (
                  <FragmentRow key={j} label={r.label} value={r.value} />
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function SideCard({ label, rows, highlighted }: { label: string; rows: SummaryRow[]; highlighted: boolean }) {
  if (rows.length === 0) return null
  return (
    <div className={cn("rounded-sm border border-border px-2.5 py-2", highlighted ? "bg-destructive/10" : "bg-muted/50")}>
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mb-1.5">{label}</div>
      <div className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-xs">
        {rows.map((r, i) => (
          <FragmentRow key={i} label={r.label} value={r.value} />
        ))}
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
