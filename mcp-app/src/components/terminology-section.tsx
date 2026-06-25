import { useEffect, useRef, useState } from "react"
import type { App } from "@modelcontextprotocol/ext-apps"
import { ArrowRight, ArrowRightLeft, BookPlus, Check, ChevronDown, Loader2, Lock, Pencil, Plus, RotateCcw, Search, SearchX, Trash2, Upload, X } from "lucide-react"
import type { Code, CodingOverride, Preset, QueryRule } from "../types"
import { IG_CATALOG, igById, fixedGroupsFor, type FixedGroup } from "../lib/ig-catalog"
import { cn } from "../lib/cn"
import { SYSTEMS, shortLabel, uriOf, keyOfUri } from "../lib/systems"
import { callTool, parseStructured } from "../mcp"
import { RT_LABEL } from "../lib/proposal-meta"
import { Button } from "./ui/button"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "./ui/empty"
import { Input } from "./ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select"
import { Textarea } from "./ui/textarea"
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip"

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
  const [tab, setTab] = useState<Tab>("codeset")
  const [ruleDraft, setRuleDraft] = useState<QueryRule | null>(null)
  const [adding, setAdding] = useState(false)
  const [confirmingReset, setConfirmingReset] = useState(false)

  const candidates = candidatesFor(preset, rt)
  const entry = preset.coding[rt] ?? {}
  const selected = candidates.filter((s) => (entry.systems ?? candidates).includes(s))
  const pinned = entry.codes ?? []
  const rules = entry.query_rules ?? []
  const codesetDirty = !!(entry.codes?.length || entry.systems)

  function update(mut: (e: CodingOverride) => CodingOverride) {
    const coding = { ...preset.coding }
    const e = mut({ ...(coding[rt] ?? {}) })
    if (e.systems && sameSet(e.systems, candidates)) delete e.systems
    if (e.codes && e.codes.length === 0) delete e.codes
    if (e.query_rules && e.query_rules.length === 0) delete e.query_rules
    if (Object.keys(e).length === 0) delete coding[rt]
    else coding[rt] = e
    onChange(coding)
  }

  const writeCodes = (codes: Code[]) => update((e) => ({ ...e, codes }))
  const resetCodeset = () => update((e) => { const { codes: _c, systems: _s, ...rest } = e; return rest })
  const mergeCodes = (extra: Code[]) => {
    const seen = new Set(pinned.map((c) => c.system + "|" + c.code))
    const add = extra.filter((c) => { const k = c.system + "|" + c.code; if (seen.has(k)) return false; seen.add(k); return true })
    if (add.length) writeCodes([...pinned, ...add])
  }
  const removeCode = (i: number) => writeCodes(pinned.filter((_, j) => j !== i))
  const updateCode = (i: number, c: Code) => writeCodes(pinned.map((x, j) => (j === i ? c : x)))
  const removeBundle = (ref: string) => writeCodes(pinned.filter((c) => c.bundle !== ref))
  const addRule = (r: QueryRule) => update((e) => ({ ...e, query_rules: [...(e.query_rules ?? []), r] }))
  const updateRule = (i: number, r: QueryRule) =>
    update((e) => ({ ...e, query_rules: (e.query_rules ?? []).map((x, j) => (j === i ? r : x)) }))
  const removeRule = (i: number) =>
    update((e) => ({ ...e, query_rules: (e.query_rules ?? []).filter((_, j) => j !== i) }))

  const toggleSystem = (sys: string) =>
    update((e) => ({ ...e, systems: candidates.filter((s) => (s === sys ? !selected.includes(s) : selected.includes(s))) }))

  const startAddRule = (from = "") => { setTab("rules"); setRuleDraft({ from, to: "" }) }

  function selectRt(t: string) { setActiveRt(t); setRuleDraft(null); setAdding(false); setConfirmingReset(false) }

  return (
    <div className="flex-1 min-h-0 flex">
      <section className="w-1/2 shrink-0 border-r flex flex-col min-h-0">
        <header className="h-10 shrink-0 border-b px-3 flex items-center gap-1 min-w-0">
          <ResourceSelect types={types} active={rt} onSelect={selectRt} />
          <CodingTabs value={tab} onChange={(t) => { setTab(t); setAdding(false); setConfirmingReset(false) }} />
          <div className="flex-1" />
          {tab === "rules" ? (
            <IconBtn onClick={() => startAddRule()} label="Add rule"><Plus className="size-3.5" /></IconBtn>
          ) : (
            <>
              <IconBtn active={adding} onClick={() => { setAdding(true); setConfirmingReset(false) }} label="Add"><Plus className="size-3.5" /></IconBtn>
              {codesetDirty && (
                <IconBtn active={confirmingReset} onClick={() => { setConfirmingReset(true); setAdding(false) }} label="Reset to default"><RotateCcw className="size-3.5" /></IconBtn>
              )}
            </>
          )}
        </header>

        {tab === "rules" ? (
          <RulesList
            rules={rules}
            draft={ruleDraft}
            onAddCommit={(r) => { addRule(r); setRuleDraft(null) }}
            onAddCancel={() => setRuleDraft(null)}
            onUpdate={updateRule}
            onRemove={removeRule}
          />
        ) : confirmingReset ? (
          <ResetConfirmView
            rt={rt}
            onCancel={() => setConfirmingReset(false)}
            onConfirm={() => { resetCodeset(); setConfirmingReset(false) }}
          />
        ) : (
          <div className="flex-1 min-h-0 flex flex-col">
            {adding && (
              <AddForm
                offSystems={candidates.filter((s) => !selected.includes(s))}
                onAddCode={(c) => { mergeCodes([c]); setAdding(false) }}
                onAddSystem={(s) => { toggleSystem(s); setAdding(false) }}
                onImport={async (lane, value) => {
                  const resolved = lane === "reference"
                    ? (await resolveRef(app, value)).map((c) => ({ ...c, bundle: value }))
                    : await parseText(app, value)
                  mergeCodes(resolved); setAdding(false)
                }}
                onCancel={() => setAdding(false)}
              />
            )}
            <CodeList
              fixedGroups={fixedGroupsFor(preset, rt)}
              systems={candidates}
              open={selected}
              onToggleSystem={toggleSystem}
              codes={pinned}
              onRemoveBundle={removeBundle}
              onRemoveCode={removeCode}
              onUpdateCode={updateCode}
            />
          </div>
        )}
      </section>

      <CodeProbe
        app={app}
        systems={candidates}
        open={selected}
        pinned={pinned}
        rules={rules}
        onAdd={(c) => mergeCodes([c])}
        onAddRuleFor={(q) => startAddRule(q)}
      />
    </div>
  )
}

