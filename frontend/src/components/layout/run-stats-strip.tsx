"use client"

import { Clock, FileText, Sparkle, Wallet } from "lucide-react"
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

function formatTokens(n: number) {
  if (n < 1000) return `${n}`
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`
  return `${(n / 1_000_000).toFixed(1)}M`
}

function formatCost(usd: number) {
  if (usd === 0) return "$0"
  if (usd < 0.01) return `<$0.01`
  return `$${usd.toFixed(2)}`
}

interface StatItem {
  icon: React.ReactNode
  value: string
  label: string
}

function buildItems(run: Run): StatItem[] {
  const items: StatItem[] = []
  const duration = formatDuration(run.duration_ms)
  if (duration) {
    items.push({
      icon: <Clock className="size-3" />,
      value: duration,
      label: "Processing time",
    })
  }
  if (run.total_documents > 0) {
    items.push({
      icon: <FileText className="size-3" />,
      value: `${run.total_documents}`,
      label: `Documents processed (${run.total_documents})`,
    })
  }
  if (run.total_tokens > 0) {
    items.push({
      icon: <Sparkle className="size-3" />,
      value: formatTokens(run.total_tokens),
      label: `Total tokens (${run.total_tokens.toLocaleString()})`,
    })
  }
  if (run.total_cost_usd > 0) {
    items.push({
      icon: <Wallet className="size-3" />,
      value: formatCost(run.total_cost_usd),
      label: `Estimated cost ($${run.total_cost_usd.toFixed(4)})`,
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
        <Tooltip key={item.label}>
          <TooltipTrigger asChild>
            <div className="flex items-center gap-1 shrink-0 cursor-default">
              {item.icon}
              <span>{item.value}</span>
            </div>
          </TooltipTrigger>
          <TooltipContent side="bottom"><p>{item.label}</p></TooltipContent>
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
