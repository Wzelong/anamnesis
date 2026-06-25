import { useEffect, useRef, useState } from "react"
import type { App } from "@modelcontextprotocol/ext-apps"
import { Plus, Search, Loader2 } from "lucide-react"
import { callTool, parseStructured } from "../mcp"
import { cn } from "../lib/cn"
import { SYSTEMS, uriOf } from "../lib/systems"
import { Input } from "./ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"

interface CodeResult {
  system: string
  code: string
  display: string
  score: number
  rank: number
}

const SYSTEM_OPTIONS = Object.values(SYSTEMS).map((s) => ({ value: s.key, label: s.label }))

// Mocked results for standalone preview (no MCP host).
const MOCK: CodeResult[] = [
  { system: "snomed", code: "233819005", display: "Stable angina pectoris", score: 0.94, rank: 1 },
  { system: "snomed", code: "194828000", display: "Angina", score: 0.81, rank: 2 },
  { system: "snomed", code: "429559004", display: "Typical angina", score: 0.77, rank: 3 },
]

export function CodeSearch({
  app,
  initialQuery = "",
  initialSystem = "snomed",
  onApply,
}: {
  app: App | null
  initialQuery?: string
  initialSystem?: string
  onApply?: (coding: { system: string; code: string; display: string }) => void
}) {
  const [query, setQuery] = useState(initialQuery)
  const [system, setSystem] = useState(initialSystem)
  const [results, setResults] = useState<CodeResult[]>([])
  const [loading, setLoading] = useState(false)
  const reqId = useRef(0)

  useEffect(() => {
    const q = query.trim()
    if (!q) { setResults([]); setLoading(false); return }
    const id = ++reqId.current
    setLoading(true)
    const t = setTimeout(async () => {
      try {
        if (!app) {
          await new Promise((r) => setTimeout(r, 250))
          if (id !== reqId.current) return
          setResults(MOCK.filter((m) => m.system === system))
        } else {
          const res = await callTool(app, "SearchTerminology", { query: q, system, top_k: 12 })
          const data = parseStructured<{ results: CodeResult[] }>(res)
          if (id !== reqId.current) return
          setResults(data?.results ?? [])
        }
      } catch {
        if (id === reqId.current) setResults([])
      } finally {
        if (id === reqId.current) setLoading(false)
      }
    }, 300)
    return () => clearTimeout(t)
  }, [query, system, app])

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="flex items-center justify-between gap-2 px-3 h-10 border-b shrink-0">
        <div className="relative flex-1 min-w-0 -ml-2">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
          <Input
            autoFocus
            placeholder="Search terminology…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-7 h-7 text-xs border-0 shadow-none focus-visible:ring-0 bg-transparent"
          />
        </div>
        <Select value={system} onValueChange={setSystem}>
          <SelectTrigger className="h-7 gap-1 text-xs shrink-0 border-0 shadow-none focus-visible:ring-0 bg-transparent text-muted-foreground hover:text-foreground px-1.5">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SYSTEM_OPTIONS.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-10 text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
          </div>
        ) : results.length === 0 ? (
          <div className="flex items-center justify-center py-10 text-sm text-muted-foreground px-6 text-center">
            {query.trim() ? "No matches" : "Type to search terminology."}
          </div>
        ) : (
          results.map((r) => (
            <div key={`${r.system}-${r.code}`} className="group flex items-center gap-3 px-3 py-2 border-b hover:bg-muted/50">
              <span className="text-xs font-mono text-muted-foreground shrink-0 w-24 truncate">{r.code}</span>
              <span className="text-sm truncate flex-1">{r.display}</span>
              <span className="text-[11px] text-muted-foreground tabular-nums shrink-0">{Math.round(r.score * 100)}%</span>
              {onApply && (
                <button
                  onClick={() => onApply({ system: uriOf(r.system), code: r.code, display: r.display })}
                  className={cn("h-6 w-6 inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground cursor-pointer opacity-0 group-hover:opacity-100")}
                  aria-label="Apply code"
                  title="Apply to resource"
                >
                  <Plus className="size-3.5" />
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
