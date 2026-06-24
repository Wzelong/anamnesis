import { useEffect, useRef, useState } from "react"
import type { App } from "@modelcontextprotocol/ext-apps"
import { ArrowRight, ArrowRightLeft, BookPlus, ChevronDown, Loader2, Plus, Replace, Search, SearchX, Trash2, Upload, X } from "lucide-react"
import type { Code, CodingOverride, Preset, QueryRule } from "../types"
import { IG_CATALOG, igById } from "../lib/ig-catalog"
import { cn } from "../lib/cn"
import { callTool, parseStructured } from "../mcp"
import { RT_LABEL } from "../lib/proposal-meta"
import { Button } from "./ui/button"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "./ui/empty"
import { Input } from "./ui/input"
import { Textarea } from "./ui/textarea"
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip"

const SYS_SHORT: Record<string, string> = {
  snomed: "SNOMED",
  loinc: "LOINC",
  rxnorm: "RxNorm",
  icd10: "ICD-10",
}

function sameSet(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((x) => b.includes(x))
}

function candidatesFor(preset: Preset, rt: string): string[] {
  const base = igById(preset.ig.base) ?? IG_CATALOG.base[0]
  const specialty = preset.ig.specialty ? igById(preset.ig.specialty) : undefined
  return specialty?.resources[rt]?.coding.systems ?? base.resources[rt].coding.systems
}

export function TerminologySection({
  app,
  preset,
  onChange,
}: {
  app: App | null
  preset: Preset
  onChange: (coding: Preset["coding"]) => void
}) {
  const types = Object.keys((igById(preset.ig.base) ?? IG_CATALOG.base[0]).resources)
  const [activeRt, setActiveRt] = useState<string>(types[0] ?? "")
  const rt = types.includes(activeRt) ? activeRt : (types[0] ?? "")
  const [vsOpen, setVsOpen] = useState(false)
  const [ruleSeed, setRuleSeed] = useState<string | null>(null)

  const candidates = candidatesFor(preset, rt)
  const locked = candidates.length === 1
  const entry = preset.coding[rt] ?? {}
  const selected = candidates.filter((s) => (entry.systems ?? candidates).includes(s))
  const subset = entry.subset ?? null
  const scoped = !!(subset && subset.length > 0)
  const rules = entry.query_rules ?? []

  function update(mut: (e: CodingOverride) => CodingOverride) {
    const coding = { ...preset.coding }
    const e = mut({ ...(coding[rt] ?? {}) })
    if (e.systems && sameSet(e.systems, candidates)) delete e.systems
    if (e.subset && e.subset.length === 0) delete e.subset
    if (e.query_rules && e.query_rules.length === 0) delete e.query_rules
    if (Object.keys(e).length === 0) delete coding[rt]
    else coding[rt] = e
    onChange(coding)
  }

  function toggleSystem(sys: string) {
    const has = selected.includes(sys)
    if (has && selected.length === 1) return
    const next = candidates.filter((s) => (s === sys ? !has : selected.includes(s)))
    update((e) => ({ ...e, systems: next }))
  }

  const attachSubset = (codes: Code[]) => { update((e) => ({ ...e, subset: codes })); setVsOpen(false) }
  const clearSubset = () => update((e) => { const { subset: _s, ...rest } = e; return rest })
  const addRule = (r: QueryRule) => update((e) => ({ ...e, query_rules: [...(e.query_rules ?? []), r] }))
  const removeRule = (i: number) =>
    update((e) => ({ ...e, query_rules: (e.query_rules ?? []).filter((_, j) => j !== i) }))

  return (
    <div className="flex-1 min-h-0 flex">
      <section className="w-1/2 shrink-0 border-r flex flex-col min-h-0">
        <header className="h-10 shrink-0 border-b px-3 flex items-center gap-2 min-w-0">
          <ResourceSelect types={types} active={rt} onSelect={(t) => { setActiveRt(t); setVsOpen(false) }} />

          {!scoped && (
            <div className="flex items-center gap-0.5 min-w-0">
              {candidates.map((sys) => {
                const on = selected.includes(sys)
                return (
                  <button
                    key={sys}
                    onClick={() => toggleSystem(sys)}
                    disabled={locked}
                    className={cn(
                      "h-6 px-2 rounded-md text-[11px] transition-colors",
                      on ? "bg-muted text-foreground font-medium" : "text-muted-foreground hover:bg-accent hover:text-foreground",
                      locked ? "cursor-default" : "cursor-pointer",
                    )}
                  >
                    {SYS_SHORT[sys] ?? sys}
                  </button>
                )
              })}
            </div>
          )}

          <div className="flex-1" />

          {scoped ? (
            <div className="flex items-center gap-0.5 shrink-0">
              <span className="text-xs text-muted-foreground tabular-nums px-1">{subset!.length} codes</span>
              <Tip label="Replace value set">
                <IconBtn active={vsOpen} onClick={() => setVsOpen((o) => !o)}><Replace className="size-3.5" /></IconBtn>
              </Tip>
              <Tip label="Remove value set">
                <IconBtn onClick={clearSubset}><X className="size-3.5" /></IconBtn>
              </Tip>
            </div>
          ) : (
            <Tip label="Add value set">
              <IconBtn active={vsOpen} onClick={() => setVsOpen((o) => !o)}><BookPlus className="size-3.5" /></IconBtn>
            </Tip>
          )}
        </header>

        {vsOpen ? (
          <ValueSetFlow app={app} rt={rt} onCancel={() => setVsOpen(false)} onAttach={attachSubset} />
        ) : (
          <>
            <RulesList rules={rules} onRemove={removeRule} />
            <RuleComposer onAdd={addRule} seed={ruleSeed} onSeedConsumed={() => setRuleSeed(null)} />
          </>
        )}
      </section>

      <CodeProbe
        app={app}
        systems={selected}
        subset={subset}
        rules={rules}
        onAddRuleFor={(q) => setRuleSeed(q)}
      />
    </div>
  )
}

