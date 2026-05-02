"use client"

import { useEffect, useState } from "react"
import { useRouter, usePathname } from "next/navigation"
import { ClipboardList, PanelLeftClose, PanelLeftOpen, RefreshCw, Trash2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { DataList } from "@/components/ui/data-list"
import type { BulkAction, ToolbarButton } from "@/components/ui/data-list-types"
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
import { useAppStore, useRunPanelOpen, useToggleRunPanel } from "@/lib/store"

const STATUS_VARIANT: Record<string, "destructive" | "secondary" | "default" | "outline"> = {
  pending: "outline",
  in_review: "secondary",
  resolved: "default",
  empty: "outline",
}

const STATUS_LABEL: Record<string, string> = {
  pending: "Pending",
  in_review: "In review",
  resolved: "Resolved",
  empty: "Empty",
}

function formatTimeAgo(iso: string | null) {
  if (!iso) return ""
  const d = new Date(iso)
  const now = new Date()
  const s = Math.max(0, Math.floor((now.getTime() - d.getTime()) / 1000))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h`
  const days = Math.floor(h / 24)
  if (days < 7) return `${days}d`
  const sameYear = d.getFullYear() === now.getFullYear()
  return d.toLocaleDateString(undefined, sameYear
    ? { month: "short", day: "numeric" }
    : { month: "short", day: "numeric", year: "numeric" })
}

export function RunListPanel() {
  const runs = useAppStore((s) => s.runs)
  const fetchRuns = useAppStore((s) => s.fetchRuns)
  const selectedRunIds = useAppStore((s) => s.selectedRunIds)
  const toggleRunSelection = useAppStore((s) => s.toggleRunSelection)
  const selectAllRuns = useAppStore((s) => s.selectAllRuns)
  const clearRunSelection = useAppStore((s) => s.clearRunSelection)
  const deleteSelectedRuns = useAppStore((s) => s.deleteSelectedRuns)
  const panelOpen = useRunPanelOpen()
  const togglePanel = useToggleRunPanel()
  const router = useRouter()
  const pathname = usePathname()

  const [search, setSearch] = useState("")
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [spinning, setSpinning] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const handleRefresh = async () => {
    setSpinning(true)
    await fetchRuns()
    setTimeout(() => setSpinning(false), 800)
  }

  useEffect(() => { setPage(1) }, [search])

  const activeRunId = pathname === "/" ? undefined : pathname.split("/")[1]

  const filtered = search.trim()
    ? runs.filter((r) => {
        const q = search.trim().toLowerCase()
        return r.id.includes(q)
          || (r.patient_id ?? "").toLowerCase().includes(q)
          || (r.patient_name ?? "").toLowerCase().includes(q)
      })
    : runs

  const start = (page - 1) * pageSize
  const paged = filtered.slice(start, start + pageSize)

  const toolbarButtons: ToolbarButton[] = [
    {
      icon: <RefreshCw className={cn("size-3", spinning && "animate-spin")} />,
      onClick: handleRefresh,
      ariaLabel: "Refresh",
    },
    {
      icon: <PanelLeftClose className="size-3" />,
      onClick: togglePanel,
      ariaLabel: "Collapse",
    },
  ]

  const bulkActions: BulkAction[] = [
    {
      icon: <Trash2 className="size-3" />,
      onClick: () => setConfirmOpen(true),
      ariaLabel: "Delete selected",
    },
  ]

  const isRoot = pathname === "/"

  return (
    <>
      <aside
        className={cn(
          "shrink-0 w-[40px] flex-col border-r hidden lg:flex",
          panelOpen && "xl:hidden",
          isRoot && "lg:hidden",
        )}
      >
        <div className="h-11 flex items-center justify-center">
          <button
            type="button"
            onClick={togglePanel}
            className="size-6 flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted cursor-pointer"
            aria-label="Expand"
          >
            <PanelLeftOpen className="size-3.5" />
          </button>
        </div>
      </aside>

      <aside
        className={cn(
          "shrink-0 lg:w-[260px] border-r flex-col",
          isRoot ? "flex flex-1 lg:flex-none" : (panelOpen ? "hidden xl:flex" : "hidden"),
        )}
      >
        <DataList
          data={paged}
          getItemId={(r) => r.id}
          renderItem={(run) => {
            const needReview =
              (run.pending_by_tier?.ATTENTION ?? 0) + (run.pending_by_tier?.REVIEW ?? 0)
            return (
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm truncate flex-1">
                    {run.patient_name ?? `Patient ${(run.patient_id ?? run.id).slice(0, 8)}`}
                  </span>
                  <Badge variant={STATUS_VARIANT[run.status]} className="text-[10px] px-1 py-0 shrink-0">
                    {STATUS_LABEL[run.status]}
                  </Badge>
                </div>
                <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                  <span className="flex-1 min-w-0 truncate">
                    {needReview > 0
                      ? `${needReview} of ${run.total_proposals} need review`
                      : `${run.total_proposals} proposals`}
                  </span>
                  <span className="tabular-nums shrink-0 text-muted-foreground/70">
                    {formatTimeAgo(run.started_at)}
                  </span>
                </div>
              </div>
            )
          }}
          searchPlaceholder="Search runs..."
          searchValue={search}
          onSearchChange={setSearch}
          pagination={{
            currentPage: page,
            pageSize,
            totalItems: filtered.length,
            onPageChange: setPage,
            onPageSizeChange: setPageSize,
          }}
          activeId={activeRunId}
          selectedIds={selectedRunIds}
          onSelectAll={() => selectAllRuns(paged.map((r) => r.id))}
          onSelectOne={toggleRunSelection}
          onClearSelection={clearRunSelection}
          toolbarButtons={toolbarButtons}
          bulkActions={bulkActions}
          onItemClick={(r) => router.push(`/${r.id}`)}
          emptyState={{
            icon: <ClipboardList className="size-6 text-muted-foreground" />,
            message: search.trim() ? "No matching runs" : "No runs yet",
          }}
        />
      </aside>

      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {selectedRunIds.size} run{selectedRunIds.size === 1 ? "" : "s"}?</AlertDialogTitle>
            <AlertDialogDescription>
              This removes the runs and their proposals from the working DB. FHIR resources already written are unaffected.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                const willDelete = new Set(selectedRunIds)
                await deleteSelectedRuns()
                setConfirmOpen(false)
                if (activeRunId && willDelete.has(activeRunId)) {
                  router.push("/")
                }
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
