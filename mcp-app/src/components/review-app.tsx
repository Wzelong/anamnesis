import { useEffect, useMemo, useRef, useState } from "react"
import type { App } from "@modelcontextprotocol/ext-apps"
import {
  Ban,
  BookSearch,
  Check,
  CheckCheck,
  ChevronLeft,
  Braces,
  ChevronDown,
  CircleAlert,
  ClipboardList,
  ClipboardPen,
  Form,
  FilePlusCorner,
  FileText,
  ListFilter,
  Loader2,
  Pencil,
  Search,
  Settings,
  Stamp,
  TriangleAlert,
  Undo2,
  X,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { toast } from "sonner"
import { callTool, parseStructured, resultText } from "../mcp"
import type { ExtractionResult, PatientHeader, Proposal, SourceDocument } from "../types"
import { cn } from "../lib/cn"
import { MOCK_RESULT } from "../mock"
import {
  CLASSIFICATION_LABEL,
  RESOURCE_LABEL,
  TIER_BADGE,
  TIER_LABEL,
  TIER_TEXT,
} from "../lib/proposal-meta"
import { Button } from "./ui/button"
import { Input } from "./ui/input"
import { Textarea } from "./ui/textarea"
import { Checkbox } from "./ui/checkbox"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "./ui/empty"
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu"
import { NoteReader } from "./note-reader"
import { ProposalFormView } from "./proposal-form-view"
import { CodeSearch } from "./code-search"
import { ReasoningSections } from "./reasoning-sections"
import { InterProposalConflictCallout, ProposalConflictCallout } from "./conflict-callouts"
import { ProvenanceCard } from "./provenance-card"

// PO does not relay real pipeline progress, so the loading screen runs on a
// timed simulation: one verb per stage, ~50s total for a 4-document chart. The
// `at` value is the fraction of total time elapsed when each verb appears.
const LOADING_STAGES: { at: number; verb: string }[] = [
  { at: 0.0, verb: "Reading source notes" },
  { at: 0.12, verb: "Extracting clinical facts" },
  { at: 0.4, verb: "Coding to standard terminology" },
  { at: 0.62, verb: "Reconciling against the chart" },
  { at: 0.82, verb: "Assembling proposals" },
]
const LOADING_TOTAL_MS = 50000

function loadingVerb(progress: number): string {
  let verb = LOADING_STAGES[0].verb
  for (const s of LOADING_STAGES) if (progress >= s.at) verb = s.verb
  return verb
}

// dev: served at root by Vite. built: copied next to the JS chunk in /app/,
// resolved against the module's own (cloudflare-hosted) URL so the iframe can load it.
const LOGO_URL = import.meta.env.DEV ? "/logo.png" : new URL("./logo.png", import.meta.url).href

function elapsedLabel(startMs: number | null): string {
  if (!startMs) return ""
  const s = Math.floor((Date.now() - startMs) / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${s % 60}s`
}

const CLASS_ICON: Record<string, LucideIcon> = {
  NEW: FilePlusCorner,
  UPDATING: ClipboardPen,
  CONFLICTING: CircleAlert,
}

const TIER_ICON_COLOR: Record<string, string> = {
  ATTENTION: "text-destructive",
  REVIEW: "text-warning-fg",
  CONFIDENT: "text-muted-foreground",
}

// Mirrors the shape backend/fhir/write.py:build_provenance emits, for local preview.
function mockProvenance(p: Proposal): Record<string, unknown> {
  const activity = p.classification === "UPDATING" ? "UPDATE" : "CREATE"
  return {
    resourceType: "Provenance",
    target: [{ reference: `${p.resource_type}/${p.id}` }],
    recorded: new Date().toISOString(),
    activity: { coding: [{ system: "http://terminology.hl7.org/CodeSystem/v3-DataOperation", code: activity }] },
    agent: [
      { type: { coding: [{ code: "author" }] }, who: { display: "Anamnesis augmentation agent" } },
      { type: { coding: [{ code: "attester" }] }, who: { display: "Reviewing clinician" } },
    ],
    entity: p.citations.map((c) => ({ role: "source", what: { reference: `DocumentReference/${c.document_id}` } })),
    extension: p.citations.map((c) => ({
      url: "https://anamnesis.health/fhir/StructureDefinition/source-span",
      extension: [
        { url: "start", valueInteger: c.char_start },
        { url: "end", valueInteger: c.char_end },
        { url: "text", valueString: c.text },
      ],
    })),
  }
}

type Phase = "idle" | "running" | "ready" | "error"
type Decision = {
  status: "accepted" | "rejected"
  resourceRef?: string | null
  provenance?: Record<string, unknown> | null
  reason?: string
  at: number
}

const TIER_STYLE: Record<string, string> = {
  ATTENTION: "bg-error-bg text-error-fg border-error-border",
  REVIEW: "bg-warning-bg text-warning-fg border-warning-border",
  CONFIDENT: "bg-success-bg text-success-fg border-success-border",
}

const BADGE_VARIANT: Record<string, string> = {
  default: "border-transparent bg-primary text-primary-foreground",
  secondary: "border-transparent bg-secondary text-secondary-foreground",
  destructive: "border-transparent bg-destructive text-white",
  outline: "text-foreground",
}

function Badge({
  children,
  className,
  variant = "default",
}: {
  children: React.ReactNode
  className?: string
  variant?: "default" | "secondary" | "destructive" | "outline"
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center rounded-full border px-2 py-0.5 text-xs font-medium w-fit whitespace-nowrap shrink-0",
        BADGE_VARIANT[variant],
        className,
      )}
    >
      {children}
    </span>
  )
}

export function ReviewApp({
  app,
  header,
  preview,
}: {
  app: App | null
  header: PatientHeader | null
  preview?: "loading" | "flow" | "ready" | null
}) {
  const [phase, setPhase] = useState<Phase>(
    app ? "running" : preview === "ready" ? "ready" : preview ? "running" : "idle",
  )
  const [progress, setProgress] = useState(0)
  const [startMs, setStartMs] = useState<number | null>(null)
  const [result, setResult] = useState<ExtractionResult | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [decisions, setDecisions] = useState<Record<string, Decision>>({})
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [detailTab, setDetailTab] = useState<"form" | "source" | "codes">("form")
  const [showRaw, setShowRaw] = useState(false)
  const [activeDocId, setActiveDocId] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [statusFilter, setStatusFilter] = useState("")
  const [tierFilter, setTierFilter] = useState("")
  const [typeFilter, setTypeFilter] = useState("")
  const [classFilter, setClassFilter] = useState("")
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [bulkConfirm, setBulkConfirm] = useState<"accept" | "reject" | null>(null)
  const started = useRef(false)

  // Drives the loading bar: eases 0 → 0.95 over LOADING_TOTAL_MS while the real
  // run is in flight, then `settle()` snaps to 1 and reveals the result. PO does
  // not relay real progress, so this is a time-based simulation, not live data.
  const runLoading = (onDone: () => void) => {
    setStartMs(Date.now())
    const start = Date.now()
    let done = false
    let frame: ReturnType<typeof setTimeout> | undefined
    const tick = () => {
      if (done) return
      const t = Math.min((Date.now() - start) / LOADING_TOTAL_MS, 1)
      // ease-out so it slows as it approaches the 0.95 ceiling
      setProgress(0.95 * (1 - Math.pow(1 - t, 2)))
      frame = setTimeout(tick, 80)
    }
    tick()
    const settle = () => {
      done = true
      clearTimeout(frame)
      setProgress(1)
      setTimeout(onDone, 450)
    }
    const cancel = () => { done = true; clearTimeout(frame) }
    return { settle, cancel }
  }

  useEffect(() => {
    if (!app || started.current) return
    started.current = true
    const loop = runLoading(() => setPhase("ready"))
    ;(async () => {
      try {
        const res = await callTool(app, "RunExtraction", {})
        const data = parseStructured<ExtractionResult>(res)
        if (!data) throw new Error(resultText(res) || "no extraction result")
        setResult(data)
        setSelectedId(data.proposals[0]?.id ?? null)
        loop.settle()
      } catch (e) {
        loop.cancel()
        setError(String(e))
        setPhase("error")
      }
    })()
    return loop.cancel
  }, [app])

  useEffect(() => {
    if (!preview || started.current) return
    started.current = true
    if (preview === "ready") {
      setResult(MOCK_RESULT)
      setSelectedId(MOCK_RESULT.proposals[0]?.id ?? null)
      return
    }
    const loop = runLoading(() => setPhase("ready"))
    const t = setTimeout(() => {
      setResult(MOCK_RESULT)
      setSelectedId(MOCK_RESULT.proposals[0]?.id ?? null)
      loop.settle()
    }, preview === "flow" ? 6000 : LOADING_TOTAL_MS)
    return () => { clearTimeout(t); loop.cancel() }
  }, [preview])

  const selected = useMemo(
    () => result?.proposals.find((p) => p.id === selectedId) ?? null,
    [result, selectedId],
  )

  const allProposals = result?.proposals ?? []

  const counts = useMemo(() => {
    const tier: Record<string, number> = { ATTENTION: 0, REVIEW: 0, CONFIDENT: 0 }
    const type: Record<string, number> = {}
    const cls: Record<string, number> = { NEW: 0, UPDATING: 0, CONFLICTING: 0 }
    const status: Record<string, number> = { pending: 0, accepted: 0, rejected: 0 }
    for (const p of allProposals) {
      tier[p.confidence_tier] = (tier[p.confidence_tier] ?? 0) + 1
      type[p.resource_type] = (type[p.resource_type] ?? 0) + 1
      cls[p.classification] = (cls[p.classification] ?? 0) + 1
      const st = decisions[p.id]?.status ?? "pending"
      status[st] = (status[st] ?? 0) + 1
    }
    return { tier, type, cls, status }
  }, [allProposals, decisions])

  const filteredProposals = useMemo(() => {
    const q = search.trim().toLowerCase()
    const tierRank: Record<string, number> = { ATTENTION: 0, REVIEW: 1, CONFIDENT: 2 }
    return allProposals
      .filter((p) => {
        const st = decisions[p.id]?.status ?? "pending"
        if (statusFilter && st !== statusFilter) return false
        if (tierFilter && p.confidence_tier !== tierFilter) return false
        if (typeFilter && p.resource_type !== typeFilter) return false
        if (classFilter && p.classification !== classFilter) return false
        if (q && !p.display_label.toLowerCase().includes(q)) return false
        return true
      })
      .sort((a, b) => {
        const t = (tierRank[a.confidence_tier] ?? 99) - (tierRank[b.confidence_tier] ?? 99)
        if (t !== 0) return t
        return a.resource_type.localeCompare(b.resource_type)
      })
  }, [allProposals, decisions, search, statusFilter, tierFilter, typeFilter, classFilter])

  const selectedProposals = useMemo(
    () => allProposals.filter((p) => selectedIds.has(p.id)),
    [allProposals, selectedIds],
  )
  const allSelectedConfident =
    selectedProposals.length > 0 && selectedProposals.every((p) => p.confidence_tier === "CONFIDENT")

  async function decide(
    p: Proposal,
    action: "accept" | "reject",
    opts?: { resource?: Record<string, unknown>; reason?: string },
  ): Promise<boolean> {
    setBusyId(p.id)
    try {
      const { resourceRef, provenance } = await applyDecision(p, action, opts)
      setDecisions((d) => ({
        ...d,
        [p.id]: {
          status: action === "accept" ? "accepted" : "rejected",
          resourceRef,
          provenance,
          reason: opts?.reason,
          at: Date.now(),
        },
      }))
      if (action === "accept") {
        toast.success("Written to FHIR", {
          description: resourceRef ? `${p.display_label} · ${resourceRef}` : p.display_label,
        })
      } else {
        toast.success("Proposal rejected", { description: p.display_label })
      }
      return true
    } catch (e) {
      toast.error(action === "accept" ? "Write failed" : "Reject failed", { description: String(e) })
      return false
    } finally {
      setBusyId(null)
    }
  }

  function reopen(p: Proposal) {
    setDecisions((d) => {
      const next = { ...d }
      delete next[p.id]
      return next
    })
  }

  async function applyDecision(
    p: Proposal,
    action: "accept" | "reject",
    opts?: { resource?: Record<string, unknown>; reason?: string },
  ): Promise<{ resourceRef: string | null; provenance: Record<string, unknown> | null }> {
    if (!app) {
      await new Promise((r) => setTimeout(r, 300))
      const prov = action === "accept" ? mockProvenance(p) : null
      const ref = (prov?.target as Array<{ reference?: string }> | undefined)?.[0]?.reference ?? null
      return { resourceRef: action === "accept" ? ref : null, provenance: prov }
    }
    const tool = action === "accept" ? "AcceptAugmentation" : "RejectAugmentation"
    // Always send the full proposal payload on accept: the host may route this
    // call to a worker that never cached the run, so we can't rely on server-side
    // lookup by run_id (see session_cache contract).
    const args =
      action === "accept"
        ? {
            run_id: p.run_id,
            proposal_id: p.id,
            resource: opts?.resource ?? p.resource,
            citations: p.citations,
            classification: p.classification,
            supersedes: p.supersedes ?? [],
          }
        : { run_id: p.run_id, proposal_id: p.id, resource_type: p.resource_type, ...(opts?.reason ? { reason: opts.reason } : {}) }
    const res = await callTool(app, tool, args)
    const data = parseStructured<{ provenance_resource?: Record<string, unknown>; write_result?: { resource_ref?: string } }>(res)
    return { resourceRef: data?.write_result?.resource_ref ?? null, provenance: data?.provenance_resource ?? null }
  }

  const toggleSelect = (id: string) =>
    setSelectedIds((s) => {
      const next = new Set(s)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  const selectAllPending = (ids: string[]) =>
    setSelectedIds((s) => (ids.length > 0 && ids.every((id) => s.has(id)) ? new Set() : new Set(ids)))

  const clearSelection = () => setSelectedIds(new Set())

  async function bulkDecide(action: "accept" | "reject", reason?: string): Promise<boolean> {
    const ids = [...selectedIds]
    const targets = (result?.proposals ?? []).filter((p) => ids.includes(p.id) && !decisions[p.id])
    setSelectedIds(new Set())
    let ok = 0
    let failed = 0
    for (const p of targets) {
      try {
        const { resourceRef, provenance } = await applyDecision(p, action, reason ? { reason } : undefined)
        setDecisions((d) => ({
          ...d,
          [p.id]: { status: action === "accept" ? "accepted" : "rejected", resourceRef, provenance, reason, at: Date.now() },
        }))
        ok++
      } catch {
        failed++
      }
    }
    const verb = action === "accept" ? "written to FHIR" : "rejected"
    if (ok > 0) toast.success(`${ok} proposal${ok === 1 ? "" : "s"} ${verb}`, failed > 0 ? { description: `${failed} failed` } : undefined)
    else if (failed > 0) toast.error(`${failed} proposal${failed === 1 ? "" : "s"} failed`)
    return failed === 0
  }

  if (phase === "idle") {
    return (
      <Shell header={header}>
        <Centered>Open this from an MCP host to review augmentations.</Centered>
      </Shell>
    )
  }
  if (phase === "error") {
    return (
      <Shell header={header}>
        <Centered>
          <TriangleAlert className="size-5 text-destructive" />
          <div className="text-destructive">{error}</div>
        </Centered>
      </Shell>
    )
  }
  if (phase === "running") {
    const verb = progress >= 1 ? "Done" : loadingVerb(progress)
    return (
      <div className="h-screen flex items-center justify-center px-6 bg-background text-foreground">
        <div className="w-full max-w-xs space-y-4">
          <div className="text-center space-y-1.5">
            <img src={LOGO_URL} alt="Anamnesis" width={40} height={40} className="size-10 mx-auto animate-pulse" />
            <p className="text-sm font-medium">
              Augmenting {header?.patient_name ? `${header.patient_name}'s` : ""} chart
            </p>
          </div>

          <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
            <div
              className="h-full bg-primary rounded-full transition-[width] duration-200 ease-out"
              style={{ width: `${Math.round(progress * 100)}%` }}
            />
          </div>

          <p className="text-xs text-muted-foreground text-center tabular-nums">
            {verb}{startMs && progress < 1 ? ` · ${elapsedLabel(startMs)}` : ""}
          </p>
        </div>
      </div>
    )
  }

  const proposals = result?.proposals ?? []
  const pending = proposals.filter((p) => !decisions[p.id])

  const filters: FilterDef[] = [
    {
      label: "Status", value: statusFilter, onChange: setStatusFilter,
      options: [
        { value: "pending", label: "Pending", count: counts.status.pending },
        { value: "accepted", label: "Accepted", count: counts.status.accepted },
        { value: "rejected", label: "Rejected", count: counts.status.rejected },
      ],
    },
    {
      label: "Tier", value: tierFilter, onChange: setTierFilter,
      options: [
        { value: "ATTENTION", label: "Attention", count: counts.tier.ATTENTION },
        { value: "REVIEW", label: "Review", count: counts.tier.REVIEW },
        { value: "CONFIDENT", label: "Confident", count: counts.tier.CONFIDENT },
      ],
    },
    {
      label: "Type", value: typeFilter, onChange: setTypeFilter,
      options: Object.keys(RESOURCE_LABEL).map((k) => ({
        value: k, label: RESOURCE_LABEL[k], count: counts.type[k] ?? 0,
      })),
    },
    {
      label: "Classification", value: classFilter, onChange: setClassFilter,
      options: [
        { value: "NEW", label: "New", count: counts.cls.NEW },
        { value: "UPDATING", label: "Update", count: counts.cls.UPDATING },
        { value: "CONFLICTING", label: "Conflict", count: counts.cls.CONFLICTING },
      ],
    },
  ]


  return (
    <Shell header={header}>
      <div className="flex-1 min-h-0 flex">
        <div className={cn("w-full sm:w-72 sm:border-r flex flex-col min-h-0", selectedId && "hidden sm:flex")}>
          {/* Stats strip: source docs · change breakdown */}
          {result && (
            <div className="h-10 shrink-0 border-b px-3 flex items-center gap-5 text-xs tabular-nums text-muted-foreground">
              <StatChip icon={<FileText className="size-3.5" />} count={result.documents.length} label={`${result.documents.length} source documents`} />
              <StatChip icon={<FilePlusCorner className="size-3.5" />} count={counts.cls.NEW} label={`${counts.cls.NEW} new`} />
              <StatChip icon={<ClipboardPen className="size-3.5" />} count={counts.cls.UPDATING} label={`${counts.cls.UPDATING} updates`} />
              <StatChip icon={<CircleAlert className="size-3.5" />} count={counts.cls.CONFLICTING} label={`${counts.cls.CONFLICTING} conflicts`} />
            </div>
          )}

          {/* Toolbar: search + filter, or selection actions */}
          <div className="flex items-center justify-between gap-2 px-3 h-10 border-b shrink-0 select-none">
            {selectedIds.size > 0 ? (
              <>
                <span className="text-xs flex-1 text-muted-foreground">{selectedIds.size} selected</span>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => selectAllPending(filteredProposals.filter((p) => !decisions[p.id]).map((p) => p.id))}
                    className="h-6 w-6 inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-accent cursor-pointer"
                    aria-label="Select all"
                  >
                    <CheckCheck className="size-3" />
                  </button>
                  <button
                    onClick={() => allSelectedConfident ? setBulkConfirm("accept") : setError("Bulk-accept is restricted to confident proposals. Open individual items to review.")}
                    className={cn("h-6 w-6 inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-accent cursor-pointer", !allSelectedConfident && "opacity-40")}
                    aria-label="Accept selected"
                  >
                    <Stamp className="size-3" />
                  </button>
                  <button
                    onClick={() => setBulkConfirm("reject")}
                    className="h-6 w-6 inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-accent cursor-pointer"
                    aria-label="Reject selected"
                  >
                    <Ban className="size-3" />
                  </button>
                  <button
                    onClick={clearSelection}
                    className="h-6 w-6 inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-accent cursor-pointer"
                    aria-label="Clear selection"
                  >
                    <X className="size-3" />
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="relative flex-1 min-w-0 -ml-2">
                  <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
                  <Input
                    placeholder="Search proposals..."
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="pl-7 h-7 text-xs border-0 shadow-none focus-visible:ring-0 bg-transparent"
                  />
                </div>
                <FilterMenu filters={filters} />
              </>
            )}
          </div>

          {/* List */}
          <div className="flex-1 overflow-y-auto min-h-0">
            {filteredProposals.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full gap-2 px-4 text-center">
                <ClipboardList className="size-6 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">No proposals match</p>
              </div>
            ) : (
              filteredProposals.map((p) => {
                const d = decisions[p.id]
                const reviewed = !!d
                const checked = selectedIds.has(p.id)
                const ClassIcon = CLASS_ICON[p.classification] ?? ClipboardList
                const group = p.conflict_group_id
                  ? filteredProposals.filter((x) => x.conflict_group_id === p.conflict_group_id)
                  : null
                const isLastInGroup = group ? group[group.length - 1].id === p.id : true
                return (
                  <div
                    key={p.id}
                    onClick={() => setSelectedId(p.id)}
                    className={cn(
                      "group flex items-center gap-2.5 px-3 py-2 border-b transition-colors select-none cursor-pointer",
                      group && "shadow-[inset_2px_0_0_0_var(--color-amber-500)]",
                      group && !isLastInGroup && "!border-b-0",
                      selectedId === p.id ? "bg-muted" : "hover:bg-muted/50",
                    )}
                  >
                    <div className="size-4 shrink-0 flex items-center justify-center">
                      {reviewed ? (
                        d.status === "accepted"
                          ? <Check className="size-3.5 text-muted-foreground" />
                          : <X className="size-3.5 text-muted-foreground" />
                      ) : (
                        <>
                          <button
                            onClick={(e) => { e.stopPropagation(); toggleSelect(p.id) }}
                            className={cn(
                              "size-4 rounded border flex items-center justify-center cursor-pointer",
                              checked
                                ? "bg-primary border-primary text-primary-foreground"
                                : "border-input hidden group-hover:flex",
                            )}
                            aria-label={checked ? "Deselect" : "Select"}
                          >
                            {checked && <Check className="size-3" />}
                          </button>
                          {!checked && (
                            <ClassIcon className={cn("size-4 group-hover:hidden", TIER_ICON_COLOR[p.confidence_tier])} />
                          )}
                        </>
                      )}
                    </div>
                    <span className="text-sm truncate flex-1">{p.display_label}</span>
                    <span className="text-[11px] text-muted-foreground shrink-0">{RESOURCE_LABEL[p.resource_type] ?? p.resource_type}</span>
                  </div>
                )
              })
            )}
          </div>
        </div>

        <div className={cn("flex-1 min-w-0 flex flex-col", !selectedId && !bulkConfirm && "hidden sm:flex")}>
          {bulkConfirm ? (
            <BulkConfirmView
              action={bulkConfirm}
              proposals={selectedProposals.filter((p) => !decisions[p.id])}
              busy={busyId !== null}
              onCancel={() => setBulkConfirm(null)}
              onConfirm={async (reason) => {
                await bulkDecide(bulkConfirm, reason)
                setBulkConfirm(null)
              }}
            />
          ) : selected ? (
            <ProposalDetail
              key={selected.id}
              app={app}
              proposal={selected}
              proposals={allProposals}
              documents={result?.documents ?? null}
              decision={decisions[selected.id]}
              busy={busyId === selected.id}
              tab={detailTab}
              setTab={setDetailTab}
              showRaw={showRaw}
              setShowRaw={setShowRaw}
              activeDocId={activeDocId}
              setActiveDocId={setActiveDocId}
              onBack={() => setSelectedId(null)}
              onOpenSibling={(id) => setSelectedId(id)}
              onAccept={(resource) => decide(selected, "accept", resource ? { resource } : undefined)}
              onReject={(reason) => decide(selected, "reject", { reason })}
              onReopen={() => reopen(selected)}
            />
          ) : (
            <Centered>Select a proposal to review.</Centered>
          )}
        </div>
      </div>
    </Shell>
  )
}