type Tab = "codeset" | "rules"

function CodingTabs({ value, onChange }: { value: Tab; onChange: (v: Tab) => void }) {
  return (
    <div className="flex items-center gap-0.5 shrink-0">
      <IconBtn active={value === "codeset"} onClick={() => onChange("codeset")} label="Codeset">
        <BookPlus className="size-3.5" />
      </IconBtn>
      <IconBtn active={value === "rules"} onClick={() => onChange("rules")} label="Rules">
        <ArrowRightLeft className="size-3.5" />
      </IconBtn>
    </div>
  )
}

function CodeList({
  fixedGroups,
  systems,
  open,
  onToggleSystem,
  codes,
  onRemoveBundle,
  onRemoveCode,
  onUpdateCode,
}: {
  fixedGroups: FixedGroup[]
  systems: string[]
  open: string[]
  onToggleSystem: (sys: string) => void
  codes: Code[]
  onRemoveBundle: (ref: string) => void
  onRemoveCode: (i: number) => void
  onUpdateCode: (i: number, c: Code) => void
}) {
  const [editIndex, setEditIndex] = useState<number | null>(null)

  const openBundles = systems.filter((s) => open.includes(s))
  const vsBundles = new Map<string, number>()
  codes.forEach((c) => { if (c.bundle) vsBundles.set(c.bundle, (vsBundles.get(c.bundle) ?? 0) + 1) })
  const loose = codes.map((c, i) => ({ c, i })).filter(({ c }) => !c.bundle)

  const hasBundles = openBundles.length > 0 || vsBundles.size > 0
  if (fixedGroups.length === 0 && !hasBundles && loose.length === 0) {
    return <p className="px-3 py-6 text-[11px] text-muted-foreground text-center">Empty codeset. Add a system, code, or value set.</p>
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto divide-y">
      {fixedGroups.map((g) => (
        <div key={g.title}>
          <GroupHeader>Required by {g.title}</GroupHeader>
          {g.codes.map((c) => <FixedRow key={c.system + c.code} item={c} />)}
        </div>
      ))}

      {hasBundles && (
        <div>
          <GroupHeader>Bundles</GroupHeader>
          {openBundles.map((s) => (
            <BundleRow key={"sys:" + s} title={SYSTEMS[s]?.label ?? s} meta="all concepts" onTrash={() => onToggleSystem(s)} />
          ))}
          {[...vsBundles].map(([ref, n]) => (
            <BundleRow key={"vs:" + ref} title={ref} meta={`${n} concept${n === 1 ? "" : "s"}`} onTrash={() => onRemoveBundle(ref)} />
          ))}
        </div>
      )}

      {loose.length > 0 && (
        <div>
          <GroupHeader>Codes</GroupHeader>
          {loose.map(({ c, i }) =>
            editIndex === i ? (
              <CodeEditor key={i} initial={c} onCommit={(u) => { onUpdateCode(i, u); setEditIndex(null) }} onCancel={() => setEditIndex(null)} />
            ) : (
              <div key={i} className="group flex items-center gap-2 px-3 py-1.5 hover:bg-muted/50">
                <div className="flex-1 min-w-0">
                  <div className="text-sm truncate">{c.display || c.code}</div>
                  <div className="text-[11px] text-muted-foreground truncate">
                    {shortLabel(keyOfUri(c.system))} <span className="font-mono">{c.code}</span>
                  </div>
                </div>
                <IconBtn label="Edit code" onClick={() => setEditIndex(i)} className="shrink-0 opacity-0 group-hover:opacity-100"><Pencil className="size-3.5" /></IconBtn>
                <IconBtn label="Remove code" onClick={() => onRemoveCode(i)} className="shrink-0 opacity-0 group-hover:opacity-100"><Trash2 className="size-3.5" /></IconBtn>
              </div>
            ),
          )}
        </div>
      )}
    </div>
  )
}

