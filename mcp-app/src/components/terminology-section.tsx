import { useRef, useState } from "react"
import type { App } from "@modelcontextprotocol/ext-apps"
import { ChevronLeft, ChevronRight, Loader2, Upload, X } from "lucide-react"
import type { Code, Preset } from "../types"
import { IG_CATALOG, igById } from "../lib/ig-catalog"
import { cn } from "../lib/cn"
import { callTool, parseStructured } from "../mcp"
import { Checkbox } from "./ui/checkbox"
import { Input } from "./ui/input"
import { Textarea } from "./ui/textarea"

const SYS_LABEL: Record<string, string> = {
  snomed: "SNOMED CT",
  loinc: "LOINC",
  rxnorm: "RxNorm",
  icd10: "ICD-10-CM",
}

const COVERAGE_GAP: Record<string, string> = {
  Procedure: "US Core also allows CPT, HCPCS, ICD-10-PCS, CDT — not retrieved.",
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
  const [editing, setEditing] = useState<string | null>(null)
  const types = Object.keys((igById(preset.ig.base) ?? IG_CATALOG.base[0]).resources)

  if (editing) {
    return <TypeEditor app={app} preset={preset} rt={editing} onBack={() => setEditing(null)} onChange={onChange} />
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="px-4 py-3 max-w-md">
        <div className="space-y-0.5 mb-3">
          <h2 className="text-base font-semibold">Terminology</h2>
          <p className="text-xs text-muted-foreground">Coding systems and value-set scope per type.</p>
        </div>

        <div className="-mx-2">
          {types.map((rt) => {
            const candidates = candidatesFor(preset, rt)
            const selected = preset.coding[rt]?.systems ?? candidates
            const subset = preset.coding[rt]?.subset ?? null
            return (
              <button
                key={rt}
                onClick={() => setEditing(rt)}
                className="group w-full flex items-center gap-3 px-2 h-10 rounded-md text-left cursor-pointer hover:bg-muted/50 transition-colors"
              >
                <span className="text-sm shrink-0">{rt}</span>
                <span className="flex-1 min-w-0 text-xs text-muted-foreground truncate text-right">
                  {candidates.filter((s) => selected.includes(s)).map((s) => SYS_LABEL[s] ?? s).join(", ")}
                  {subset && subset.length > 0 ? ` · ${subset.length} scoped` : ""}
                </span>
                <ChevronRight className="size-4 shrink-0 text-muted-foreground/40 group-hover:text-muted-foreground transition-colors" />
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function TypeEditor({
  app,
  preset,
  rt,
  onBack,
  onChange,
}: {
  app: App | null
  preset: Preset
  rt: string
  onBack: () => void
  onChange: (coding: Preset["coding"]) => void
}) {
  const candidates = candidatesFor(preset, rt)
  const locked = candidates.length === 1
  const selected = candidates.filter((s) => (preset.coding[rt]?.systems ?? candidates).includes(s))
  const subset = preset.coding[rt]?.subset ?? null

  function toggleSystem(sys: string) {
    const has = selected.includes(sys)
    if (has && selected.length === 1) return
    const next = candidates.filter((s) => (s === sys ? !has : selected.includes(s)))
    const coding = { ...preset.coding }
    const entry = { ...coding[rt], systems: next }
    coding[rt] = sameSet(next, candidates) ? stripSystems(entry) : entry
    if (!coding[rt] || Object.keys(coding[rt]).length === 0) delete coding[rt]
    onChange(coding)
  }

  function setSubset(codes: Code[]) {
    onChange({ ...preset.coding, [rt]: { ...preset.coding[rt], subset: codes } })
  }

  function clearSubset() {
    const coding = { ...preset.coding }
    const entry = { ...coding[rt] }
    delete entry.subset
    if (Object.keys(entry).length === 0) delete coding[rt]
    else coding[rt] = entry
    onChange(coding)
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto animate-in slide-in-from-right-2 duration-150">
      <div className="px-4 py-3 space-y-5 max-w-md">
        <div>
          <div className="flex items-center gap-1">
            <button
              onClick={onBack}
              aria-label="Back to Terminology"
              className="-ml-1.5 size-7 inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground cursor-pointer"
            >
              <ChevronLeft className="size-4" />
            </button>
            <h2 className="text-base font-semibold">{rt}</h2>
          </div>
          <p className="text-xs text-muted-foreground mt-1">Coding systems and value-set scope for {rt} resources.</p>
        </div>

        <section className="space-y-2">
          <h3 className="text-xs font-medium text-muted-foreground">Coding systems</h3>
          {subset && subset.length > 0 ? (
            <p className="text-[11px] text-muted-foreground">
              {selected.map((s) => SYS_LABEL[s] ?? s).join(", ")} — governed by the value set below.
            </p>
          ) : (
            <div className="flex flex-wrap gap-x-6 gap-y-1.5">
              {candidates.map((sys) => {
                const on = selected.includes(sys)
                const lastOn = on && selected.length === 1
                return (
                  <label
                    key={sys}
                    title={lastOn && !locked ? "At least one system is required" : undefined}
                    className={cn("flex items-center gap-2 text-xs select-none", locked ? "cursor-default" : "cursor-pointer")}
                  >
                    <Checkbox checked={on} disabled={locked} onCheckedChange={() => toggleSystem(sys)} />
                    <span className={on ? "text-foreground" : "text-muted-foreground"}>{SYS_LABEL[sys] ?? sys}</span>
                  </label>
                )
              })}
            </div>
          )}
          {COVERAGE_GAP[rt] && <p className="text-[11px] text-muted-foreground">{COVERAGE_GAP[rt]}</p>}
        </section>

        <ScopeEditor app={app} rt={rt} subset={subset} onAttach={setSubset} onClear={clearSubset} />
      </div>
    </div>
  )
}

function stripSystems<T extends { systems?: string[] }>(entry: T): Omit<T, "systems"> {
  const { systems: _drop, ...rest } = entry
  return rest
}

type Lane = "reference" | "paste"

function ScopeEditor({
  app,
  rt,
  subset,
  onAttach,
  onClear,
}: {
  app: App | null
  rt: string
  subset: Code[] | null
  onAttach: (codes: Code[]) => void
  onClear: () => void
}) {
  const [adding, setAdding] = useState(false)
  const [lane, setLane] = useState<Lane>("reference")
  const [ref, setRef] = useState("")
  const [text, setText] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<Code[] | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  function reset() {
    setAdding(false); setLane("reference"); setRef(""); setText(""); setError(null); setResult(null)
  }

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
    <section className="space-y-2">
      <h3 className="text-xs font-medium text-muted-foreground">Value-set scope</h3>
      <p className="text-[11px] text-muted-foreground">Only codes in the set are produced; {rt} resources outside it are dropped.</p>

      {subset && subset.length > 0 && !adding ? (
        <div className="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-xs">
          <span className="flex-1 font-medium">{subset.length} codes</span>
          <button onClick={() => { reset(); setAdding(true) }} className="px-2 h-7 rounded-md border hover:bg-accent cursor-pointer text-[11px]">Replace</button>
          <button onClick={onClear} className="px-2 h-7 rounded-md border hover:bg-accent cursor-pointer text-[11px] inline-flex items-center gap-1"><X className="size-3" />Remove</button>
        </div>
      ) : !adding ? (
        <button onClick={() => setAdding(true)} className="text-xs px-3 h-8 rounded-md border hover:bg-accent cursor-pointer">Add a value set</button>
      ) : result ? (
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">{result.length} codes · {systemsIn(result)}</div>
          <div className="rounded-md border divide-y max-h-44 overflow-y-auto">
            {result.slice(0, 50).map((c, i) => (
              <div key={i} className="flex gap-2 px-3 py-1.5 text-[11px]">
                <span className="font-mono text-muted-foreground shrink-0">{c.code}</span>
                <span className="truncate">{c.display}</span>
              </div>
            ))}
          </div>
          <div className="flex gap-2">
            <button onClick={() => { onAttach(result); reset() }} className="h-8 px-3 text-xs rounded-md bg-primary text-primary-foreground hover:bg-primary/90 cursor-pointer font-medium">Attach</button>
            <button onClick={reset} className="h-8 px-3 text-xs rounded-md border hover:bg-accent cursor-pointer">Cancel</button>
          </div>
        </div>
      ) : (
        <div className="space-y-2">
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
            <button
              onClick={resolve}
              disabled={busy || (lane === "reference" ? !ref.trim() : !text.trim())}
              className="h-8 px-3 text-xs rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 cursor-pointer font-medium inline-flex items-center gap-1.5"
            >
              {busy && <Loader2 className="size-3 animate-spin" />}
              {busy ? "Resolving…" : lane === "reference" ? "Resolve" : "Parse"}
            </button>
            <button onClick={reset} disabled={busy} className="h-8 px-3 text-xs rounded-md border hover:bg-accent cursor-pointer disabled:opacity-50">Cancel</button>
          </div>
        </div>
      )}
    </section>
  )
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