function BulkConfirmView({
  action,
  proposals,
  busy,
  onCancel,
  onConfirm,
}: {
  action: "accept" | "reject"
  proposals: Proposal[]
  busy: boolean
  onCancel: () => void
  onConfirm: (reason?: string) => void
}) {
  const [reason, setReason] = useState("")
  const isAccept = action === "accept"
  const count = proposals.length
  const disabled = busy || (!isAccept && !reason.trim())

  return (
    <Empty className="flex-1 min-h-0">
      <EmptyHeader>
        <EmptyMedia variant="icon" className={cn(isAccept ? "text-primary" : "text-destructive")}>
          {isAccept ? <Stamp className="size-5" /> : <Ban className="size-5" />}
        </EmptyMedia>
        <EmptyTitle>{isAccept ? "Accept" : "Reject"} {count} proposal{count === 1 ? "" : "s"}</EmptyTitle>
        <EmptyDescription>
          {isAccept
            ? "Each is written to FHIR with a Provenance record naming you."
            : "The reason below applies to all and is saved to the audit log. Nothing is written to FHIR."}
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <div className="w-full max-h-44 overflow-y-auto rounded-md border divide-y text-left">
          {proposals.map((p) => (
            <div key={p.id} className="flex items-center gap-2 px-3 py-2 min-w-0">
              <span className="text-[11px] text-muted-foreground shrink-0 w-24 truncate">
                {RESOURCE_LABEL[p.resource_type] ?? p.resource_type}
              </span>
              <span className="text-sm truncate flex-1">{p.display_label}</span>
              <Badge className={cn("text-[10px] leading-none px-1.5 py-0.5 shrink-0", TIER_BADGE[p.confidence_tier])}>
                {CLASSIFICATION_LABEL[p.classification]}
              </Badge>
            </div>
          ))}
        </div>

        {!isAccept && (
          <Textarea
            autoFocus
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason for rejecting — saved to the audit log"
            className="text-sm min-h-20"
          />
        )}

        <div className="flex items-center justify-center gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={busy}>Cancel</Button>
          <Button
            size="sm"
            variant={isAccept ? "default" : "destructive"}
            disabled={disabled}
            onClick={() => onConfirm(isAccept ? undefined : reason.trim())}
          >
            {busy ? <Loader2 className="size-3.5 animate-spin" /> : isAccept ? <Stamp className="size-3.5" /> : <Ban className="size-3.5" />}
            {isAccept ? "Accept & write" : "Reject"}
          </Button>
        </div>
      </EmptyContent>
    </Empty>
  )
}

