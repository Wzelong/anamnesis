import { useState } from "react"
import { ChevronDown, ShieldAlert } from "lucide-react"
import type { Conformance } from "../types"
import { cn } from "../lib/cn"

const LEVEL_LABEL: Record<string, string> = {
  r4: "Base R4",
  profile: "US Core",
  validator: "US Core validated",
}

// Renders only when the resource is non-conformant — an exception flag, not a
// per-proposal stamp. A valid resource shows nothing.
export function ConformanceBadge({ c }: { c?: Conformance | null }) {
  const [open, setOpen] = useState(false)
  if (!c || c.valid) return null

  const issues = c.issues ?? []
  const level = LEVEL_LABEL[c.level] ?? c.level

  return (
    <div className="rounded-md border bg-muted/40">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-[11px] cursor-pointer"
      >
        <ShieldAlert className="size-3.5 shrink-0 text-foreground" />
        <span className="font-medium text-foreground">
          {issues.length} issue{issues.length === 1 ? "" : "s"}
        </span>
        <span className="text-muted-foreground">{level}</span>
        <ChevronDown className={cn("size-3 ml-auto text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <ul className="border-t divide-y">
          {issues.map((i, idx) => (
            <li key={idx} className="px-3 py-1.5 text-[11px] space-y-0.5">
              <div className="flex items-center gap-1.5">
                <span className={cn("uppercase tracking-wide text-[9px] font-medium", i.severity === "error" || i.severity === "fatal" ? "text-foreground" : "text-muted-foreground")}>
                  {i.severity}
                </span>
                {i.path && <span className="font-mono text-muted-foreground truncate">{i.path}</span>}
              </div>
              <div className="text-muted-foreground">{i.message}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
