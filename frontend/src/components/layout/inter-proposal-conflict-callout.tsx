"use client"

import { useRouter, useParams } from "next/navigation"
import { cn } from "@/lib/utils"
import { useAppStore } from "@/lib/store"
import type { Proposal, ProposalDetail } from "@/lib/types"
import { type FhirResource, stateLabel, summarize, type SummaryRow } from "@/lib/fhir-summary"

interface Props {
  current: ProposalDetail
}

export function InterProposalConflictCallout({ current }: Props) {
  const router = useRouter()
  const params = useParams<{ runId: string }>()
  const proposals = useAppStore((s) => s.proposals)

  const siblings = proposals.filter(
    (p) => p.conflict_group_id === current.conflict_group_id && p.id !== current.id,
  )
  if (siblings.length === 0) return null

  const currentState = stateLabel(current.resource as FhirResource)

  return (
    <div className="mb-4 rounded-md border border-border bg-muted/30 px-3 py-2.5">
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
              <div className={cn("grid gap-3", "grid-cols-1 sm:grid-cols-2")}>
                <SideCard
                  label="This proposal"
                  rows={summarize(current.resource as FhirResource)}
                />
                <SideCard
                  label="Conflicting proposal"
                  rows={siblingRows(sib)}
                  onClick={() => params?.runId && router.push(`/${params.runId}/${sib.id}`)}
                />
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
  const flags = p.flags || []
  for (const f of flags) {
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