function ProposalDetail({
  app,
  proposal,
  proposals,
  documents,
  decision,
  busy,
  tab,
  setTab,
  showRaw,
  setShowRaw,
  activeDocId,
  setActiveDocId,
  onBack,
  onOpenSibling,
  onAccept,
  onReject,
  onReopen,
}: {
  app: App | null
  proposal: Proposal
  proposals: Proposal[]
  documents: SourceDocument[] | null
  decision?: Decision
  busy: boolean
  tab: "form" | "source" | "codes"
  setTab: (t: "form" | "source" | "codes") => void
  showRaw: boolean
  setShowRaw: (v: boolean | ((p: boolean) => boolean)) => void
  activeDocId: string | null
  setActiveDocId: (id: string) => void
  onBack: () => void
  onOpenSibling: (id: string) => void
  onAccept: (resource?: Record<string, unknown>) => Promise<boolean>
  onReject: (reason: string) => Promise<boolean>
  onReopen: () => void
}) {
  const [confirming, setConfirming] = useState<"accept" | "reject" | null>(null)
  const [rejectReason, setRejectReason] = useState("")
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null)
  const [edited, setEdited] = useState<Record<string, unknown> | null>(null)
  const hasSource = proposal.citations.length > 0
  const activeResource = edited ?? proposal.resource
  const effectiveTab = tab === "source" && !hasSource ? "form" : tab
  const citation = proposal.citations[0]

  const citedDocs = useMemo(() => {
    if (!documents) return []
    const ids = Array.from(new Set(proposal.citations.map((c) => c.document_id)))
    return ids.map((id) => documents.find((d) => d.id === id)).filter((d): d is SourceDocument => Boolean(d))
  }, [documents, proposal.citations])

  useEffect(() => {
    if (effectiveTab !== "source" || citedDocs.length === 0) return
    if (!activeDocId || !citedDocs.some((d) => d.id === activeDocId)) {
      setActiveDocId(citedDocs[0].id)
    }
  }, [effectiveTab, citedDocs, activeDocId, setActiveDocId])

  const activeDoc = citedDocs.find((d) => d.id === activeDocId) ?? citedDocs[0] ?? null

  // Apply a searched code into the edit draft's primary coding.
  function applyCode(coding: { system: string; code: string; display: string }) {
    if (!editing || !draft) return
    const key = draft.resourceType === "MedicationRequest" ? "medicationCodeableConcept" : "code"
    const cc = (draft[key] as Record<string, unknown> | undefined) ?? {}
    setDraft({
      ...draft,
      [key]: { ...cc, text: coding.display, coding: [{ system: coding.system, code: coding.code, display: coding.display }] },
    })
    setTab("form")
  }

  const codeQuery = (() => {
    const r = activeResource as Record<string, unknown>
    const cc = (r.medicationCodeableConcept ?? r.code) as { text?: string } | undefined
    return cc?.text || proposal.display_label
  })()

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {/* Sub-header: tabs left, contextual actions right */}
      <div className="h-10 shrink-0 border-b px-4 flex items-center gap-2 min-w-0">
        <button onClick={onBack} className="sm:hidden shrink-0 -ml-1 text-muted-foreground hover:text-foreground" aria-label="Back to list">
          <ChevronLeft className="size-4" />
        </button>
        <div className="flex items-center gap-1 shrink-0">
          <IconBtn label="Proposal" active={effectiveTab === "form"} onClick={() => setTab("form")}>
            <Form className="size-3.5" />
          </IconBtn>
          {hasSource && (
            <IconBtn label="Source document" active={effectiveTab === "source"} onClick={() => setTab("source")}>
              <FileText className="size-3.5" />
            </IconBtn>
          )}
          <IconBtn label="Search codes" active={effectiveTab === "codes"} onClick={() => setTab("codes")}>
            <BookSearch className="size-3.5" />
          </IconBtn>
        </div>

        <div className="flex-1" />

        {editing ? (
          <div className="flex items-center gap-1 shrink-0">
            <IconBtn label="Cancel" onClick={() => { setEditing(false); setDraft(null) }}>
              <X className="size-3.5" />
            </IconBtn>
            <IconBtn label="Save edits" tone="primary" onClick={() => { setEdited(draft); setEditing(false); setDraft(null) }}>
              <Check className="size-3.5" />
            </IconBtn>
          </div>
        ) : decision ? (
          decision.status === "rejected" ? (
            <IconBtn label="Reopen" onClick={onReopen}>
              <Undo2 className="size-3.5" />
            </IconBtn>
          ) : null
        ) : (
          <div className="flex items-center gap-1 shrink-0">
            <IconBtn label="Edit" onClick={() => { setDraft(activeResource); setEditing(true) }}>
              <Pencil className="size-3.5" />
            </IconBtn>
            <IconBtn label="Reject" tone="destructive" onClick={() => setConfirming("reject")}>
              <Ban className="size-3.5" />
            </IconBtn>
            <IconBtn label="Accept" tone="primary" onClick={() => setConfirming("accept")}>
              <Stamp className="size-3.5" />
            </IconBtn>
          </div>
        )}
      </div>

      {confirming ? (
        <ConfirmView
          action={confirming}
          label={proposal.display_label}
          busy={busy}
          reason={rejectReason}
          setReason={setRejectReason}
          onCancel={() => { setConfirming(null); setRejectReason("") }}
          onConfirm={async () => {
            const ok = confirming === "reject"
              ? await onReject(rejectReason.trim())
              : await onAccept(edited ?? undefined)
            if (ok) { setConfirming(null); setRejectReason("") }
          }}
        />
      ) : effectiveTab === "form" ? (
        <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-3 text-sm">
          <div className="relative pr-9">
            <div className="text-base font-semibold leading-tight">{proposal.display_label}</div>
            <div className="flex items-center gap-1 mt-0.5 text-xs">
              <span className="text-muted-foreground shrink-0">{CLASSIFICATION_LABEL[proposal.classification]}</span>
              <Dot className="text-sm" />
              {decision ? (
                <span className="text-muted-foreground shrink-0">
                  {decision.status === "accepted" ? "Accepted" : "Rejected"}
                </span>
              ) : (
                <span className={cn("shrink-0 truncate", TIER_TEXT[proposal.confidence_tier])}>
                  {TIER_LABEL[proposal.confidence_tier]}
                </span>
              )}
            </div>
            {!editing && (
              <button
                onClick={() => setShowRaw((v) => !v)}
                className={cn("absolute -top-1 right-0 h-7 w-7 inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-accent cursor-pointer", showRaw && "bg-muted")}
                aria-label={showRaw ? "Show fields" : "Show raw FHIR"}
              >
                <Braces className="size-3.5" />
              </button>
            )}
          </div>

          {!editing && !decision && proposal.conflict_group_id && (
            <InterProposalConflictCallout
              current={proposal}
              proposals={proposals}
              onOpenSibling={onOpenSibling}
            />
          )}
          {!editing && !decision && (proposal.classification === "CONFLICTING" || proposal.classification === "UPDATING") && (
            <ProposalConflictCallout
              proposed={proposal.resource}
              matches={proposal.chart_matches}
              mode={proposal.classification}
            />
          )}

          {editing && draft ? (
            <ProposalFormView resource={draft} mode="edit" onChange={setDraft} />
          ) : showRaw ? (
            <pre className="text-xs font-mono leading-relaxed whitespace-pre-wrap break-words rounded-md border bg-muted/40 p-3">
              {JSON.stringify(activeResource, null, 2)}
            </pre>
          ) : (
            <ProposalFormView resource={activeResource} source={citation?.text} />
          )}

          {!editing && !decision && (
            <ReasoningSections
              extraction={proposal.extraction_reasoning}
              classification={proposal.classification_reasoning}
              classificationKind={proposal.classification}
              merge={proposal.merge_reasoning}
              flags={proposal.flags}
              breakdown={proposal.confidence_breakdown}
            />
          )}

          {!editing && decision?.status === "accepted" && decision.provenance && (
            <div className="pt-2">
              <ProvenanceCard resource={decision.provenance} />
            </div>
          )}
        </div>
      ) : effectiveTab === "codes" ? (
        <CodeSearch
          app={app}
          initialQuery={codeQuery}
          initialSystem={systemForResource(activeResource)}
          onApply={editing ? applyCode : undefined}
        />
      ) : (
        <div className="flex-1 min-h-0 flex flex-col">
          {activeDoc && (
            <div className="h-10 shrink-0 border-b px-4 flex items-center gap-2 min-w-0">
              <NotesHeader
                activeDoc={activeDoc}
                docs={citedDocs}
                activeDocId={activeDocId}
                setActiveDocId={setActiveDocId}
              />
            </div>
          )}
          <NoteReader
            key={`${proposal.id}:${activeDoc?.id ?? ""}`}
            document={activeDoc}
            citations={proposal.citations.filter((c) => c.document_id === activeDoc?.id)}
          />
        </div>
      )}
    </div>
  )
}

