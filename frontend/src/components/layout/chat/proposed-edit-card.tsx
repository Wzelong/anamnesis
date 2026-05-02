"use client"

import { useMemo } from "react"
import { Check, RotateCcw, Sparkle } from "lucide-react"
import { cn } from "@/lib/utils"
import { useAppStore } from "@/lib/store"
import { type FhirResource, summarize } from "@/lib/fhir-summary"
import type { ProposedEdit } from "@/lib/types"

interface Props {
  messageId: string
  edit: ProposedEdit
  onRevise: () => void
}

export function ProposedEditCard({ messageId, edit, onRevise }: Props) {
  const proposals = useAppStore((s) => s.proposals)
  const selectedDetail = useAppStore((s) => s.selectedDetail)
  const applyProposedEdit = useAppStore((s) => s.applyProposedEdit)

  const baseResource = useMemo<FhirResource | null>(() => {
    if (selectedDetail?.id === edit.proposalId) {
      return selectedDetail.resource as FhirResource
    }
    const p = proposals.find((x) => x.id === edit.proposalId)
    return (p as unknown as { resource?: FhirResource })?.resource ?? null
  }, [edit.proposalId, proposals, selectedDetail])

  const diff = useMemo(() => {
    const next = summarize(edit.resource as FhirResource)
    if (!baseResource) return next.map((r) => ({ label: r.label, from: "—", to: r.value }))
    const prev = summarize(baseResource)
    const prevByLabel = new Map(prev.map((r) => [r.label, r.value]))
    const seen = new Set<string>()
    const rows: { label: string; from: string; to: string }[] = []
    for (const r of next) {
      seen.add(r.label)
      const from = prevByLabel.get(r.label) ?? "—"
      if (from !== r.value) rows.push({ label: r.label, from, to: r.value })
    }
    for (const r of prev) {
      if (!seen.has(r.label)) rows.push({ label: r.label, from: r.value, to: "—" })
    }
    return rows
  }, [edit.resource, baseResource])

  const status = edit.status
  const applied = status === "applied"
  const dismissed = status === "dismissed"

  return (
    <div
      className={cn(
        "rounded-lg border p-3 space-y-2 max-w-[85%]",
        applied && "border-emerald-500/30 bg-emerald-500/5",
        dismissed && "border-border/50 bg-muted/30 opacity-60",
        !applied && !dismissed && "border-border",
      )}
    >
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Sparkle className="size-3" />
        <span>Proposed edit</span>
      </div>

      {edit.rationale && (
        <p className="text-xs text-muted-foreground">{edit.rationale}</p>
      )}

      {diff.length > 0 ? (
        <div className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-xs font-mono">
          {diff.map((row) => (
            <div key={row.label} className="contents">
              <div className="text-muted-foreground">{row.label}</div>
              <div className="min-w-0 truncate">
                <span className="text-muted-foreground line-through">{row.from}</span>
                <span className="text-muted-foreground"> → </span>
                <span className="text-foreground">{row.to}</span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground italic">No field changes</p>
      )}

      {!applied && !dismissed && (
        <div className="flex items-center gap-1.5 pt-1">
          <button
            type="button"
            onClick={() => applyProposedEdit(messageId)}
            className="flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs hover:bg-muted cursor-pointer"
          >
            <Check className="size-3" />
            Apply
          </button>
          <button
            type="button"
            onClick={onRevise}
            className="flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted cursor-pointer"
          >
            <RotateCcw className="size-3" />
            Revise
          </button>
        </div>
      )}

      {applied && (
        <div className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
          <Check className="size-3" />
          Applied
        </div>
      )}
      {dismissed && <div className="text-xs text-muted-foreground">Dismissed</div>}
    </div>
  )
}