function ResetConfirmView({ rt, onCancel, onConfirm }: { rt: string; onCancel: () => void; onConfirm: () => void }) {
  const label = RT_LABEL[rt] ?? rt
  return (
    <Empty className="flex-1 min-h-0">
      <EmptyHeader>
        <EmptyMedia variant="icon" className="text-destructive"><RotateCcw className="size-5" /></EmptyMedia>
        <EmptyTitle>Reset to default</EmptyTitle>
        <EmptyDescription>
          Discards the codeset for <span className="font-medium text-foreground">{label}</span> — re-opens all systems and removes every pinned code and value set.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <div className="flex items-center justify-center gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
          <Button size="sm" variant="destructive" onClick={onConfirm}><RotateCcw className="size-3.5" />Reset</Button>
        </div>
      </EmptyContent>
    </Empty>
  )
}

function GroupHeader({ children }: { children: React.ReactNode }) {
  return <div className="px-3 py-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground bg-muted/40">{children}</div>
}

function FixedRow({ item }: { item: { system: string; code: string; display: string } }) {
  return (
    <div className="flex items-center gap-2 px-3 py-1.5 opacity-70">
      <div className="flex-1 min-w-0">
        <div className="text-sm truncate">{item.display || item.code}</div>
        <div className="text-[11px] text-muted-foreground truncate">
          {shortLabel(item.system)} <span className="font-mono">{item.code}</span>
        </div>
      </div>
      <Lock className="size-3 text-muted-foreground shrink-0" />
    </div>
  )
}