function Tip({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  )
}

function IconBtn({
  children,
  onClick,
  active,
  label,
  className,
}: {
  children: React.ReactNode
  onClick: () => void
  active?: boolean
  label?: string
  className?: string
}) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      className={cn(
        "size-7 inline-flex items-center justify-center rounded-md cursor-pointer transition-colors",
        active ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground",
        className,
      )}
    >
      {children}
    </button>
  )
}

function ResourceSelect({
  types,
  active,
  onSelect,
}: {
  types: string[]
  active: string
  onSelect: (rt: string) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])

  return (
    <div className="relative min-w-0 shrink-0" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1 text-sm font-medium cursor-pointer hover:opacity-80 outline-none max-w-full"
      >
        <span className="truncate max-w-[140px]">{RT_LABEL[active] ?? active ?? "Resource"}</span>
        <ChevronDown className="size-3.5 text-muted-foreground shrink-0" />
      </button>

      {open && (
        <div className="absolute left-0 top-8 z-20 w-48 rounded-md border bg-card text-card-foreground shadow-md p-1">
          {types.map((t) => (
            <div
              key={t}
              onClick={() => { onSelect(t); setOpen(false) }}
              className={cn(
                "flex items-center rounded px-2 py-1.5 text-xs cursor-pointer",
                active === t ? "bg-muted font-medium" : "hover:bg-accent",
              )}
            >
              <span className="truncate flex-1 text-left">{RT_LABEL[t] ?? t}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function RulesList({ rules, onRemove }: { rules: QueryRule[]; onRemove: (i: number) => void }) {
  if (rules.length === 0) {
    return (
      <Empty className="flex-1 min-h-0">
        <EmptyHeader>
          <EmptyMedia variant="icon"><ArrowRightLeft /></EmptyMedia>
          <EmptyTitle>No rules yet</EmptyTitle>
          <EmptyDescription>Map an abbreviation or synonym to the term the pipeline should search for.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }
  return (
    <div className="flex-1 min-h-0 overflow-y-auto divide-y">
      {rules.map((r, i) => (
        <div key={i} className="group flex items-center gap-2 px-3 py-2 hover:bg-muted/50">
          <span className="text-sm truncate max-w-[45%] shrink-0">{r.from}</span>
          <ArrowRight className="size-3.5 text-muted-foreground shrink-0 relative top-px" />
          <span className="text-sm flex-1 min-w-0 truncate">{r.to}</span>
          <IconBtn label="Remove rule" onClick={() => onRemove(i)} className="shrink-0 opacity-0 group-hover:opacity-100">
            <Trash2 className="size-3.5" />
          </IconBtn>
        </div>
      ))}
    </div>
  )
}

function RuleComposer({
  onAdd,
  seed,
  onSeedConsumed,
}: {
  onAdd: (r: QueryRule) => void
  seed?: string | null
  onSeedConsumed?: () => void
}) {
  const [from, setFrom] = useState("")
  const [to, setTo] = useState("")
  const toRef = useRef<HTMLInputElement>(null)
  const canAdd = from.trim().length > 0 && to.trim().length > 0

  useEffect(() => {
    if (!seed) return
    setFrom(seed)
    onSeedConsumed?.()
    setTimeout(() => toRef.current?.focus(), 0)
  }, [seed])

  function add() {
    if (!canAdd) return
    onAdd({ from: from.trim(), to: to.trim() })
    setFrom("")
    setTo("")
  }

  return (
    <div className="shrink-0 border-t bg-background px-2.5 py-1.5 flex items-center gap-1.5">
      <input
        value={from}
        onChange={(e) => setFrom(e.target.value)}
        placeholder="abbreviation"
        spellCheck={false}
        className="flex-1 min-w-0 bg-transparent px-1 py-1 text-sm outline-none placeholder:text-muted-foreground"
      />
      <ArrowRight className="size-3.5 text-muted-foreground shrink-0" />
      <input
        ref={toRef}
        value={to}
        onChange={(e) => setTo(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") add() }}
        placeholder="standard term"
        spellCheck={false}
        className="flex-1 min-w-0 bg-transparent px-1 py-1 text-sm outline-none placeholder:text-muted-foreground"
      />
      <button
        onClick={add}
        disabled={!canAdd}
        aria-label="Add rule"
        className={cn(
          "flex size-7 shrink-0 items-center justify-center rounded-full border transition-colors",
          canAdd ? "cursor-pointer text-foreground hover:bg-accent" : "cursor-not-allowed text-muted-foreground opacity-50",
        )}
      >
        <Plus className="size-4" />
      </button>
    </div>
  )
}

type Lane = "reference" | "paste"

function ValueSetFlow({
  app,
  rt,
  onCancel,
  onAttach,
}: {
  app: App | null
  rt: string
  onCancel: () => void
  onAttach: (codes: Code[]) => void
}) {
  const [lane, setLane] = useState<Lane>("reference")
  const [ref, setRef] = useState("")
  const [text, setText] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<Code[] | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  async function resolve() {
    setBusy(true); setError(null)
    try {
      const codes = lane === "reference" ? await resolveRef(app, ref.trim()) : await parseText(app, text)
      if (!codes.length) setError("No codes resolved.")
      else setResult(codes)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  const systemsIn = (codes: Code[]) => [...new Set(codes.map((c) => labelForUri(c.system)))].join(", ")

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="px-3 py-3 space-y-3">
        <p className="text-[11px] text-muted-foreground">Only codes in the set are produced; {rt} resources outside it are dropped.</p>

        {result ? (
          <>
            <div className="text-xs text-muted-foreground">{result.length} codes · {systemsIn(result)}</div>
            <div className="rounded-md border divide-y max-h-56 overflow-y-auto">
              {result.slice(0, 50).map((c, i) => (
                <div key={i} className="flex gap-2 px-3 py-1.5 text-[11px]">
                  <span className="font-mono text-muted-foreground shrink-0">{c.code}</span>
                  <span className="truncate">{c.display}</span>
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <Button size="sm" onClick={() => onAttach(result)}>Attach</Button>
              <Button size="sm" variant="ghost" onClick={() => setResult(null)}>Back</Button>
            </div>
          </>
        ) : (
          <>
            <div className="inline-flex rounded-md border p-0.5 text-[11px]">
              {(["reference", "paste"] as Lane[]).map((l) => (
                <button
                  key={l}
                  onClick={() => { setLane(l); setError(null) }}
                  className={cn("px-2.5 h-6 rounded cursor-pointer", lane === l ? "bg-muted text-foreground font-medium" : "text-muted-foreground")}
                >
                  {l === "reference" ? "Reference" : "Paste / upload"}
                </button>
              ))}
            </div>

            {lane === "reference" ? (
              <div className="space-y-1">
                <Input value={ref} onChange={(e) => setRef(e.target.value)} placeholder="VSAC OID or ValueSet URL" className="h-8 text-xs" spellCheck={false} />
                <p className="text-[10px] text-muted-foreground">Resolved straight from VSAC.</p>
              </div>
            ) : (
              <div className="space-y-1">
                <Textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste codes or CSV…" className="text-xs min-h-20" spellCheck={false} />
                <div className="flex items-center justify-between">
                  <button onClick={() => fileInput.current?.click()} className="text-[11px] px-2 h-6 rounded-md border hover:bg-accent cursor-pointer inline-flex items-center gap-1"><Upload className="size-3" />Upload file</button>
                  <p className="text-[10px] text-muted-foreground">AI reads it; every code verified vs VSAC.</p>
                </div>
                <input ref={fileInput} type="file" accept=".csv,.txt,.tsv,text/*" className="hidden" onChange={async (e) => {
                  const f = e.target.files?.[0]; if (f) setText(await f.text()); e.target.value = ""
                }} />
              </div>
            )}

            {error && <p className="text-xs text-destructive">{error}</p>}
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={resolve}
                disabled={busy || (lane === "reference" ? !ref.trim() : !text.trim())}
              >
                {busy && <Loader2 className="size-3.5 animate-spin" />}
                {busy ? "Resolving…" : lane === "reference" ? "Resolve" : "Parse"}
              </Button>
              <Button size="sm" variant="ghost" onClick={onCancel} disabled={busy}>Cancel</Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

interface ProbeItem {
  code: string
  display: string
  score?: number
}
interface ProbeGroup {
  key: string
  items: ProbeItem[]
}

function CodeProbe({
  app,
  systems,
  subset,
  rules,
  onAddRuleFor,
}: {
  app: App | null
  systems: string[]
  subset: Code[] | null
  rules: QueryRule[]
  onAddRuleFor: (q: string) => void
}) {
  const [query, setQuery] = useState("")
  const [groups, setGroups] = useState<ProbeGroup[] | null>(null)
  const [loading, setLoading] = useState(false)
  const reqId = useRef(0)

  const q = query.trim()
  const matchedRule = rules.find((r) => r.from.trim().toLowerCase() === q.toLowerCase()) ?? null
  const term = matchedRule ? matchedRule.to : q
  const scoped = !!(subset && subset.length > 0)
  const subsetSig = (subset ?? []).map((c) => c.system + c.code).join("|")

  useEffect(() => {
    if (!q) { setGroups(null); setLoading(false); return }
    const id = ++reqId.current
    setLoading(true)
    const t = setTimeout(async () => {
      try {
        const g = subset && subset.length ? filterSubset(subset, term) : await apiSearch(app, term, systems)
        if (id !== reqId.current) return
        setGroups(g)
      } catch {
        if (id === reqId.current) setGroups([])
      } finally {
        if (id === reqId.current) setLoading(false)
      }
    }, 300)
    return () => clearTimeout(t)
  }, [q, term, scoped, subsetSig, systems.join(","), app])

  const visible = (groups ?? []).filter((g) => g.items.length > 0)

  return (
    <section className="flex-1 min-w-0 flex flex-col min-h-0">
      <div className="h-10 shrink-0 border-b px-3 flex items-center gap-2">
        <Search className="size-3.5 text-muted-foreground shrink-0" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search a concept…"
          spellCheck={false}
          className="flex-1 min-w-0 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
        <span className="text-[11px] text-muted-foreground shrink-0 truncate max-w-[45%]">
          {scoped ? `${subset!.length} in value set` : systems.map((s) => SYS_SHORT[s] ?? s).join(" · ")}
        </span>
      </div>

      {matchedRule && (
        <div className="shrink-0 border-b px-3 py-1.5 flex items-center gap-1.5 text-[11px]">
          <span className="text-muted-foreground truncate">{q}</span>
          <ArrowRight className="size-3 text-muted-foreground shrink-0" />
          <span className="truncate">{term}</span>
          <span className="ml-auto shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">rule</span>
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto">
        {!q ? (
          <Empty className="h-full">
            <EmptyHeader>
              <EmptyMedia variant="icon"><Search /></EmptyMedia>
              <EmptyTitle>Search a concept</EmptyTitle>
              <EmptyDescription>See the codes it resolves to in {scoped ? "the value set" : "the enabled systems"}.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : loading ? (
          <div className="flex items-center justify-center py-10 text-muted-foreground"><Loader2 className="size-4 animate-spin" /></div>
        ) : visible.length > 0 ? (
          visible.map((g) => (
            <div key={g.key}>
              <div className="px-3 py-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground bg-muted/40">
                {SYS_SHORT[g.key] ?? g.key}
              </div>
              {g.items.map((it) => (
                <div key={g.key + it.code} className="flex items-center gap-3 px-3 py-2 border-b hover:bg-muted/50">
                  <span className="text-xs font-mono text-muted-foreground shrink-0 w-20 truncate">{it.code}</span>
                  <span className="text-sm truncate flex-1">{it.display}</span>
                  {it.score != null && <span className="text-[11px] text-muted-foreground tabular-nums shrink-0">{Math.round(it.score * 100)}%</span>}
                </div>
              ))}
            </div>
          ))
        ) : (
          <Empty className="h-full">
            <EmptyHeader>
              <EmptyMedia variant="icon"><SearchX /></EmptyMedia>
              <EmptyTitle>No matches</EmptyTitle>
              <EmptyDescription>Nothing for "{term}". Add a rule to rewrite it into the term the terminology uses.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              <Button size="sm" variant="outline" onClick={() => onAddRuleFor(q)}>Add a rule for "{q}"</Button>
            </EmptyContent>
          </Empty>
        )}
      </div>
    </section>
  )
}

const SYSTEM_URI: Record<string, string> = {
  snomed: "http://snomed.info/sct",
  rxnorm: "http://www.nlm.nih.gov/research/umls/rxnorm",
  loinc: "http://loinc.org",
  icd10: "http://hl7.org/fhir/sid/icd-10-cm",
}
const URI_TO_SYS: Record<string, string> = Object.fromEntries(
  Object.entries(SYSTEM_URI).map(([k, v]) => [v, k]),
)

function filterSubset(subset: Code[], term: string): ProbeGroup[] {
  const lc = term.toLowerCase()
  const byKey: Record<string, ProbeItem[]> = {}
  for (const c of subset) {
    const disp = c.display ?? ""
    if (disp.toLowerCase().includes(lc) || c.code.toLowerCase().includes(lc)) {
      const key = URI_TO_SYS[c.system] ?? c.system
      ;(byKey[key] ??= []).push({ code: c.code, display: disp })
    }
  }
  return Object.entries(byKey).map(([key, items]) => ({ key, items }))
}

async function apiSearch(app: App | null, term: string, systems: string[]): Promise<ProbeGroup[]> {
  return Promise.all(systems.map(async (sys) => {
    if (!app) {
      const lc = term.toLowerCase()
      const items = (MOCK_RESULTS[sys] ?? []).filter((r) => r.display.toLowerCase().includes(lc) || r.code.toLowerCase().includes(lc))
      return { key: sys, items }
    }
    const res = await callTool(app, "SearchTerminology", { query: term, system: sys, top_k: 8 })
    return { key: sys, items: parseStructured<{ results: ProbeItem[] }>(res)?.results ?? [] }
  }))
}

const MOCK_RESULTS: Record<string, ProbeItem[]> = {
  snomed: [
    { code: "233819005", display: "Stable angina pectoris", score: 0.94 },
    { code: "194828000", display: "Angina", score: 0.81 },
    { code: "429559004", display: "Typical angina", score: 0.77 },
  ],
  icd10: [
    { code: "I20.9", display: "Angina pectoris, unspecified", score: 0.88 },
    { code: "I20.0", display: "Unstable angina", score: 0.72 },
  ],
  rxnorm: [
    { code: "1116635", display: "ticagrelor 90 MG Oral Tablet", score: 0.9 },
  ],
  loinc: [
    { code: "4548-4", display: "Hemoglobin A1c/Hemoglobin.total in Blood", score: 0.92 },
  ],
}

const URI_LABEL: Record<string, string> = {
  "http://snomed.info/sct": "SNOMED CT",
  "http://loinc.org": "LOINC",
  "http://www.nlm.nih.gov/research/umls/rxnorm": "RxNorm",
  "http://hl7.org/fhir/sid/icd-10-cm": "ICD-10-CM",
}
function labelForUri(uri: string): string {
  return URI_LABEL[uri] ?? uri
}

const MOCK_CODES: Code[] = [
  { system: "http://snomed.info/sct", code: "44054006", display: "Diabetes mellitus type 2" },
  { system: "http://hl7.org/fhir/sid/icd-10-cm", code: "E11.9", display: "Type 2 diabetes without complications" },
]

async function resolveRef(app: App | null, ref: string): Promise<Code[]> {
  if (!app) return MOCK_CODES
  const res = await callTool(app, "ResolveValueSet", { ref })
  return parseStructured<{ codes: Code[] }>(res)?.codes ?? []
}

async function parseText(app: App | null, text: string): Promise<Code[]> {
  if (!app) return MOCK_CODES
  const res = await callTool(app, "ParseCodes", { text })
  return parseStructured<{ codes: Code[] }>(res)?.codes ?? []
}