function ConfirmView({
  action,
  label,
  busy,
  reason,
  setReason,
  onCancel,
  onConfirm,
}: {
  action: "accept" | "reject"
  label: string
  busy: boolean
  reason: string
  setReason: (v: string) => void
  onCancel: () => void
  onConfirm: () => void
}) {
  const isAccept = action === "accept"
  return (
    <Empty className="flex-1 min-h-0">
      <EmptyHeader>
        <EmptyMedia variant="icon" className={cn(isAccept ? "text-primary" : "text-destructive")}>
          {isAccept ? <Stamp className="size-5" /> : <Ban className="size-5" />}
        </EmptyMedia>
        <EmptyTitle>{isAccept ? "Accept proposal" : "Reject proposal"}</EmptyTitle>
        <EmptyDescription>
          {isAccept
            ? <>Writes <span className="font-medium text-foreground">{label}</span> to FHIR with a Provenance record naming you.</>
            : <>Records a reject decision for <span className="font-medium text-foreground">{label}</span> in the audit log. Nothing is written to FHIR.</>}
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        {!isAccept && (
          <Textarea
            autoFocus
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason for rejecting — saved to the audit log"
            className="text-sm min-h-20"
          />
        )}
        <div className="flex items-center justify-center gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={busy}>Cancel</Button>
          <Button
            size="sm"
            variant={isAccept ? "default" : "destructive"}
            disabled={busy || (!isAccept && !reason.trim())}
            onClick={onConfirm}
          >
            {busy ? <Loader2 className="size-3.5 animate-spin" /> : isAccept ? <Stamp className="size-3.5" /> : <Ban className="size-3.5" />}
            {isAccept ? "Accept & write" : "Reject"}
          </Button>
        </div>
      </EmptyContent>
    </Empty>
  )
}

