"use client"

import { useEffect, useMemo, useState } from "react"
import { useRouter, useParams } from "next/navigation"
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  CheckCircle2,
  ClipboardPlus,
  Code,
  DatabaseSearch,
  FileText,
  Inbox,
  Loader2,
  Minus,
  NotepadText,
  Save,
  MessageCircleQuestionMark,
  Undo2,
  XCircle,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useAppStore } from "@/lib/store"
import { TIER_LABEL, TIER_TEXT } from "@/lib/proposal-meta"
import { ProposalFormView } from "./proposal-form-view"
import { ProposalConflictCallout } from "./proposal-conflict-callout"
import { ProvenanceCard } from "./provenance-card"
import { JsonEditor } from "@/components/ui/json-editor"
import { useShortcuts } from "@/lib/use-shortcuts"

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
  const router = useRouter()
  const params = useParams<{ runId: string }>()
  const detail = useAppStore((s) => s.selectedDetail)
  const proposals = useAppStore((s) => s.proposals)
  const selectedId = useAppStore((s) => s.selectedId)
  const contentView = useAppStore((s) => s.contentView)
  const setContentView = useAppStore((s) => s.setContentView)
  const rightTab = useAppStore((s) => s.rightTab)
  const setRightTab = useAppStore((s) => s.setRightTab)
  const revealChartResource = useAppStore((s) => s.revealChartResource)
  const acceptProposal = useAppStore((s) => s.acceptProposal)
  const rejectProposal = useAppStore((s) => s.rejectProposal)
  const reopenProposal = useAppStore((s) => s.reopenProposal)
  const editProposal = useAppStore((s) => s.editProposal)
  const tokenValid = useAppStore((s) => s.tokenValid)
  const actionError = useAppStore((s) => s.actionError)
  const clearActionError = useAppStore((s) => s.clearActionError)

  const [tab, setTab] = useState<"form" | "json">("form")
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null)
  const [rawJson, setRawJson] = useState("")
  const [jsonError, setJsonError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<"accept" | "reject" | null>(null)
  const [rejectReason, setRejectReason] = useState("")
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    setEditing(false)
    setDraft(null)
    setRawJson("")
    setJsonError(null)
    setConfirming(null)
    setRejectReason("")
  }, [selectedId])

  const navIds = useMemo(() => {
    const tierRank: Record<string, number> = { ATTENTION: 0, REVIEW: 1, CONFIDENT: 2 }
    return [...proposals]
      .sort((a, b) => {
        const t = (tierRank[a.confidence_tier] ?? 99) - (tierRank[b.confidence_tier] ?? 99)
        if (t !== 0) return t
        return a.resource_type.localeCompare(b.resource_type)
      })
      .map((p) => p.id)
  }, [proposals])

  const currentIdx = selectedId ? navIds.indexOf(selectedId) : -1
  const prevId = currentIdx > 0
    ? navIds[currentIdx - 1]
    : currentIdx === -1 ? (navIds[navIds.length - 1] ?? null) : null
  const nextId = currentIdx >= 0 && currentIdx < navIds.length - 1
    ? navIds[currentIdx + 1]
    : currentIdx === -1 ? (navIds[0] ?? null) : null
  const runId = params?.runId

  const goTo = (id: string | null) => {
    if (id && runId) router.push(`/${runId}/${id}`)
  }

  const locked = tokenValid !== true
  const canDecide = !!detail && detail.status === "pending" && !locked && !submitting
  const shortcutsActive = !confirming && !editing

  useShortcuts(
    {
      j: () => goTo(nextId),
      ArrowDown: () => goTo(nextId),
      k: () => goTo(prevId),
      ArrowUp: () => goTo(prevId),
      a: () => { if (canDecide) setConfirming("accept") },
      r: () => { if (canDecide) setConfirming("reject") },
      e: () => {
        if (!detail || !canDecide) return
        setDraft(detail.resource)
        setRawJson(JSON.stringify(detail.resource, null, 2))
        setJsonError(null)
        setEditing(true)
      },
      v: () => { setContentView("right"); setRightTab("notes") },
    },
    shortcutsActive,
  )

  if (!selectedId) {
    return (
      <section className="flex-1 min-w-0 border-r flex flex-col items-center justify-center text-muted-foreground gap-2">
        <Inbox className="size-8" />
        <div className="text-sm">Select a proposal to review</div>
      </section>
    )
  }

  if (!detail) {
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
      setConfirming(null)
    } finally {
      setSubmitting(false)
    }
  }

  const handleReject = async () => {
    if (!rejectReason.trim()) return
    setSubmitting(true)
    try {
      await rejectProposal(detail.id, rejectReason.trim())
      setConfirming(null)
      setRejectReason("")
    } finally {
      setSubmitting(false)
    }
  }

  const cancelConfirm = () => {
    setConfirming(null)
    setRejectReason("")
  }

  const handleReopen = async () => {
    setSubmitting(true)
    try {
      await reopenProposal(detail.id)
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

  const showDetailBody = contentView === "detail"
  const navTabs: Array<{ value: "detail" | "notes" | "chart" | "chat"; label: string; icon: React.ReactNode }> = [
    { value: "detail", label: "Proposal", icon: <ClipboardPlus className="size-3.5" /> },
    { value: "notes", label: "Notes", icon: <FileText className="size-3.5" /> },
    { value: "chart", label: "FHIR store", icon: <DatabaseSearch className="size-3.5" /> },
    { value: "chat", label: "AI chat", icon: <MessageCircleQuestionMark className="size-3.5" /> },
  ]
  const activeNavTab: typeof navTabs[number]["value"] = contentView === "detail" ? "detail" : rightTab
  const handleNavTab = (v: typeof navTabs[number]["value"]) => {
    if (v === "detail") setContentView("detail")
    else { setContentView("right"); setRightTab(v) }
  }

  return (
    <section
      className={cn(
        "flex-1 min-w-0 border-r flex-col h-full min-h-0",
        showDetailBody ? "flex" : "hidden xl:flex",
      )}
    >
      {/* Below xl: navigation header (back + title + nav tabs) */}
      <div className="h-11 shrink-0 border-b px-3 flex items-center gap-2 min-w-0 xl:hidden">
        <ArrowLeft
          className="size-3.5 text-muted-foreground hover:text-foreground cursor-pointer lg:hidden shrink-0"
          onClick={() => params?.runId && router.push(`/${params.runId}`)}
          aria-label="Back to list"
        />
        <span className="text-sm font-medium truncate flex-1 min-w-0">{detail.display_label}</span>
        <div className="flex items-center gap-1 shrink-0">
          {navTabs.map((t) => (
            <Tooltip key={t.value}>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className={cn(
                    "h-7 w-7 cursor-pointer text-muted-foreground",
                    activeNavTab === t.value && "bg-muted",
                  )}
                  onClick={() => handleNavTab(t.value)}
                  aria-label={t.label}
                >
                  {t.icon}
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top"><p>{t.label}</p></TooltipContent>
            </Tooltip>
          ))}
        </div>
      </div>

      {/* Sub-header: tier label OR decision status + form/JSON toggle */}
      <div className="h-11 shrink-0 border-b px-3 flex items-center gap-2 min-w-0">
        {decided ? (
          <span className="flex items-baseline gap-1.5 shrink-0 text-xs text-muted-foreground">
            <span>{detail.status === "accepted" ? "Accepted" : "Rejected"}</span>
            {detail.reviewed_at && (
              <>
                <span className="text-muted-foreground/60">·</span>
                <span>{formatTimeAgo(detail.reviewed_at)}</span>
              </>
            )}
          </span>
        ) : (
          <span className={cn("text-xs shrink-0 truncate", TIER_TEXT[detail.confidence_tier])}>
            {TIER_LABEL[detail.confidence_tier]}
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

      {confirming ? (
        <ConfirmView
          kind={confirming}
          reason={rejectReason}
          onReasonChange={setRejectReason}
          onCancel={cancelConfirm}
          onConfirm={confirming === "accept" ? handleAccept : handleReject}
          submitting={submitting}
        />
      ) : tab === "form" ? (
        <div className="flex-1 min-h-0 overflow-auto px-3 py-3">
          <div className="mb-3 flex items-baseline gap-2 min-w-0">
            <h2 className="text-base font-semibold break-words flex-1 min-w-0">{detail.display_label}</h2>
            {editing && (
              <span className="shrink-0 text-[10px] font-medium uppercase tracking-wider text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                Editing
              </span>
            )}
          </div>
          {!editing && detail.status === "rejected" && detail.rejection_reason && (
            <RejectionBanner reason={detail.rejection_reason} />
          )}
          {!editing && detail.classification === "CONFLICTING" && !decided && (
            <ProposalConflictCallout
              proposed={activeResource}
              matches={detail.chart_matches}
            />
          )}
          <ProposalFormView
            resource={activeResource}
            mode={editing ? "edit" : "view"}
            onChange={handleFormChange}
          />
          {!editing && !decided && (
            <ReasoningSections
              extraction={detail.extraction_reasoning}
              classification={detail.classification_reasoning}
              merge={detail.merge_reasoning}
              flags={detail.flags}
              confidenceScore={detail.confidence_score}
              breakdown={detail.confidence_breakdown}
              chartMatches={detail.chart_matches}
              classificationKind={detail.classification}
              onRevealChartResource={revealChartResource}
            />
          )}
          {!editing && detail.status === "accepted" && detail.provenance_resource && (
            <div className="mt-6">
              <ProvenanceCard resource={detail.provenance_resource} />
            </div>
          )}
        </div>
      ) : (
        <div className="flex-1 min-h-0 overflow-auto pb-6">
          <JsonEditor
            value={editing ? rawJson : JSON.stringify(activeResource, null, 2)}
            editable={editing}
            onChange={editing ? handleJsonChange : undefined}
          />
        </div>
      )}

      {!confirming && actionError && !editing && (
        <ActionErrorCallout message={actionError} onDismiss={clearActionError} />
      )}

      {!confirming && detail.status !== "accepted" && (
        <div className="shrink-0 border-t px-3 py-2.5 flex items-center gap-2">
          {!editing && <UnauthenticatedNotice tokenValid={tokenValid} />}
          <div className="ml-auto flex items-center gap-2">
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
            ) : detail.status === "rejected" ? (
              <Button
                variant="outline"
                size="sm"
                className="h-7 text-xs"
                onClick={handleReopen}
                disabled={submitting || tokenValid !== true}
              >
                <Undo2 className="size-3" />
                Reopen
              </Button>
            ) : (
              <ReviewActions
                tokenValid={tokenValid}
                decided={decided}
                submitting={submitting}
                onEdit={startEdit}
                onReject={() => setConfirming("reject")}
                onAccept={() => setConfirming("accept")}
              />
            )}
          </div>
        </div>
      )}
    </section>
  )
}

interface ConfirmViewProps {
  kind: "accept" | "reject"
  reason: string
  onReasonChange: (v: string) => void
  onCancel: () => void
  onConfirm: () => void
  submitting: boolean
}

function ConfirmView({ kind, reason, onReasonChange, onCancel, onConfirm, submitting }: ConfirmViewProps) {
  const isAccept = kind === "accept"
  const Icon = isAccept ? CheckCircle2 : XCircle
  const disabled = submitting || (!isAccept && !reason.trim())

  return (
    <div className="flex-1 min-h-0 flex flex-col items-center justify-center text-center gap-3 px-6">
      <div className="h-10 w-10 rounded-full bg-muted flex items-center justify-center">
        <Icon className="size-4.5 text-muted-foreground" />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium">
          {isAccept ? "Accept this proposal?" : "Reject this proposal?"}
        </p>
        <p className="text-xs text-muted-foreground max-w-sm">
          {isAccept
            ? "This writes the resource to FHIR with a Provenance record naming you."
            : "Provide a brief reason — it's saved to the audit log."}
        </p>
      </div>
      {!isAccept && (
        <textarea
          autoFocus
          value={reason}
          onChange={(e) => onReasonChange(e.target.value)}
          placeholder="Reason"
          disabled={submitting}
          className="w-full max-w-sm text-base md:text-sm border rounded-md p-2 min-h-20 outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
      )}
      <div className="flex items-center gap-2 mt-1">
        <Button variant="outline" size="sm" className="h-7 text-xs cursor-pointer" onClick={onCancel} disabled={submitting}>
          Cancel
        </Button>
        <Button
          variant="outline"
          size="sm"
          className={cn(
            "h-7 text-xs cursor-pointer",
            isAccept
              ? "text-emerald-600 border-emerald-600/40 hover:bg-emerald-600/10 hover:text-emerald-600 dark:text-emerald-400 dark:border-emerald-400/40 dark:hover:bg-emerald-400/10 dark:hover:text-emerald-400"
              : "text-destructive border-destructive/30 hover:bg-destructive/10 hover:text-destructive",
          )}
          onClick={onConfirm}
          disabled={disabled}
        >
          {submitting ? <Loader2 className="size-3 animate-spin" /> : <Icon className="size-3" />}
          {isAccept ? "Accept" : "Reject"}
        </Button>
      </div>
    </div>
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
  classificationKind: "NEW" | "UPDATING" | "CONFLICTING"
  onRevealChartResource: (id: string) => void
}

const CHART_SECTION_TITLE: Record<"NEW" | "UPDATING" | "CONFLICTING", string> = {
  NEW: "Related in chart",
  UPDATING: "Replaces in chart",
  CONFLICTING: "Conflicts in chart",
}

const MATCH_TYPE_LABEL: Record<string, string> = {
  exact_code: "exact code",
  ingredient: "same ingredient",
  display_text: "name match",
}

const CONNECTOR_FRAGMENTS = new Set([
  "in the setting of",
  "due to",
  "secondary to",
  "associated with",
  "in association with",
  "from history of",
  "from a history of",
  "in the context of",
  "related to",
  "on the background of",
])

function isFragmentReasoning(value: string): boolean {
  const t = value.trim().toLowerCase().replace(/[.!?]+$/, "")
  if (!t) return true
  if (t.split(/\s+/).length < 3) return true
  return CONNECTOR_FRAGMENTS.has(t)
}

function ReasoningSections({
  extraction,
  classification,
  merge,
  flags,
  confidenceScore,
  breakdown,
  chartMatches,
  classificationKind,
  onRevealChartResource,
}: ReasoningProps) {
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
          <ReasoningRow label="What the note said" value={extraction} skipFragments />
          <ReasoningRow label="Compared to chart" value={classification} />
          {merge && <ReasoningRow label="Across notes" value={merge} />}
        </div>
      </Section>

      {chartMatches.length > 0 && classificationKind !== "CONFLICTING" && (
        <Section title={CHART_SECTION_TITLE[classificationKind]}>
          <div className="flex flex-col gap-1">
            {chartMatches.map((m) => (
              <button
                key={m.resource_id}
                type="button"
                onClick={() => onRevealChartResource(m.resource_id)}
                className="group flex items-center gap-3 text-sm text-left rounded-sm px-2 -mx-2 py-1 hover:bg-muted cursor-pointer"
              >
                <span className="flex-1 truncate">{m.display || m.resource_id}</span>
                <span className="text-xs text-muted-foreground shrink-0">
                  {MATCH_TYPE_LABEL[m.match_type] ?? m.match_type}
                </span>
              </button>
            ))}
          </div>
        </Section>
      )}

    </div>
  )
}

function ReasoningRow({
  label,
  value,
  skipFragments,
}: {
  label: string
  value: string
  skipFragments?: boolean
}) {
  if (!value) return null
  if (skipFragments && isFragmentReasoning(value)) return null
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
  { key: "certainty", label: "Certainty" },
  { key: "coding", label: "Coding" },
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

function RejectionBanner({ reason }: { reason: string }) {
  return (
    <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 flex items-start gap-2">
      <XCircle className="size-3.5 text-destructive mt-0.5 shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="text-xs font-medium text-destructive mb-0.5">Rejected</div>
        <div className="text-xs text-foreground/80 leading-snug whitespace-pre-wrap break-words">{reason}</div>
      </div>
    </div>
  )
}

function ActionErrorCallout({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  return (
    <div className="shrink-0 border-t bg-destructive/5 px-3 py-2 flex items-start gap-2">
      <span className="text-xs text-destructive flex-1 leading-snug">{message}</span>
      <button
        type="button"
        onClick={onDismiss}
        className="text-xs text-destructive/80 hover:text-destructive cursor-pointer shrink-0"
        aria-label="Dismiss"
      >
        Dismiss
      </button>
    </div>
  )
}

function UnauthenticatedNotice({ tokenValid }: { tokenValid: boolean | null }) {
  if (tokenValid === true) return null
  const verifying = tokenValid === null
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "text-xs cursor-default",
            verifying ? "text-muted-foreground" : "text-destructive",
          )}
          role="status"
        >
          {verifying ? "Verifying access…" : "Read-only — review token required"}
        </span>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-[240px] [text-wrap:pretty]">
        Writes need an alias of the clinician's Prompt Opinion session. Without it, no FHIR change — Provenance always names a verified clinician. Production would SSO-embed this surface.
      </TooltipContent>
    </Tooltip>
  )
}

interface ReviewActionsProps {
  tokenValid: boolean | null
  decided: boolean
  submitting: boolean
  onEdit: () => void
  onReject: () => void
  onAccept: () => void
}

function ReviewActions({ tokenValid, decided, submitting, onEdit, onReject, onAccept }: ReviewActionsProps) {
  const locked = tokenValid !== true
  const disabled = decided || submitting || locked
  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="h-7 text-xs"
        onClick={onEdit}
        disabled={disabled}
      >
        Edit
      </Button>
      <Button
        variant="outline"
        size="sm"
        className="h-7 text-xs text-destructive border-destructive/30 hover:bg-destructive/10 hover:text-destructive"
        onClick={onReject}
        disabled={disabled}
      >
        Reject
      </Button>
      <Button
        variant="outline"
        size="sm"
        className="h-7 text-xs text-emerald-600 border-emerald-600/40 hover:bg-emerald-600/10 hover:text-emerald-600 dark:text-emerald-400 dark:border-emerald-400/40 dark:hover:bg-emerald-400/10 dark:hover:text-emerald-400"
        onClick={onAccept}
        disabled={disabled}
      >
        Accept
      </Button>
    </>
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


