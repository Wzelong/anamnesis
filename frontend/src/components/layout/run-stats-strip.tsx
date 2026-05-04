"use client"

import { ClipboardList, Clock, DollarSign, FileText } from "lucide-react"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import type { Run } from "@/lib/types"

function formatDuration(ms: number | null) {
  if (ms == null) return null
  if (ms < 1000) return `${ms}ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const rem = Math.round(s - m * 60)
  return `${m}m ${rem}s`
}

function formatCost(usd: number) {
  if (usd === 0) return "$0"
  if (usd < 0.01) return "<$0.01"
  return `$${usd.toFixed(2)}`
}

interface StatItem {
  icon?: React.ReactNode
  value: string
  tooltip: string
}

function buildItems(run: Run): StatItem[] {
  const items: StatItem[] = []
  if (run.total_documents > 0) {
    items.push({
      icon: <FileText className="size-3" />,
      value: `${run.total_documents}`,
      tooltip: `${run.total_documents} ${run.total_documents === 1 ? "document" : "documents"} processed`,
    })
  }
  if (run.total_proposals > 0) {
    items.push({
      icon: <ClipboardList className="size-3" />,
      value: `${run.total_proposals}`,
      tooltip: `${run.total_proposals} ${run.total_proposals === 1 ? "proposal" : "proposals"} generated`,
    })
  }
  const duration = formatDuration(run.duration_ms)
  if (duration) {
    items.push({ icon: <Clock className="size-3" />, value: duration, tooltip: "Processing time" })
  }
  if (run.total_cost_usd > 0) {
    items.push({
      icon: <DollarSign className="size-3 -mr-1" />,
      value: formatCost(run.total_cost_usd).replace(/^\$/, ""),
      tooltip: `Estimated cost ($${run.total_cost_usd.toFixed(4)})`,
    })
  }
  return items
}

export function RunStatsItems({ run }: { run: Run | null | undefined }) {
  if (!run) return null
  const items = buildItems(run)
  if (items.length === 0) return null
  return (
    <>
      {items.map((item) => (
        <Tooltip key={item.tooltip}>
          <TooltipTrigger asChild>
            <span className="flex items-center gap-1 shrink-0 cursor-default">
              {item.icon}
              <span>{item.value}</span>
            </span>
          </TooltipTrigger>
          <TooltipContent side="bottom"><p>{item.tooltip}</p></TooltipContent>
        </Tooltip>
      ))}
    </>
  )
}

export function RunStatsStrip({ run }: { run: Run | null | undefined }) {
  if (!run) return null
  const items = buildItems(run)
  if (items.length === 0) return null
  return (
    <div className="hidden lg:flex h-8 shrink-0 border-b px-3 items-center gap-3 text-[11px] text-muted-foreground tabular-nums overflow-x-auto">
      <RunStatsItems run={run} />
    </div>
  )
}
