"use client"

import { cn } from "@/lib/utils"
import { useAppStore } from "@/lib/store"
import type { ChartMatch } from "@/lib/types"
import { type FhirResource, type SummaryRow, codeableDisplay, stateLabel, summarize } from "@/lib/fhir-summary"

interface Props {
  proposed: FhirResource
  matches: ChartMatch[]
}

interface Delta {
  from: string
  to: string
}

export function ProposalConflictCallout({ proposed, matches }: Props) {
  const rightTab = useAppStore((s) => s.rightTab)
  const linked = rightTab === "chart"
  const real = matches.filter((m) => m.resource)
  if (real.length === 0) return null

  return (
    <div className="mb-4 rounded-md border border-border bg-muted/30 px-3 py-2.5">
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground mb-2.5">
        Conflicts with chart
      </div>
      <div className="flex flex-col gap-3.5">
        {real.map((m, i) => {
          const chart = m.resource as FhirResource
          const delta = computeDelta(proposed, chart)
          return (
            <div key={`${m.resource_id}-${i}`} className="flex flex-col gap-2">
              {delta && (
                <div className="text-xs font-mono text-foreground">
                  {delta.from} <span className="text-muted-foreground">→</span> {delta.to}
                </div>
              )}
              <ChartSummary resource={chart} highlighted={linked} />
            </div>
          )
        })}
      </div>
      <div className="mt-2.5 text-[11px] text-muted-foreground">
        On accept, this chart record will be retired and superseded.
      </div>
    </div>
  )
}

function ChartSummary({ resource, highlighted }: { resource: FhirResource; highlighted: boolean }) {
  const rows = summarize(resource)
  if (rows.length === 0) return null
  return (
    <div
      className={cn(
        "rounded-sm grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-xs",
        highlighted && "bg-destructive/10 px-2.5 py-2",
      )}
    >
      {rows.map((r, i) => (
        <FragmentRow key={i} label={r.label} value={r.value} />
      ))}
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

function computeDelta(proposed: FhirResource, chart: FhirResource): Delta | null {
  const type = proposed.resourceType
  let from: string
  let to: string
  if (type === "AllergyIntolerance") {
    from = codeableDisplay(chart.code)
    to = codeableDisplay(proposed.code)
  } else {
    from = stateLabel(chart)
    to = stateLabel(proposed)
  }
  if (!from || !to || from === to) return null
  return { from, to }
}