function StatChip({
  icon,
  count,
  label,
  className,
}: {
  icon: React.ReactNode
  count: number
  label: string
  className?: string
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={cn("shrink-0 flex items-center gap-1.5 cursor-default", count === 0 && "opacity-40", className)}>
          {icon}{count}
        </span>
      </TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  )
}

function IconBtn({
  children,
  label,
  onClick,
  disabled,
  active,
  tone = "default",
}: {
  children: React.ReactNode
  label: string
  onClick?: () => void
  disabled?: boolean
  active?: boolean
  tone?: "default" | "primary" | "destructive"
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          onClick={onClick}
          disabled={disabled}
          aria-label={label}
          className={cn(
            "h-7 w-7 inline-flex items-center justify-center rounded-md cursor-pointer transition-colors disabled:opacity-50",
            tone === "default" && "text-muted-foreground hover:bg-accent hover:text-foreground",
            tone === "primary" && "text-primary hover:bg-primary/10",
            tone === "destructive" && "text-muted-foreground hover:bg-destructive/10 hover:text-destructive",
            active && "bg-muted text-foreground",
          )}
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  )
}

function ageFromDob(dob: string | null | undefined): string {
  if (!dob) return ""
  const d = new Date(dob)
  if (isNaN(d.getTime())) return ""
  const now = new Date()
  let age = now.getFullYear() - d.getFullYear()
  const m = now.getMonth() - d.getMonth()
  if (m < 0 || (m === 0 && now.getDate() < d.getDate())) age--
  return String(age)
}