function BundleRow({ title, meta, onTrash }: { title: string; meta: string; onTrash: () => void }) {
  return (
    <div className="group flex items-center gap-2 px-3 py-2 hover:bg-muted/50">
      <span className="text-sm truncate min-w-0">{title}</span>
      <span className="text-base leading-none text-muted-foreground shrink-0">·</span>
      <span className="text-[11px] text-muted-foreground shrink-0">{meta}</span>
      <div className="flex-1" />
      <IconBtn label="Remove" onClick={onTrash} className="shrink-0 opacity-0 group-hover:opacity-100"><Trash2 className="size-3.5" /></IconBtn>
    </div>
  )
}

function CodeEditor({ initial, onCommit, onCancel }: { initial: Code; onCommit: (c: Code) => void; onCancel: () => void }) {
  const known = keyOfUri(initial.system) in SYSTEMS
  const [sys, setSys] = useState(known ? keyOfUri(initial.system) : CUSTOM_SYSTEM)
  const [customSys, setCustomSys] = useState(known ? "" : initial.system)
  const [code, setCode] = useState(initial.code)
  const [display, setDisplay] = useState(initial.display ?? "")
  const codeRef = useRef<HTMLInputElement>(null)

  useEffect(() => { codeRef.current?.focus() }, [])

  const system = sys === CUSTOM_SYSTEM ? customSys.trim() : uriOf(sys)
  const valid = code.trim().length > 0 && system.length > 0
  function commit() { if (valid) onCommit({ ...initial, system, code: code.trim(), display: display.trim() }) }

  return (
    <div className="bg-muted/20">
      <div className="px-3 pt-2 flex items-center gap-1">
        <span className="text-[11px] font-medium text-muted-foreground">Edit code</span>
        <div className="flex-1" />
        <IconBtn label="Save" onClick={commit} className={cn(!valid && "opacity-40 pointer-events-none")}><Check className="size-3.5" /></IconBtn>
        <IconBtn label="Cancel" onClick={onCancel}><X className="size-3.5" /></IconBtn>
      </div>
      <div className="px-3 py-2 space-y-1.5">
        <div className="flex items-center gap-1.5">
          <Select value={sys} onValueChange={setSys}>
            <SelectTrigger className="h-8 w-32 shrink-0 text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              {Object.values(SYSTEMS).map((s) => <SelectItem key={s.key} value={s.key}>{s.label}</SelectItem>)}
              <SelectItem value={CUSTOM_SYSTEM}>Custom…</SelectItem>
            </SelectContent>
          </Select>
          <Input ref={codeRef} value={code} onChange={(e) => setCode(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") onCancel() }} placeholder="code" className="h-8 flex-1 text-xs font-mono" spellCheck={false} />
        </div>
        {sys === CUSTOM_SYSTEM && (
          <Input value={customSys} onChange={(e) => setCustomSys(e.target.value)} placeholder="system URI" className="h-8 text-xs font-mono" spellCheck={false} />
        )}
        <Input value={display} onChange={(e) => setDisplay(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") onCancel() }} placeholder="display" className="h-8 text-xs" spellCheck={false} />
      </div>
    </div>
  )
}

type AddTab = "code" | "reference" | "paste" | "system"

const CUSTOM_SYSTEM = "__custom__"

const ADD_TABS: [AddTab, string][] = [
  ["code", "Code"],
  ["reference", "Reference"],
  ["paste", "Paste"],
  ["system", "System"],
]

function AddForm({
  offSystems,
  onAddCode,
  onAddSystem,
  onImport,
  onCancel,
}: {
  offSystems: string[]
  onAddCode: (c: Code) => void
  onAddSystem: (sys: string) => void
  onImport: (lane: "reference" | "paste", value: string) => Promise<void>
  onCancel: () => void
}) {
  const [tab, setTab] = useState<AddTab>("code")
  const [sys, setSys] = useState(Object.values(SYSTEMS)[0].key)
  const [customSys, setCustomSys] = useState("")
  const [code, setCode] = useState("")
  const [display, setDisplay] = useState("")
  const [ref, setRef] = useState("")
  const [text, setText] = useState("")
  const [busy, setBusy] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  const codeSystem = sys === CUSTOM_SYSTEM ? customSys.trim() : uriOf(sys)

  async function runImport(lane: "reference" | "paste", value: string) {
    if (!value.trim() || busy) return
    setBusy(true)
    try { await onImport(lane, value.trim()) } finally { setBusy(false) }
  }

  const canConfirm = busy
    ? false
    : tab === "code" ? !!code.trim() && !!codeSystem
    : tab === "reference" ? !!ref.trim()
    : tab === "paste" ? !!text.trim()
    : false

  function confirm() {
    if (!canConfirm) return
    if (tab === "code") onAddCode({ system: codeSystem, code: code.trim(), display: display.trim() })
    else if (tab === "reference") runImport("reference", ref)
    else if (tab === "paste") runImport("paste", text)
  }

  return (
    <div className="shrink-0 border-b bg-muted/20">
      <div className="px-3 pt-2 flex items-center gap-1">
        <div className="flex gap-0.5 rounded-md bg-muted/50 p-0.5 text-[11px]">
          {ADD_TABS.map(([t, label]) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "h-6 px-2 rounded cursor-pointer transition-colors",
                tab === t ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex-1" />
        {tab !== "system" && (
          <IconBtn label="Add" onClick={confirm} className={cn(!canConfirm && "opacity-40 pointer-events-none")}>
            {busy ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />}
          </IconBtn>
        )}
        <IconBtn label="Cancel" onClick={onCancel}><X className="size-3.5" /></IconBtn>
      </div>

      <div className="px-3 py-2">
        {tab === "code" && (
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5">
              <Select value={sys} onValueChange={setSys}>
                <SelectTrigger className="h-8 w-32 shrink-0 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.values(SYSTEMS).map((s) => <SelectItem key={s.key} value={s.key}>{s.label}</SelectItem>)}
                  <SelectItem value={CUSTOM_SYSTEM}>Custom…</SelectItem>
                </SelectContent>
              </Select>
              <Input value={code} onChange={(e) => setCode(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") confirm() }} placeholder="code" className="h-8 flex-1 text-xs font-mono" spellCheck={false} />
            </div>
            {sys === CUSTOM_SYSTEM && (
              <Input value={customSys} onChange={(e) => setCustomSys(e.target.value)} placeholder="system URI (e.g. http://example.org/cs)" className="h-8 text-xs font-mono" spellCheck={false} />
            )}
            <Input value={display} onChange={(e) => setDisplay(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") confirm() }} placeholder="display" className="h-8 text-xs" spellCheck={false} />
          </div>
        )}

        {tab === "reference" && (
          <div className="space-y-1">
            <Input value={ref} onChange={(e) => setRef(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") confirm() }} placeholder="VSAC OID or ValueSet URL" className="h-8 text-xs" spellCheck={false} />
            <p className="text-[10px] text-muted-foreground">Added as a bundle, resolved from VSAC.</p>
          </div>
        )}

        {tab === "paste" && (
          <div className="space-y-1.5">
            <Textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste codes or CSV…" className="text-xs min-h-16" spellCheck={false} />
            <button onClick={() => fileInput.current?.click()} className="text-[11px] px-2 h-7 rounded-md border hover:bg-accent cursor-pointer inline-flex items-center gap-1"><Upload className="size-3" />Upload</button>
            <input ref={fileInput} type="file" accept=".csv,.txt,.tsv,text/*" className="hidden"
              onChange={async (e) => { const f = e.target.files?.[0]; if (f) setText(await f.text()); e.target.value = "" }} />
          </div>
        )}

        {tab === "system" && (
          offSystems.length === 0 ? (
            <p className="text-[11px] text-muted-foreground py-1">All systems already included.</p>
          ) : (
            <div className="divide-y">
              {offSystems.map((s) => (
                <div key={s} className="flex items-center gap-2 py-1">
                  <span className="text-sm flex-1 min-w-0 truncate">{SYSTEMS[s]?.label ?? s}</span>
                  <IconBtn label="Add bundle" onClick={() => onAddSystem(s)}><Plus className="size-3.5" /></IconBtn>
                </div>
              ))}
            </div>
          )
        )}
      </div>
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
  const btn = (
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
  return label ? <Tip label={label}>{btn}</Tip> : btn
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

function RulesList({
  rules,
  draft,
  onAddCommit,
  onAddCancel,
  onUpdate,
  onRemove,
}: {
  rules: QueryRule[]
  draft: QueryRule | null
  onAddCommit: (r: QueryRule) => void
  onAddCancel: () => void
  onUpdate: (i: number, r: QueryRule) => void
  onRemove: (i: number) => void
}) {
  const [editIndex, setEditIndex] = useState<number | null>(null)

  if (rules.length === 0 && !draft) {
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
      {draft && <RuleEditRow initial={draft} onCommit={onAddCommit} onCancel={onAddCancel} />}
      {rules.map((r, i) =>
        editIndex === i ? (
          <RuleEditRow
            key={i}
            initial={r}
            onCommit={(u) => { onUpdate(i, u); setEditIndex(null) }}
            onCancel={() => setEditIndex(null)}
          />
        ) : (
          <div key={i} className="group flex items-center gap-2 px-3 py-2 hover:bg-muted/50">
            <span className="text-sm truncate max-w-[45%] shrink-0">{r.from}</span>
            <ArrowRight className="size-3.5 text-muted-foreground shrink-0 relative top-px" />
            <span className="text-sm flex-1 min-w-0 truncate">{r.to}</span>
            <IconBtn label="Edit rule" onClick={() => setEditIndex(i)} className="shrink-0 opacity-0 group-hover:opacity-100">
              <Pencil className="size-3.5" />
            </IconBtn>
            <IconBtn label="Remove rule" onClick={() => onRemove(i)} className="shrink-0 opacity-0 group-hover:opacity-100">
              <Trash2 className="size-3.5" />
            </IconBtn>
          </div>
        ),
      )}
    </div>
  )
}

function RuleEditRow({
  initial,
  onCommit,
  onCancel,
}: {
  initial: QueryRule
  onCommit: (r: QueryRule) => void
  onCancel: () => void
}) {
  const [from, setFrom] = useState(initial.from)
  const [to, setTo] = useState(initial.to)
  const fromRef = useRef<HTMLInputElement>(null)
  const toRef = useRef<HTMLInputElement>(null)
  const valid = from.trim().length > 0 && to.trim().length > 0

  useEffect(() => { (initial.from ? toRef.current : fromRef.current)?.focus() }, [])

  function commit() { if (valid) onCommit({ from: from.trim(), to: to.trim() }) }

  return (
    <div className="flex items-center gap-1.5 px-3 py-2 bg-muted/40">
      <input
        ref={fromRef}
        value={from}
        onChange={(e) => setFrom(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Escape") onCancel(); if (e.key === "Enter") toRef.current?.focus() }}
        placeholder="abbreviation"
        spellCheck={false}
        className="flex-1 min-w-0 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
      />
      <ArrowRight className="size-3.5 text-muted-foreground shrink-0" />
      <input
        ref={toRef}
        value={to}
        onChange={(e) => setTo(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Escape") onCancel(); if (e.key === "Enter") commit() }}
        placeholder="standard term"
        spellCheck={false}
        className="flex-1 min-w-0 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
      />
      <IconBtn label="Confirm" onClick={commit} className={cn("shrink-0", !valid && "opacity-40 pointer-events-none")}>
        <Check className="size-3.5" />
      </IconBtn>
      <IconBtn label="Cancel" onClick={onCancel} className="shrink-0">
        <X className="size-3.5" />
      </IconBtn>
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
  open,
  pinned,
  rules,
  onAdd,
  onAddRuleFor,
}: {
  app: App | null
  systems: string[]
  open: string[]
  pinned: Code[]
  rules: QueryRule[]
  onAdd: (c: Code) => void
  onAddRuleFor: (q: string) => void
}) {
  const [query, setQuery] = useState("")
  const [groups, setGroups] = useState<ProbeGroup[] | null>(null)
  const [loading, setLoading] = useState(false)
  const reqId = useRef(0)

  const q = query.trim()
  const matchedRule = rules.find((r) => r.from.trim().toLowerCase() === q.toLowerCase()) ?? null
  const term = matchedRule ? matchedRule.to : q

  useEffect(() => {
    if (!q) { setGroups(null); setLoading(false); return }
    const id = ++reqId.current
    setLoading(true)
    const t = setTimeout(async () => {
      try {
        const g = await apiSearch(app, term, systems)
        if (id !== reqId.current) return
        setGroups(g)
      } catch {
        if (id === reqId.current) setGroups([])
      } finally {
        if (id === reqId.current) setLoading(false)
      }
    }, 300)
    return () => clearTimeout(t)
  }, [q, term, systems.join(","), app])

  const pinnedKeys = new Set(pinned.map((c) => c.system + "|" + c.code))
  const inScope = (sysKey: string, code: string) => open.includes(sysKey) || pinnedKeys.has(uriOf(sysKey) + "|" + code)

  const flat = (groups ?? []).flatMap((g) => g.items.map((it) => ({ sys: g.key, ...it })))
  const inItems = flat.filter((x) => inScope(x.sys, x.code))
  const outItems = flat.filter((x) => !inScope(x.sys, x.code))

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
              <EmptyDescription>Search every system; add codes that aren't included yet.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : loading ? (
          <div className="flex items-center justify-center py-10 text-muted-foreground"><Loader2 className="size-4 animate-spin" /></div>
        ) : flat.length > 0 ? (
          <>
            {outItems.length > 0 && (
              <div>
                <GroupHeader>Not included</GroupHeader>
                {outItems.map((it) => (
                  <ProbeRow key={"out:" + it.sys + it.code} item={it}
                    action={<IconBtn label="Add to codeset" onClick={() => onAdd({ system: uriOf(it.sys), code: it.code, display: it.display })}><Plus className="size-3.5" /></IconBtn>} />
                ))}
              </div>
            )}
            {inItems.length > 0 && (
              <div>
                <GroupHeader>Included</GroupHeader>
                {inItems.map((it) => <ProbeRow key={"in:" + it.sys + it.code} item={it} muted />)}
              </div>
            )}
          </>
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

function ProbeRow({ item, action, muted }: {
  item: { sys: string; code: string; display: string; score?: number }
  action?: React.ReactNode
  muted?: boolean
}) {
  return (
    <div className={cn("group flex items-center gap-2 px-3 py-2 border-b hover:bg-muted/50", muted && "opacity-70")}>
      <span className="text-[10px] uppercase text-muted-foreground shrink-0 w-12 truncate">{shortLabel(item.sys)}</span>
      <span className="text-xs font-mono text-muted-foreground shrink-0 w-16 truncate">{item.code}</span>
      <span className="text-sm truncate flex-1">{item.display}</span>
      {item.score != null && <span className="text-[11px] text-muted-foreground tabular-nums shrink-0">{Math.round(item.score * 100)}%</span>}
      {action}
    </div>
  )
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
