"use client"

import { useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import {
  ArrowLeft,
  Ban,
  Check,
  ClipboardList,
  ListChecks,
  Stamp,
  X,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { DataList } from "@/components/ui/data-list"
import type { BulkAction, FilterConfig } from "@/components/ui/data-list-types"
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
import { toast } from "sonner"
import { useAppStore } from "@/lib/store"
import type { Proposal } from "@/lib/types"
import {
  CLASSIFICATION_LABEL,
  CLASSIFICATION_VARIANT,
  RESOURCE_ICON,
  RESOURCE_LABEL,
  TIER_DOT,
} from "@/lib/proposal-meta"
import { RunStatsItems, RunStatsStrip } from "./run-stats-strip"

type StatusFilter = "" | "pending" | "accepted" | "rejected"
type TierFilter = "" | "ATTENTION" | "REVIEW" | "CONFIDENT"
type TypeFilter = "" | keyof typeof RESOURCE_LABEL
type ClassFilter = "" | "NEW" | "UPDATING" | "CONFLICTING"

export function ProposalListPanel() {
  const router = useRouter()
  const proposals = useAppStore((s) => s.proposals)
  const selectedId = useAppStore((s) => s.selectedId)
  const runId = useAppStore((s) => s.runId)
  const runs = useAppStore((s) => s.runs)
  const currentRun = useMemo(() => runs.find((r) => r.id === runId), [runs, runId])
  const selectedProposalIds = useAppStore((s) => s.selectedProposalIds)
  const toggleProposalSelection = useAppStore((s) => s.toggleProposalSelection)
  const selectAllProposals = useAppStore((s) => s.selectAllProposals)
  const clearProposalSelection = useAppStore((s) => s.clearProposalSelection)
  const bulkAcceptSelected = useAppStore((s) => s.bulkAcceptSelected)
  const bulkRejectSelected = useAppStore((s) => s.bulkRejectSelected)

  const [search, setSearch] = useState("")
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("")
  const [tierFilter, setTierFilter] = useState<TierFilter>("")
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("")
  const [classFilter, setClassFilter] = useState<ClassFilter>("")
  const [rejectOpen, setRejectOpen] = useState(false)
  const [rejectReason, setRejectReason] = useState("")

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    const tierRank: Record<string, number> = { ATTENTION: 0, REVIEW: 1, CONFIDENT: 2 }
    return proposals
      .filter((p) => {
        if (statusFilter && p.status !== statusFilter) return false
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
  }, [proposals, search, statusFilter, tierFilter, typeFilter, classFilter])

  const counts = useMemo(() => {
    const status: Record<string, number> = { pending: 0, accepted: 0, rejected: 0 }
    const tier: Record<string, number> = { ATTENTION: 0, REVIEW: 0, CONFIDENT: 0 }
    const type: Record<string, number> = {}
    const cls: Record<string, number> = { NEW: 0, UPDATING: 0, CONFLICTING: 0 }
    for (const p of proposals) {
      status[p.status] = (status[p.status] ?? 0) + 1
      tier[p.confidence_tier] = (tier[p.confidence_tier] ?? 0) + 1
      type[p.resource_type] = (type[p.resource_type] ?? 0) + 1
      cls[p.classification] = (cls[p.classification] ?? 0) + 1
    }
    return { status, tier, type, cls }
  }, [proposals])


  const filters: FilterConfig[] = [
    {
      type: "submenu",
      label: "Status",
      value: statusFilter || null,
      options: [
        { value: "pending", label: "Pending", count: counts.status.pending },
        { value: "accepted", label: "Accepted", count: counts.status.accepted },
        { value: "rejected", label: "Rejected", count: counts.status.rejected },
      ],
      onChange: (v) => setStatusFilter((v as StatusFilter) || ""),
    },
    {
      type: "submenu",
      label: "Tier",
      value: tierFilter || null,
      options: [
        { value: "ATTENTION", label: "Attention", count: counts.tier.ATTENTION },
        { value: "REVIEW", label: "Review", count: counts.tier.REVIEW },
        { value: "CONFIDENT", label: "Confident", count: counts.tier.CONFIDENT },
      ],
      onChange: (v) => setTierFilter((v as TierFilter) || ""),
    },
    {
      type: "submenu",
      label: "Type",
      value: typeFilter || null,
      options: Object.keys(RESOURCE_LABEL).map((k) => ({
        value: k,
        label: RESOURCE_LABEL[k],
        count: counts.type[k] ?? 0,
      })),
      onChange: (v) => setTypeFilter((v as TypeFilter) || ""),
    },
    {
      type: "submenu",
      label: "Classification",
      value: classFilter || null,
      options: [
        { value: "NEW", label: "New", count: counts.cls.NEW },
        { value: "UPDATING", label: "Update", count: counts.cls.UPDATING },
        { value: "CONFLICTING", label: "Conflict", count: counts.cls.CONFLICTING },
      ],
      onChange: (v) => setClassFilter((v as ClassFilter) || ""),
    },
  ]

  const tokenValid = useAppStore((s) => s.tokenValid)
  const locked = tokenValid !== true
  const lockedMessage = tokenValid === null
    ? "Verifying access…"
    : "Open this run from the deep link to enable actions."

  const selectedProposals = useMemo(() => {
    const tierRank: Record<string, number> = { ATTENTION: 0, REVIEW: 1, CONFIDENT: 2 }
    return [...selectedProposalIds]
      .map((id) => proposals.find((p) => p.id === id))
      .filter((p): p is Proposal => Boolean(p))
      .sort((a, b) => {
        const t = (tierRank[a.confidence_tier] ?? 99) - (tierRank[b.confidence_tier] ?? 99)
        if (t !== 0) return t
        return a.resource_type.localeCompare(b.resource_type)
      })
  }, [selectedProposalIds, proposals])

  const allSelectedConfident =
    selectedProposals.length > 0 &&
    selectedProposals.every((p) => p.confidence_tier === "CONFIDENT")

  const bulkActions: BulkAction[] = [
    {
      icon: <Stamp className={cn("size-3", (!allSelectedConfident || locked) && "opacity-40")} />,
      onClick: () => {
        if (locked) {
          toast.error(lockedMessage)
          return
        }
        if (!allSelectedConfident) {
          toast.error("Bulk-accept is restricted to confident proposals. Open individual items to review.")
          return
        }
        bulkAcceptSelected()
      },
      ariaLabel: "Accept selected",
    },
    {
      icon: <Ban className={cn("size-3", locked && "opacity-40")} />,
      onClick: () => {
        if (locked) {
          toast.error(lockedMessage)
          return
        }
        setRejectOpen(true)
      },
      ariaLabel: "Reject selected",
    },
  ]

  return (
    <>
      <aside
        className={cn(
          "shrink-0 lg:w-[280px] flex-1 lg:flex-none border-r flex-col h-full min-h-0 overflow-hidden",
          selectedId ? "hidden lg:flex" : "flex",
        )}
      >
        <div className="h-11 shrink-0 border-b px-3 flex items-center gap-2 min-w-0 lg:hidden">
          <ArrowLeft
            className="size-3.5 text-muted-foreground hover:text-foreground cursor-pointer shrink-0"
            onClick={() => router.push("/")}
            aria-label="Back to runs"
          />
          <span className="text-sm font-medium truncate flex-1 min-w-0">
            {currentRun?.patient_name ?? (runId ? `Run ${runId.slice(0, 8)}` : "")}
          </span>
          <div className="flex items-center gap-3 shrink-0 text-[11px] text-muted-foreground tabular-nums">
            <RunStatsItems run={currentRun} />
          </div>
        </div>
        <DataList
          data={filtered}
          getItemId={(p) => p.id}
          renderItem={(p) => {
            const Icon = RESOURCE_ICON[p.resource_type] ?? ClipboardList
            const reviewed = p.status !== "pending"
            return (
              <div className="flex items-center gap-2 min-w-0">
                <span className="size-3 shrink-0 inline-flex items-center justify-center text-muted-foreground">
                  {reviewed ? (
                    p.status === "accepted"
                      ? <Check className="size-3 -ml-1" />
                      : <X className="size-3 -ml-1" />
                  ) : (
                    <span
                      className={cn("size-1.5 rounded-full", TIER_DOT[p.confidence_tier])}
                      aria-hidden
                    />
                  )}
                </span>
                <Icon className={cn("size-3 text-muted-foreground shrink-0", reviewed && "-ml-0.5")} />
                <span className="text-sm truncate flex-1">{p.display_label}</span>
                {reviewed ? (
                  <span className="text-[10px] px-1 py-0 shrink-0 text-muted-foreground">
                    {p.status === "accepted" ? "Accepted" : "Rejected"}
                  </span>
                ) : (
                  <Badge
                    variant={CLASSIFICATION_VARIANT[p.classification]}
                    className="text-[10px] px-1 py-0 shrink-0"
                  >
                    {CLASSIFICATION_LABEL[p.classification]}
                  </Badge>
                )}
              </div>
            )
          }}
          searchPlaceholder="Search proposals..."
          searchValue={search}
          onSearchChange={setSearch}
          searchDebounceMs={250}
          filters={filters}
          virtualized
          activeId={selectedId ?? undefined}
          selectedIds={selectedProposalIds}
          onSelectAll={() => selectAllProposals(filtered.filter((p) => p.status === "pending").map((p) => p.id))}
          onSelectOne={toggleProposalSelection}
          onClearSelection={clearProposalSelection}
          isItemSelectable={(p: Proposal) => p.status === "pending"}
          bulkActions={bulkActions}
          onItemClick={(p: Proposal) => runId && router.push(`/${runId}/${p.id}`)}
          emptyState={{
            icon: <ListChecks className="size-6 text-muted-foreground" />,
            message: "No proposals match",
          }}
          headerExtra={<RunStatsStrip run={currentRun} />}
        />
      </aside>

      <AlertDialog open={rejectOpen} onOpenChange={setRejectOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Reject {selectedProposals.length} proposal{selectedProposals.length === 1 ? "" : "s"}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              The reason below applies to all selected proposals and is saved to the audit log.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="border rounded-md max-h-56 overflow-y-auto divide-y">
            {selectedProposals.map((p) => {
              const Icon = RESOURCE_ICON[p.resource_type] ?? ClipboardList
              return (
                <div key={p.id} className="flex items-center gap-2 px-2 py-1.5 min-w-0">
                  <span
                    className={cn("size-1.5 rounded-full shrink-0", TIER_DOT[p.confidence_tier])}
                    aria-hidden
                  />
                  <Icon className="size-3 text-muted-foreground shrink-0" />
                  <span className="text-sm truncate flex-1">{p.display_label}</span>
                  <Badge
                    variant={CLASSIFICATION_VARIANT[p.classification]}
                    className="text-[10px] px-1 py-0 shrink-0"
                  >
                    {CLASSIFICATION_LABEL[p.classification]}
                  </Badge>
                </div>
              )
            })}
          </div>
          <textarea
            autoFocus
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            placeholder="Reason"
            className="w-full text-sm border rounded-md p-2 min-h-20 outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={!rejectReason.trim()}
              onClick={async () => {
                await bulkRejectSelected(rejectReason.trim())
                setRejectReason("")
                setRejectOpen(false)
              }}
            >
              Reject
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
