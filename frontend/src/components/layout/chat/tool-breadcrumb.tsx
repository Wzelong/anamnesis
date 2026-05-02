"use client"

import { AlertCircle, Check, Loader2, Wrench } from "lucide-react"
import { cn } from "@/lib/utils"

interface Props {
  name: string
  status: "pending" | "ok" | "error" | undefined
  summary?: string
}

const HUMAN: Record<string, string> = {
  list_proposals: "Listing proposals",
  get_proposal: "Reading proposal",
  get_chart: "Reading chart",
  get_doc: "Reading document",
  search_codes: "Searching codes",
  propose_edit: "Drafting edit",
}

export function ToolBreadcrumb({ name, status, summary }: Props) {
  const label = summary || HUMAN[name] || name
  const Icon = status === "pending" ? Loader2 : status === "error" ? AlertCircle : status === "ok" ? Check : Wrench
  return (
    <div
      className={cn(
        "flex items-center gap-1.5 text-[11px]",
        status === "error" ? "text-destructive" : "text-muted-foreground",
      )}
    >
      <Icon
        className={cn("size-3 shrink-0", status === "pending" && "animate-spin")}
      />
      <span className="truncate">{label}</span>
    </div>
  )
}