function formatDob(dob: string | null | undefined): string {
  if (!dob) return ""
  const d = new Date(dob)
  if (isNaN(d.getTime())) return dob
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
}

function Shell({
  header,
  children,
}: {
  header: PatientHeader | null
  children: React.ReactNode
}) {
  return (
    <div className="h-screen p-3 sm:p-4 bg-background text-foreground">
      <div className="h-full max-w-5xl mx-auto flex flex-col bg-background rounded-xl border shadow-sm overflow-hidden">
        <div className="flex items-center gap-3 px-4 h-10 border-b shrink-0">
          <img src={LOGO_URL} alt="Anamnesis" width={24} height={24} className="size-6 shrink-0 -ml-2" />
          <div className="min-w-0 flex items-baseline gap-2 text-xs">
            <span className="text-sm font-semibold shrink-0 -ml-1">{header?.patient_name ?? "Patient"}</span>
            {(() => {
              const age = ageFromDob(header?.birth_date)
              const sex = header?.sex ? header.sex[0].toUpperCase() : ""
              const agesex = `${age}${sex}`
              return agesex ? <span className="text-muted-foreground shrink-0">{agesex}</span> : null
            })()}
            {header?.birth_date && <Dot className="relative top-px" />}
            {header?.birth_date && <span className="text-muted-foreground shrink-0">DOB {formatDob(header.birth_date)}</span>}
            {header?.mrn && <Dot className="relative top-px" />}
            {header?.mrn && <span className="text-muted-foreground tabular-nums truncate">MRN {header.mrn}</span>}
          </div>
          <div className="ml-auto shrink-0">
            <IconBtn label="Settings" onClick={() => {}}>
              <Settings className="size-3.5" />
            </IconBtn>
          </div>
        </div>
        {children}
      </div>
    </div>
  )
}

