"use client"

import { useEffect, useState } from "react"
import {
  ArrowDown,
  ArrowUp,
  Ban,
  CheckCircle2,
  ChevronRight,
  Code,
  Inbox,
  Minus,
  NotepadText,
  Pencil,
  Save,
  Stamp,
  Undo2,
  XCircle,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { useAppStore } from "@/lib/store"
import {
  TIER_BADGE,
  TIER_LABEL,
} from "@/lib/proposal-meta"
import { ProposalFormView } from "./proposal-form-view"

function formatTimeAgo(iso: string | null) {
  if (!iso) return ""
  const d = new Date(iso)
  const now = new Date()
  const s = Math.max(0, Math.floor((now.getTime() - d.getTime()) / 1000))
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const days = Math.floor(h / 24)
  return `${days}d ago`
}

export function ProposalDetailPanel() {
  const detail = useAppStore((s) => s.selectedDetail)
  const detailLoading = useAppStore((s) => s.detailLoading)
  const selectedId = useAppStore((s) => s.selectedId)
  const setSelectedId = useAppStore((s) => s.setSelectedId)
  const acceptProposal = useAppStore((s) => s.acceptProposal)
  const rejectProposal = useAppStore((s) => s.rejectProposal)
  const editProposal = useAppStore((s) => s.editProposal)

  const [tab, setTab] = useState<"form" | "json">("form")
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null)
  const [rawJson, setRawJson] = useState("")
  const [jsonError, setJsonError] = useState<string | null>(null)
  const [rejectOpen, setRejectOpen] = useState(false)
  const [rejectReason, setRejectReason] = useState("")
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    setEditing(false)
    setDraft(null)
    setRawJson("")
    setJsonError(null)
  }, [selectedId])

  if (!selectedId) {
    return (
      <section className="flex-1 min-w-0 border-r flex flex-col items-center justify-center text-muted-foreground gap-2">
        <Inbox className="size-8" />
        <div className="text-sm">Select a proposal to review</div>
      </section>
    )
  }

  if (detailLoading || !detail) {
    return (
      <section className="flex-1 min-w-0 border-r flex items-center justify-center text-muted-foreground text-sm">
        Loading…
      </section>
    )
  }

  const decided = detail.status !== "pending"
  const activeResource = editing && draft ? draft : detail.resource

  const startEdit = () => {
    setDraft(detail.resource)
    setRawJson(JSON.stringify(detail.resource, null, 2))
    setJsonError(null)
    setEditing(true)
  }

  const cancelEdit = () => {
    setEditing(false)
    setDraft(null)
    setRawJson("")
    setJsonError(null)
  }

  const handleFormChange = (next: Record<string, unknown>) => {
    setDraft(next)
    setRawJson(JSON.stringify(next, null, 2))
    setJsonError(null)
  }

  const handleJsonChange = (text: string) => {
    setRawJson(text)
    try {
      const parsed = JSON.parse(text)
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        setDraft(parsed)
        setJsonError(null)
      } else {
        setJsonError("Resource must be a JSON object")
      }
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : "Invalid JSON")
    }
  }

  const handleAccept = async () => {
    setSubmitting(true)
    try {
      await acceptProposal(detail.id)
    } finally {
      setSubmitting(false)
    }
  }

  const handleReject = async () => {
    if (!rejectReason.trim()) return
    setSubmitting(true)
    try {
      await rejectProposal(detail.id, rejectReason.trim())
      setRejectOpen(false)
      setRejectReason("")
    } finally {
      setSubmitting(false)
    }
  }

  const handleSave = async () => {
    if (!draft || jsonError) return
    setSubmitting(true)
    try {
      await editProposal(detail.id, draft)
      setEditing(false)
      setDraft(null)
      setRawJson("")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="flex-1 min-w-0 border-r flex flex-col h-full min-h-0">
      <div className="h-11 shrink-0 border-b px-3 flex items-center gap-2 min-w-0">
        <Badge className={cn("text-[10px] px-1.5 py-0 shrink-0 font-normal", TIER_BADGE[detail.confidence_tier])}>
          {TIER_LABEL[detail.confidence_tier]}
        </Badge>
        {decided && (
          <span className="flex items-center gap-1.5 shrink-0 text-xs text-muted-foreground">
            {detail.status === "accepted"
              ? <CheckCircle2 className="size-3.5 text-success-fg" />
              : <XCircle className="size-3.5" />}
            {detail.reviewed_by && <span>{detail.reviewed_by}</span>}
            {detail.reviewed_at && (
              <>
                <span className="text-muted-foreground/60">·</span>
                <span>{formatTimeAgo(detail.reviewed_at)}</span>
              </>
            )}
          </span>
        )}
        <div className="flex-1" />
        <div className="flex items-center gap-1 shrink-0">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className={cn("h-7 w-7 cursor-pointer text-muted-foreground", tab === "form" && "bg-muted")}
                onClick={() => setTab("form")}
                aria-label="Form view"
              >
                <NotepadText className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="top"><p>Form</p></TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className={cn("h-7 w-7 cursor-pointer text-muted-foreground", tab === "json" && "bg-muted")}
                onClick={() => setTab("json")}
                aria-label="JSON view"
              >
                <Code className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="top"><p>JSON</p></TooltipContent>
          </Tooltip>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-auto px-3 py-3">
        {tab === "form" ? (
          <>
            <h2 className="text-base font-semibold mb-3 break-words">{detail.display_label}</h2>
            <ProposalFormView
              resource={activeResource}
              mode={editing ? "edit" : "view"}
              onChange={handleFormChange}
            />
          </>
        ) : editing ? (
          <div className="flex flex-col gap-1">
            <textarea
              value={rawJson}
              onChange={(e) => handleJsonChange(e.target.value)}
              className="text-xs font-mono border rounded-md p-2 min-h-[300px] bg-background outline-none focus-visible:ring-1 focus-visible:ring-ring resize-y"
              spellCheck={false}
            />
            {jsonError && (
              <div className="text-xs text-destructive">{jsonError}</div>
            )}
          </div>
        ) : (
          <pre className="text-xs font-mono whitespace-pre overflow-x-auto">
            {JSON.stringify(activeResource, null, 2)}
          </pre>
        )}

        <ReasoningSections
          extraction={detail.extraction_reasoning}
          classification={detail.classification_reasoning}
          merge={detail.merge_reasoning}
          flags={detail.flags}
          confidenceScore={detail.confidence_score}
          breakdown={detail.confidence_breakdown}
          chartMatches={detail.chart_matches}
          supersedes={detail.supersedes}
          conflicts={detail.conflicts_with}
          classificationKind={detail.classification}
          onSelectConflict={(id) => setSelectedId(id)}
        />
      </div>

      <div className="shrink-0 border-t px-3 py-2.5 flex items-center justify-end gap-2">
        {editing ? (
          <>
            <Button variant="outline" size="sm" className="h-7 text-xs" onClick={cancelEdit} disabled={submitting}>
              <Undo2 className="size-3" />
              Cancel
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs text-success-fg border-success-border hover:bg-success-bg hover:text-success-fg"
              onClick={handleSave}
              disabled={submitting || !!jsonError || !draft}
            >
              <Save className="size-3" />
              Save
            </Button>
          </>
        ) : (
          <>
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              onClick={startEdit}
              disabled={decided || submitting}
            >
              <Pencil className="size-3" />
              Edit
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs text-destructive border-destructive/30 hover:bg-destructive/10 hover:text-destructive"
              onClick={() => setRejectOpen(true)}
              disabled={decided || submitting}
            >
              <Ban className="size-3" />
              Reject
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs text-emerald-600 border-emerald-600/40 hover:bg-emerald-600/10 hover:text-emerald-600 dark:text-emerald-400 dark:border-emerald-400/40 dark:hover:bg-emerald-400/10 dark:hover:text-emerald-400"
              onClick={handleAccept}
              disabled={decided || submitting}
            >
              <Stamp className="size-3" />
              Accept
            </Button>
          </>
        )}
      </div>

      <AlertDialog open={rejectOpen} onOpenChange={setRejectOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reject this proposal?</AlertDialogTitle>
            <AlertDialogDescription>
              Provide a brief reason for rejection.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <textarea
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            placeholder="Reason"
            className="w-full text-sm border rounded-md p-2 min-h-20 outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
          <AlertDialogFooter>
            <AlertDialogCancel disabled={submitting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={!rejectReason.trim() || submitting}
              onClick={handleReject}
            >
              Reject
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}

interface ReasoningProps {
  extraction: string
  classification: string
  merge: string | null
  flags: string[]
  confidenceScore: number
  breakdown: import("@/lib/types").ConfidenceBreakdown | null
  chartMatches: { resource_id: string; display: string; match_type: string }[]
  supersedes: string[]
  conflicts: string[]
  classificationKind: "NEW" | "UPDATING" | "CONFLICTING"
  onSelectConflict: (id: string) => void
}

function ReasoningSections({
  extraction,
  classification,
  merge,
  flags,
  confidenceScore,
  breakdown,
  chartMatches,
  supersedes,
  conflicts,
  classificationKind,
  onSelectConflict,
}: ReasoningProps) {
  const conflictDefault = classificationKind === "CONFLICTING"
  const updatingDefault = classificationKind === "UPDATING"

  return (
    <div className="mt-8 flex flex-col gap-6">
      <Section title="Confidence">
        {breakdown ? (
          <ConfidenceBreakdownTable breakdown={breakdown} composite={confidenceScore} />
        ) : flags.length > 0 ? (
          <ul className="flex flex-col gap-1.5">
            {flags.map((f) => (
              <li key={f} className="flex items-start gap-2 text-sm">
                <FlagIndicator direction={flagDirection(f)} />
                <span className="flex-1">{f}</span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="text-sm text-muted-foreground">
            No specific signals — assigned by confidence score alone.
          </div>
        )}
      </Section>

      <Section title="Reasoning">
        <div className="flex flex-col gap-3">
          <ReasoningRow label="What the note said" value={extraction} />
          <ReasoningRow label="Compared to chart" value={classification} />
          {merge && <ReasoningRow label="Across notes" value={merge} />}
        </div>
      </Section>

      {chartMatches.length > 0 && (
        <Disclosure title={`Chart matches (${chartMatches.length})`} defaultOpen={conflictDefault}>
          <div className="flex flex-col gap-1">
            {chartMatches.map((m) => (
              <div key={m.resource_id} className="flex items-center gap-3 text-sm">
                <span className="flex-1 truncate">{m.display}</span>
                <span className="text-xs text-muted-foreground shrink-0">{m.match_type}</span>
              </div>
            ))}
          </div>
        </Disclosure>
      )}

      {supersedes.length > 0 && (
        <Disclosure title={`Supersedes (${supersedes.length})`} defaultOpen={updatingDefault}>
          <div className="flex flex-col gap-1">
            {supersedes.map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => onSelectConflict(id)}
                className="text-left text-xs font-mono text-primary hover:underline cursor-pointer"
              >
                {id}
              </button>
            ))}
          </div>
        </Disclosure>
      )}

      {conflicts.length > 0 && (
        <Disclosure title={`Conflicts (${conflicts.length})`} defaultOpen={conflictDefault}>
          <div className="flex flex-col gap-1">
            {conflicts.map((id) => (
              <button
                key={id}
                type="button"
                onClick={() => onSelectConflict(id)}
                className="text-left text-xs font-mono text-primary hover:underline cursor-pointer"
              >
                {id}
              </button>
            ))}
          </div>
        </Disclosure>
      )}
    </div>
  )
}

function ReasoningRow({ label, value }: { label: string; value: string }) {
  if (!value) return null
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span className="text-sm leading-snug">{value}</span>
    </div>
  )
}

function Section({ title, children, suffix }: { title: string; children: React.ReactNode; suffix?: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          {title}
        </div>
        {suffix}
      </div>
      {children}
    </div>
  )
}

type FlagDirection = "up" | "down" | "neutral"

function flagDirection(f: string): FlagDirection {
  if (f === "Single mention") return "down"
  if (f.startsWith("Mentioned in")) return "up"
  if (f === "Stated assertively in source") return "up"
  if (f === "Source language is uncertain or secondhand") return "down"
  if (f === "No terminology code found — verify manually") return "down"
  if (f.startsWith("Coded in")) return "up"
  if (f.startsWith("Conflicts with:")) return "down"
  if (f === "Already in chart") return "up"
  if (f === "Approximate match — verify") return "down"
  return "neutral"
}

const AXIS_LABELS: { key: keyof import("@/lib/types").ConfidenceBreakdown; label: string }[] = [
  { key: "source", label: "Source" },
  { key: "certainty", label: "Certainty" },
  { key: "coding", label: "Coding" },
  { key: "match", label: "Match" },
  { key: "classification", label: "Verdict" },
]

function axisDirection(score: number): FlagDirection {
  if (score >= 0.85) return "up"
  if (score <= 0.5) return "down"
  return "neutral"
}

function ConfidenceBreakdownTable({
  breakdown,
}: {
  breakdown: import("@/lib/types").ConfidenceBreakdown
  composite: number
}) {
  const rows = AXIS_LABELS.map(({ key, label }) => ({
    key,
    label,
    axis: breakdown[key],
    direction: axisDirection(breakdown[key].score),
  }))
  const order: Record<FlagDirection, number> = { down: 0, neutral: 1, up: 2 }
  rows.sort((a, b) => order[a.direction] - order[b.direction])

  return (
    <ul className="flex flex-col gap-1.5">
      {rows.map(({ key, label, axis, direction }) => (
        <li key={key} className="flex items-start gap-2 text-sm">
          <FlagIndicator direction={direction} />
          <span className="text-xs text-muted-foreground w-20 shrink-0 pt-0.5">{label}</span>
          <span className="flex-1">{axis.reason}</span>
        </li>
      ))}
    </ul>
  )
}

function FlagIndicator({ direction }: { direction: FlagDirection }) {
  if (direction === "up") {
    return <ArrowUp className="size-3 shrink-0 text-emerald-600 dark:text-emerald-400 mt-0.5" aria-label="boosts confidence" />
  }
  if (direction === "down") {
    return <ArrowDown className="size-3 shrink-0 text-destructive mt-0.5" aria-label="reduces confidence" />
  }
  return <Minus className="size-3 shrink-0 text-muted-foreground mt-0.5" aria-label="context" />
}


function Disclosure({
  title,
  children,
  defaultOpen,
}: {
  title: string
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(!!defaultOpen)
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-1.5 group cursor-pointer"
      >
        <ChevronRight className={cn(
          "size-3 text-muted-foreground transition-transform",
          open && "rotate-90",
        )} />
        <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground group-hover:text-foreground transition-colors">
          {title}
        </span>
      </button>
      {open && <div className="mt-2 pl-4">{children}</div>}
    </div>
  )
}

