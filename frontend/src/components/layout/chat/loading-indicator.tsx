"use client"

import { Loader2 } from "lucide-react"

interface Props {
  status?: string | null
}

export function LoadingIndicator({ status }: Props) {
  return (
    <div className="flex items-center gap-2 animate-in fade-in duration-300">
      <Loader2 className="size-4 animate-spin text-muted-foreground shrink-0" />
      <span className="text-sm text-muted-foreground truncate max-w-[260px]">
        {status?.trim() || "Thinking"}…
      </span>
    </div>
  )
}