function Dot({ className }: { className?: string }) {
  return <span className={cn("text-lg leading-none text-muted-foreground/50 shrink-0", className)}>·</span>
}

function relativeTime(ms: number): string {
  const s = Math.floor((Date.now() - ms) / 1000)
  if (s < 5) return "just now"
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  return `${h}h ago`
}

function systemForResource(r: Record<string, unknown>): string {
  switch (r.resourceType) {
    case "MedicationRequest": return "rxnorm"
    case "Observation": return "loinc"
    default: return "snomed"
  }
}

function shortDate(iso: string | null | undefined): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })
}

function NotesHeader({
  activeDoc,
  docs,
  activeDocId,
  setActiveDocId,
}: {
  activeDoc: SourceDocument
  docs: SourceDocument[]
  activeDocId: string | null
  setActiveDocId: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const meta = [shortDate(activeDoc.date), activeDoc.author].filter(Boolean).join(" · ")
  const hasMany = docs.length > 1

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])

  if (!hasMany) {
    return (
      <div className="flex-1 min-w-0 flex items-baseline gap-2">
        <span className="text-sm font-medium truncate">{activeDoc.type || "Document"}</span>
        {meta && <span className="ml-auto text-[11px] text-muted-foreground truncate shrink-0">{meta}</span>}
      </div>
    )
  }

  return (
    <div className="flex-1 min-w-0 flex items-baseline gap-2" ref={ref}>
      <div className="relative min-w-0">
        <button
          onClick={() => setOpen((o) => !o)}
          className="inline-flex items-baseline gap-1 text-sm font-medium truncate cursor-pointer hover:opacity-80 outline-none max-w-full"
        >
          <span className="truncate">{activeDoc.type || "Document"}</span>
          <ChevronDown className="size-3 self-center text-muted-foreground shrink-0" />
        </button>
        {open && (
          <div className="absolute left-0 top-7 z-20 min-w-[240px] rounded-md border bg-card text-card-foreground shadow-md py-1">
            {docs.map((d) => {
              const label = [d.type, shortDate(d.date), d.author].filter(Boolean).join(" · ")
              return (
                <button
                  key={d.id}
                  onClick={() => { setActiveDocId(d.id); setOpen(false) }}
                  className="w-full flex items-center px-2 py-1.5 text-xs hover:bg-accent cursor-pointer"
                >
                  <span className="truncate flex-1 text-left">{label || d.id}</span>
                  {d.id === activeDocId && <Check className="size-3 ml-2 text-muted-foreground" />}
                </button>
              )
            })}
          </div>
        )}
      </div>
      {meta && <span className="ml-auto text-[11px] text-muted-foreground truncate shrink-0">{meta}</span>}
    </div>
  )
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-2 px-6 text-center text-sm text-muted-foreground">
      {children}
    </div>
  )
}

