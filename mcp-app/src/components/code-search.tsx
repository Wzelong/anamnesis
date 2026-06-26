import { useEffect, useRef, useState } from "react"
import type { App } from "@modelcontextprotocol/ext-apps"
import { Check, Loader2, Plus, Search } from "lucide-react"
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

interface Group {
  system: string
  results: CodeResult[]
}

// Mirrors the pipeline auto-coder (RESOURCE_CODE_SYSTEMS), narrowed to the
// retrievable systems the SearchTerminology tool supports. Auto mode dual-codes
// a resource against all of its natural systems at once.
const RESOURCE_SYSTEMS: Record<string, string[]> = {
  Condition: ["snomed", "icd10"],
  MedicationRequest: ["rxnorm"],
  Procedure: ["snomed", "icd10"],
  Observation: ["loinc", "snomed"],
  AllergyIntolerance: ["snomed"],
  FamilyMemberHistory: ["snomed"],
}

const systemsForResource = (rt?: string): string[] => RESOURCE_SYSTEMS[rt ?? ""] ?? ["snomed"]

// Mocked results for standalone preview (no MCP host).
const MOCK: CodeResult[] = [
  { system: "snomed", code: "233819005", display: "Stable angina pectoris", score: 0.94, rank: 1 },
  { system: "snomed", code: "194828000", display: "Angina", score: 0.81, rank: 2 },
  { system: "snomed", code: "429559004", display: "Typical angina", score: 0.77, rank: 3 },
]

export function CodeSearch({
  app,
  initialQuery = "",
  resourceType,
  current,
  onApply,
}: {
  app: App | null
  initialQuery?: string
  resourceType?: string
  current?: { system: string; code: string } | null
  onApply?: (coding: { system: string; code: string; display: string }) => void
}) {
  const [query, setQuery] = useState(initialQuery)
  const [mode, setMode] = useState<string>("auto")
  const [groups, setGroups] = useState<Group[]>([])
  const [loading, setLoading] = useState(false)
  const reqId = useRef(0)

  const autoSystems = systemsForResource(resourceType)
  const activeSystems = mode === "auto" ? autoSystems : [mode]

  useEffect(() => {
    const q = query.trim()
    if (!q) { setGroups([]); setLoading(false); return }
    const id = ++reqId.current
    setLoading(true)
    const t = setTimeout(async () => {
      try {
        if (!app) {
          await new Promise((r) => setTimeout(r, 250))
          if (id !== reqId.current) return
          setGroups(activeSystems.map((s) => ({ system: s, results: s === "snomed" ? MOCK : [] })))
        } else {
          const gs = await Promise.all(activeSystems.map(async (s) => {
            const res = await callTool(app, "SearchTerminology", { query: q, system: s, top_k: 10 })
            return { system: s, results: parseStructured<{ results: CodeResult[] }>(res)?.results ?? [] }
          }))
          if (id !== reqId.current) return
          setGroups(gs)
        }
      } catch {
        if (id === reqId.current) setGroups([])
      } finally {
        if (id === reqId.current) setLoading(false)
      }
    }, 300)
    return () => clearTimeout(t)
  }, [query, mode, app, resourceType])

  const multi = activeSystems.length > 1
  const filled = groups.filter((g) => g.results.length > 0)
  const total = filled.reduce((n, g) => n + g.results.length, 0)

  const applyRow = (r: CodeResult) => onApply?.({ system: uriOf(r.system), code: r.code, display: r.display })

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
        {autoSystems.length > 1 && (
          <Select value={mode} onValueChange={setMode}>
            <SelectTrigger className="h-7 gap-1 text-xs shrink-0 border-0 shadow-none focus-visible:ring-0 bg-transparent text-muted-foreground hover:text-foreground px-1.5">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">Auto</SelectItem>
              {autoSystems.map((s) => <SelectItem key={s} value={s}>{SYSTEMS[s]?.label ?? s}</SelectItem>)}
            </SelectContent>
          </Select>
        )}
      </div>

      {current && (
        <div className="px-3 py-1.5 border-b shrink-0 flex items-center gap-2 text-[11px] text-muted-foreground">
          <Check className="size-3 shrink-0" />
          <span className="shrink-0">Current</span>
          <span className="font-medium text-foreground shrink-0">{SYSTEMS[current.system]?.short ?? current.system}</span>
          <span className="font-mono truncate">{current.code}</span>
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center py-10 text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
          </div>
        ) : total === 0 ? (
          <div className="flex items-center justify-center py-10 text-sm text-muted-foreground px-6 text-center">
            {query.trim() ? "No matches" : "Type to search terminology."}
          </div>
        ) : (
          filled.map((g) => (
            <div key={g.system} className="divide-y">
              {multi && (
                <div className="px-3 py-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground bg-muted/30">
                  {SYSTEMS[g.system]?.label ?? g.system}
                </div>
              )}
              {g.results.map((r) => {
                const applied = !!current && current.system === r.system && current.code === r.code
                return (
                  <div key={`${r.system}-${r.code}`} className="group flex items-center gap-3 px-3 py-2 hover:bg-muted/50">
                    <span className="text-xs font-mono text-muted-foreground shrink-0 w-24 truncate">{r.code}</span>
                    <span className="text-sm truncate flex-1">{r.display}</span>
                    <span className="text-[11px] text-muted-foreground tabular-nums shrink-0">{Math.round(r.score * 100)}%</span>
                    {applied ? (
                      <span className="text-[10px] text-muted-foreground inline-flex items-center gap-1 shrink-0">
                        <Check className="size-3" />Applied
                      </span>
                    ) : onApply && (
                      <button
                        onClick={() => applyRow(r)}
                        className={cn("h-6 w-6 inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground cursor-pointer opacity-0 group-hover:opacity-100")}
                        aria-label="Apply code"
                        title="Apply to resource"
                      >
                        <Plus className="size-3.5" />
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
