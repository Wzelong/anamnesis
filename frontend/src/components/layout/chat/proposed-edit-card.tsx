"use client"

import { useMemo, useState } from "react"
import { Check, RotateCcw } from "lucide-react"
import { cn } from "@/lib/utils"
import { useAppStore } from "@/lib/store"
import type { FhirResource } from "@/lib/fhir-summary"
import type { ProposedEdit } from "@/lib/types"

type Change =
  | { kind: "added"; path: string; to: string }
  | { kind: "removed"; path: string; from: string }
  | { kind: "changed"; path: string; from: string; to: string }

const SHORT_SYSTEM: Array<[string, string]> = [
  ["snomed", "SNOMED"],
  ["icd-10", "ICD-10"],
  ["icd10", "ICD-10"],
  ["rxnorm", "RxNorm"],
  ["loinc", "LOINC"],
  ["condition-clinical", "clinical"],
  ["condition-ver-status", "verification"],
  ["allergyintolerance-clinical", "clinical"],
  ["allergyintolerance-verification", "verification"],
]

function shortSystem(system: string): string {
  const lower = system.toLowerCase()
  for (const [needle, label] of SHORT_SYSTEM) {
    if (lower.includes(needle)) return label
  }
  return system.split("/").pop() || system
}

function fmtCoding(c: Record<string, unknown>): string {
  const sys = typeof c.system === "string" ? shortSystem(c.system) : ""
  const code = typeof c.code === "string" ? c.code : ""
  const display = typeof c.display === "string" ? c.display : ""
  const head = [sys, code].filter(Boolean).join(":")
  return display ? (head ? `${head} (${display})` : display) : head
}

function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return "—"
  if (typeof v === "string") return v
  if (typeof v === "number" || typeof v === "boolean") return String(v)
  if (Array.isArray(v)) return v.length === 0 ? "[]" : `[${v.length}]`
  if (typeof v === "object") {
    const obj = v as Record<string, unknown>
    if (typeof obj.system === "string" || typeof obj.code === "string") return fmtCoding(obj)
    if (typeof obj.text === "string") return obj.text
    if (typeof obj.display === "string") return obj.display
    if (typeof obj.reference === "string") return obj.reference
    if (typeof obj.value === "number" || typeof obj.value === "string") {
      const unit = typeof obj.unit === "string" ? ` ${obj.unit}` : ""
      return `${obj.value}${unit}`
    }
    return "{…}"
  }
  return String(v)
}

const SKIP_PATH_KEYS = new Set(["resourceType", "meta", "id", "subject"])

function diffNode(prev: unknown, next: unknown, path: string, out: Change[]): void {
  if (Object.is(prev, next)) return

  if (prev === undefined && next !== undefined) {
    if (Array.isArray(next)) {
      next.forEach((v, i) => diffNode(undefined, v, `${path}[${i}]`, out))
      return
    }
    if (next && typeof next === "object" && !Array.isArray(next)) {
      for (const [k, v] of Object.entries(next as Record<string, unknown>)) {
        diffNode(undefined, v, path ? `${path}.${k}` : k, out)
      }
      return
    }
    out.push({ kind: "added", path, to: fmtValue(next) })
    return
  }

  if (next === undefined && prev !== undefined) {
    if (Array.isArray(prev)) {
      prev.forEach((v, i) => diffNode(v, undefined, `${path}[${i}]`, out))
      return
    }
    if (prev && typeof prev === "object" && !Array.isArray(prev)) {
      for (const [k, v] of Object.entries(prev as Record<string, unknown>)) {
        diffNode(v, undefined, path ? `${path}.${k}` : k, out)
      }
      return
    }
    out.push({ kind: "removed", path, from: fmtValue(prev) })
    return
  }

  if (Array.isArray(prev) && Array.isArray(next)) {
    const max = Math.max(prev.length, next.length)
    for (let i = 0; i < max; i++) {
      diffNode(prev[i], next[i], `${path}[${i}]`, out)
    }
    return
  }

  if (prev && next && typeof prev === "object" && typeof next === "object" && !Array.isArray(prev) && !Array.isArray(next)) {
    const a = prev as Record<string, unknown>
    const b = next as Record<string, unknown>
    const keys = new Set([...Object.keys(a), ...Object.keys(b)])
    for (const k of keys) {
      if (path === "" && SKIP_PATH_KEYS.has(k)) continue
      const childPath = path ? `${path}.${k}` : k
      diffNode(a[k], b[k], childPath, out)
    }
    return
  }

  out.push({ kind: "changed", path, from: fmtValue(prev), to: fmtValue(next) })
}

function diffResources(prev: unknown, next: unknown): Change[] {
  const out: Change[] = []
  diffNode(prev ?? {}, next ?? {}, "", out)
  return out
}

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

  const changes = useMemo(
    () => diffResources(baseResource ?? {}, edit.resource),
    [edit.resource, baseResource],
  )

  const status = edit.status
  const applied = status === "applied"
  const dismissed = status === "dismissed"

  const COLLAPSED_LIMIT = 4
  const [expanded, setExpanded] = useState(false)
  const overflow = changes.length > COLLAPSED_LIMIT
  const visible = expanded || !overflow ? changes : changes.slice(0, COLLAPSED_LIMIT)
  const hidden = changes.length - COLLAPSED_LIMIT

  return (
    <div
      className={cn(
        "rounded-lg border p-3 space-y-2 max-w-[85%]",
        applied && "border-emerald-500/30 bg-emerald-500/5",
        dismissed && "border-border/50 bg-muted/30 opacity-60",
        !applied && !dismissed && "border-border",
      )}
    >
      <div className="text-xs text-muted-foreground">Proposed edit</div>

      {edit.rationale && (
        <p className="text-xs text-muted-foreground">{edit.rationale}</p>
      )}

      {changes.length > 0 ? (
        <div className="space-y-1.5">
          <div className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-xs font-mono">
            {visible.map((c, i) => (
              <div key={`${c.path}-${i}`} className="contents">
                <div className="text-muted-foreground truncate">{c.path}</div>
                <div className="min-w-0 break-words">
                  {c.kind === "added" && (
                    <span className="text-emerald-600 dark:text-emerald-400">+ {c.to}</span>
                  )}
                  {c.kind === "removed" && (
                    <span className="text-destructive line-through">{c.from}</span>
                  )}
                  {c.kind === "changed" && (
                    <>
                      <span className="text-muted-foreground line-through">{c.from}</span>
                      <span className="text-muted-foreground"> → </span>
                      <span className="text-foreground">{c.to}</span>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
          {overflow && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="text-[11px] text-muted-foreground hover:text-foreground cursor-pointer"
            >
              {expanded ? "Show less" : `Show ${hidden} more`}
            </button>
          )}
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