interface FilterDef {
  label: string
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string; count: number }[]
}

function FilterMenu({ filters }: { filters: FilterDef[] }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const hasActive = filters.some((f) => f.value !== "")

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "h-6 w-6 inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-accent cursor-pointer",
          hasActive && "bg-accent",
        )}
        aria-label="Filter"
      >
        <ListFilter className="size-3" />
      </button>
      {open && (
        <div className="absolute right-0 top-7 z-20 w-44 max-h-80 overflow-y-auto rounded-md border bg-card text-card-foreground shadow-md py-1 text-sm">
          <button
            onClick={() => { filters.forEach((f) => f.onChange("")); setOpen(false) }}
            className={cn("w-full text-left px-2 py-1.5 hover:bg-accent cursor-pointer", !hasActive && "bg-accent")}
          >
            All
          </button>
          {filters.map((f) => (
            <div key={f.label}>
              <div className="px-2 pt-2 pb-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">
                {f.label}
              </div>
              {f.options.map((o) => (
                <button
                  key={o.value}
                  onClick={() => { f.onChange(f.value === o.value ? "" : o.value); setOpen(false) }}
                  className={cn("w-full flex items-center px-2 py-1.5 hover:bg-accent cursor-pointer", f.value === o.value && "bg-accent")}
                >
                  <span className="flex-1 truncate text-left">{o.label}</span>
                  <span className="text-xs text-muted-foreground ml-2">{o.count}</span>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
