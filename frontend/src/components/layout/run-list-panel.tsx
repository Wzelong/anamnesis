"use client"

import { useEffect, useState } from "react"
import { useRouter, usePathname } from "next/navigation"
import { PanelLeftClose, PanelLeftOpen, ClipboardList, Search, RefreshCw } from "lucide-react"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useAppStore } from "@/lib/store"
import type { Run } from "@/lib/types"

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

function formatDate(iso: string | null) {
  if (!iso) return ""
  const d = new Date(iso)
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
}

export function RunListPanel() {
  const runs = useAppStore((s) => s.runs)
  const runsLoading = useAppStore((s) => s.runsLoading)
  const fetchRuns = useAppStore((s) => s.fetchRuns)
  const panelOpen = useAppStore((s) => s.runPanelOpen)
  const togglePanel = useAppStore((s) => s.toggleRunPanel)
  const router = useRouter()
  const pathname = usePathname()

  const [search, setSearch] = useState("")
  const [contentVisible, setContentVisible] = useState(panelOpen)
  const [spinning, setSpinning] = useState(false)

  const handleRefresh = async () => {
    setSpinning(true)
    await fetchRuns()
    setTimeout(() => setSpinning(false), 1000)
  }

  useEffect(() => {
    if (panelOpen) {
      const t = setTimeout(() => setContentVisible(true), 200)
      return () => clearTimeout(t)
    }
    setContentVisible(false)
  }, [panelOpen])

  const activeRunId = pathname === "/" ? null : pathname.split("/")[1]

  const filtered = search.trim()
    ? runs.filter((r) => {
        const q = search.trim().toLowerCase()
        return r.id.includes(q)
          || (r.patient_id ?? "").toLowerCase().includes(q)
          || (r.patient_name ?? "").toLowerCase().includes(q)
      })
    : runs

  return (
    <aside
      className={cn(
        "shrink-0 overflow-hidden transition-[width] duration-200 ease-out flex flex-col",
        panelOpen ? "w-[260px] border-r" : "w-[40px]",
      )}
    >
      <div className={cn("h-11 px-2 shrink-0 flex items-center gap-0.5 select-none", panelOpen && "border-b")}>
        <div className={cn("flex items-center gap-0.5 flex-1 min-w-0", !contentVisible && "hidden")}>
          <div className="relative flex-1 min-w-0 ml-1">
            <Search className="absolute left-0 top-[7px] size-3 text-muted-foreground" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search..."
              className="pl-[18px] h-6 text-xs w-full bg-transparent outline-none placeholder:text-muted-foreground"
            />
          </div>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="size-6 flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted cursor-pointer"
                onClick={handleRefresh}
              >
                <RefreshCw className={cn("size-3.5", spinning && "animate-spin")} />
              </button>
            </TooltipTrigger>
            <TooltipContent>Refresh</TooltipContent>
          </Tooltip>
        </div>
        <button
          type="button"
          className="size-6 flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted cursor-pointer ml-auto"
          onClick={togglePanel}
        >
          {panelOpen ? <PanelLeftClose className="size-3.5" /> : <PanelLeftOpen className="size-3.5" />}
        </button>
      </div>

      <div className={cn("flex-1 overflow-y-auto", !contentVisible && "hidden")}>
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-2 px-4">
            <ClipboardList className="size-6 text-muted-foreground" />
            <p className="text-xs text-muted-foreground">
              {search.trim() ? "No matching runs" : "No runs yet"}
            </p>
          </div>
        ) : (
          filtered.map((run: Run) => (
            <button
              key={run.id}
              type="button"
              onClick={() => router.push(`/${run.id}`)}
              className={cn(
                "w-full text-left px-3 py-2.5 transition-colors cursor-pointer",
                activeRunId === run.id ? "bg-muted/70" : "hover:bg-muted/50",
              )}
            >
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="text-sm font-medium truncate flex-1">
                  {run.patient_name ?? `Patient ${(run.patient_id ?? run.id).slice(0, 8)}...`}
                </span>
                <Badge variant={STATUS_VARIANT[run.status]} className="text-[10px] px-1 py-0 shrink-0">
                  {STATUS_LABEL[run.status]}
                </Badge>
              </div>
              <div className="text-xs text-muted-foreground mt-0.5">
                {run.total_proposals} proposals · {formatDate(run.started_at)}
              </div>
            </button>
          ))
        )}
      </div>
    </aside>
  )
}
