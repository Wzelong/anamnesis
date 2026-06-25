import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react"
import type { App } from "@modelcontextprotocol/ext-apps"
import { ArrowUp, Check, ChevronDown, FileText, ListChecks, Loader2, PenTool, Play, Plus, Trash2, Undo2, Upload } from "lucide-react"
import type { ExtractionResult, Preset, PromptOverride } from "../types"
import { IG_CATALOG, igById } from "../lib/ig-catalog"
import { toast } from "sonner"
import { cn } from "../lib/cn"
import { callTool, parseStructured } from "../mcp"
import { NoteReader } from "./note-reader"
import { RT_LABEL } from "../lib/proposal-meta"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "./ui/empty"
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip"
import { Button } from "./ui/button"
import dump from "../demo/proposals.json"

const MAX_HEIGHT = 120

interface TestNote {
  id: string
  name: string
  text: string
  base?: boolean
}

const SEED_NOTES: TestNote[] = ((dump as unknown as ExtractionResult).documents ?? []).reduce<TestNote[]>(
  (acc, d, i) => {
    acc.push({ id: d.id, name: uniqueName(d.type || d.id, acc), text: d.text, base: i === 0 })
    return acc
  },
  [],
)

function uniqueName(base: string, notes: TestNote[]): string {
  const taken = new Set(notes.map((n) => n.name))
  if (!taken.has(base)) return base
  let i = 2
  while (taken.has(`${base} ${i}`)) i++
  return `${base} ${i}`
}

type Lane = "capture" | "extract"

function laneMap(preset: Preset, lane: Lane): Record<string, PromptOverride> {
  return (lane === "capture" ? preset.capture_prompts : preset.prompts) ?? {}
}

function presetAddon(preset: Preset, rt: string, lane: Lane): string {
  const o = laneMap(preset, lane)[rt]
  if (!o) return ""
  return o.versions.find((v) => v.version === o.active_version)?.text ?? o.versions.at(-1)?.text ?? ""
}

type Item = Record<string, unknown>

interface TestResult {
  rt: string
  items: Item[]
}

// Mock until ▶ is wired to TestPromptAddon: stage-2 candidate items, James Lee
// cardiology note, with the real per-type fields we extract.
const MOCK_ITEMS: Record<string, Item[]> = {
  Condition: [
    { name: "Stable angina pectoris", category: "diagnosis", certainty: "definite", body_site: ["heart"] },
    { name: "Coronary artery disease, two-vessel", category: "diagnosis", certainty: "definite" },
    { name: "Essential hypertension", category: "problem", certainty: "definite", onset: "2016" },
    { name: "Type 2 diabetes mellitus", category: "problem", certainty: "definite", onset: "2018" },
  ],
  Observation: [
    { name: "Blood pressure", value: "142/86", unit: "mmHg", category: "vital-signs", certainty: "definite" },
    { name: "LDL cholesterol", value: "88", unit: "mg/dL", category: "laboratory", certainty: "definite" },
    { name: "Hemoglobin A1c", value: "7.2", unit: "%", category: "laboratory", certainty: "definite" },
  ],
  MedicationRequest: [
    { name: "Metoprolol succinate", status: "active", intent: "order", dose: { value: "25", unit: "mg" }, route: "PO", frequency: "once daily" },
    { name: "Atorvastatin", status: "active", intent: "order", dose: { value: "40", unit: "mg" }, route: "PO", frequency: "daily" },
    { name: "Nitroglycerin", status: "active", intent: "order", route: "sublingual", frequency: "PRN", reason: "chest pain" },
  ],
  Procedure: [
    { name: "Diagnostic left heart catheterization", status: "completed", category: "diagnostic", performed: "2025-10-15", outcome: "two-vessel CAD" },
  ],
  AllergyIntolerance: [
    { substance: "Penicillin", category: "medication", criticality: "low", reaction: "rash", severity: "mild", onset_age: "childhood", verification: "unconfirmed" },
  ],
  FamilyMemberHistory: [
    { relationship: "father", conditions: [{ name: "myocardial infarction", onset_age: "60" }] },
  ],
}

async function testAddon(
  app: App | null, rt: string, note: string, capture: string, extract: string,
): Promise<Item[]> {
  if (!app) { await new Promise((r) => setTimeout(r, 600)); return MOCK_ITEMS[rt] ?? [] }
  const res = await callTool(app, "TestPromptAddon", { resource_type: rt, note, capture, extract })
  return parseStructured<{ items: Item[] }>(res)?.items ?? []
}

// Dev mock of the base scan routing rules per type (the editable Capture lane content).
const MOCK_CAPTURE_BASE: Record<string, string> = {
  Condition: "Include sentences asserting a confirmed patient problem (named disease with assertive framing; chronic/historical conditions; SDOH problems).\nExclude uncertain framing (possible, rule out), imaging/test findings without a diagnosis (→ Observation), pure risk factors (→ Observation), family history (→ FamilyMemberHistory).",
  Observation: "Include clinically actionable observations: abnormal/flagged vitals, decision-driving labs, clinical scores (A1c, LDL, PHQ), significant imaging findings, social-history status (tobacco, alcohol).\nExclude pertinent-negatives, routine normals, care-plan targets, family history.",
  MedicationRequest: "Include a drug name paired with an explicit action verb (start, continue, hold, stop, titrate, received).\nExclude home-med reconciliation lists and blanket 'continue all home medications'.",
  AllergyIntolerance: "Include a substance plus an adverse reaction/intolerance, or an explicit NKDA statement.\nExclude side-effects not framed as allergy.",
  Procedure: "Include completed or in-progress procedures (surgery, imaging done, biopsy, catheterization); historical procedures with an explicit date.\nExclude planned/scheduled procedures.",
  FamilyMemberHistory: "Include sentences describing a named relative's medical history (mother, father, sibling, grandparent).",
}

async function fetchCaptureBases(app: App | null): Promise<Record<string, string>> {
  if (!app) return MOCK_CAPTURE_BASE
  const res = await callTool(app, "GetPromptBases", {})
  return parseStructured<{ capture: Record<string, string> }>(res)?.capture ?? {}
}

const FIELD_SKIP = new Set([
  "source_sentences", "reasoning", "code_queries", "substance_queries", "reaction_queries", "queries",
])
const TITLE_KEYS = ["name", "substance", "relationship", "display", "title", "label"]

function titleKeyOf(item: Item): string | null {
  for (const k of TITLE_KEYS) {
    const v = item[k]
    if (typeof v === "string" && v.trim()) return k
  }
  return null
}

// One generic rule: flatten any candidate shape to label/value pairs.
function flatten(item: Item, skip: Set<string>): [string, string][] {
  const out: [string, string][] = []
  const walk = (label: string, v: unknown) => {
    if (v == null || v === "") return
    if (typeof v === "boolean") { if (v) out.push([label, "yes"]); return }
    if (Array.isArray(v)) {
      if (v.length === 0) return
      if (v.every((x) => x == null || typeof x !== "object")) {
        const s = v.filter((x) => x != null && x !== "").map(String).join(", ")
        if (s) out.push([label, s])
        return
      }
      v.forEach((x, i) => walk(v.length > 1 ? `${label} ${i + 1}` : label, x))
      return
    }
    if (typeof v === "object") {
      const o = v as Item
      if ("value" in o) {
        const s = [o.value, o.unit].filter((x) => x != null && x !== "").join(" ")
        if (s) out.push([label, s])
        return
      }
      for (const [k, cv] of Object.entries(o)) walk(`${label} · ${k.replace(/_/g, " ")}`, cv)
      return
    }
    out.push([label, String(v)])
  }
  for (const [k, v] of Object.entries(item)) {
    if (skip.has(k)) continue
    walk(k.replace(/_/g, " "), v)
  }
  return out
}

export function PromptsSection({
  app,
  preset,
  onChange,
}: {
  app: App | null
  preset: Preset
  onChange: (patch: Partial<Pick<Preset, "prompts" | "capture_prompts">>) => void
}) {
  const types = Object.keys((igById(preset.ig.base) ?? IG_CATALOG.base[0]).resources)
  const [notes, setNotes] = useState<TestNote[]>(SEED_NOTES)
  const [activeId, setActiveId] = useState<string>(SEED_NOTES[0]?.id ?? "")
  const [view, setView] = useState<"raw" | "rendered">("raw")
  const [leftView, setLeftView] = useState<"note" | "testing">("note")
  const [activeRt, setActiveRt] = useState<string>(types[0] ?? "")
  const [lane, setLane] = useState<Lane>("capture")
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [results, setResults] = useState<Record<string, TestResult>>({})
  const [captureBase, setCaptureBase] = useState<Record<string, string>>({})
  const counter = useRef(0)
  const active = notes.find((n) => n.id === activeId) ?? null

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const bases = await fetchCaptureBases(app)
      if (!cancelled) setCaptureBase(bases)
    })()
    return () => { cancelled = true }
  }, [app])

  const dkey = `${activeRt}::${lane}`
  // Capture is edit (seeded from the base routing block); extract is add-only (empty).
  const override = presetAddon(preset, activeRt, lane)
  const saved = lane === "capture" ? (override || captureBase[activeRt] || "") : override
  const addonText = drafts[dkey] ?? saved
  const dirty = drafts[dkey] !== undefined && drafts[dkey] !== saved
  const editAddon = (text: string) => setDrafts((d) => ({ ...d, [dkey]: text }))

  const revert = () => setDrafts((d) => { const n = { ...d }; delete n[dkey]; return n })

  const save = () => {
    const next = { ...laneMap(preset, lane), [activeRt]: { active_version: 1, versions: [{ version: 1, text: addonText.trim() }] } }
    onChange(lane === "capture" ? { capture_prompts: next } : { prompts: next })
    revert()
  }

  const [drafting, setDrafting] = useState(false)
  const [running, setRunning] = useState(false)
  const [confirming, setConfirming] = useState<"save" | "revert" | null>(null)

  const draftPrompt = async (ideas: string) => {
    setDrafting(true)
    try {
      const addon = await draftAddon(app, lane, activeRt, active?.text ?? "", ideas, addonText)
      if (addon) setDrafts((d) => ({ ...d, [dkey]: addon }))
    } catch (e) {
      toast.error(`Draft failed: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setDrafting(false)
    }
  }

  const runTest = async () => {
    if (!active) return
    setLeftView("testing")
    setRunning(true)
    try {
      const capture = drafts[`${activeRt}::capture`] ?? presetAddon(preset, activeRt, "capture")
      const extract = drafts[`${activeRt}::extract`] ?? presetAddon(preset, activeRt, "extract")
      const items = await testAddon(app, activeRt, active.text, capture, extract)
      setResults((r) => ({ ...r, [active.id]: { rt: activeRt, items } }))
    } catch (e) {
      toast.error(`Test failed: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setRunning(false)
    }
  }

  const addNote = () => {
    const id = `note-new-${++counter.current}`
    const name = uniqueName("Untitled note", notes)
    setNotes((ns) => [...ns, { id, name, text: "" }])
    setActiveId(id)
    setLeftView("note")
    setView("raw")
  }

  const uploadNote = async (file: File) => {
    const text = await file.text()
    const id = `note-up-${++counter.current}`
    const name = uniqueName(file.name.replace(/\.[^.]+$/, "") || "Uploaded note", notes)
    setNotes((ns) => [...ns, { id, name, text }])
    setActiveId(id)
  }

  const renameNote = (id: string, name: string) =>
    setNotes((ns) => ns.map((n) => (n.id === id ? { ...n, name } : n)))

  const deleteNote = (id: string) =>
    setNotes((ns) => {
      const next = ns.filter((n) => n.id !== id)
      if (id === activeId) setActiveId(next[0]?.id ?? "")
      return next
    })

  const editText = (id: string, text: string) =>
    setNotes((ns) => ns.map((n) => (n.id === id ? { ...n, text } : n)))

  return (
    <div className="flex-1 min-h-0 flex">
      <section className="w-1/2 shrink-0 border-r flex flex-col min-h-0">
        <header className="h-10 shrink-0 border-b px-3 flex items-center gap-1 min-w-0">
          <NoteSelect
            notes={notes}
            active={active}
            onSelect={setActiveId}
            onAdd={addNote}
            onUpload={uploadNote}
            onRename={renameNote}
            onDelete={deleteNote}
          />
          <div className="flex items-center gap-0.5 shrink-0">
            <HdrBtn active={leftView === "note"} onClick={() => setLeftView("note")} label="Note">
              <FileText className="size-3.5" />
            </HdrBtn>
            <HdrBtn active={leftView === "testing"} onClick={() => setLeftView("testing")} label="Testing">
              <ListChecks className="size-3.5" />
            </HdrBtn>
          </div>
          <div className="flex-1" />
          {leftView === "note" && active && <ViewToggle value={view} onChange={setView} />}
        </header>

        <div className="flex-1 min-h-0 flex flex-col">
          {leftView === "testing" ? (
            running ? (
              <div className="flex-1 flex items-center justify-center text-muted-foreground">
                <Loader2 className="size-5 animate-spin" />
              </div>
            ) : results[activeId] ? (
              <ResultList result={results[activeId]} />
            ) : (
              <Empty className="flex-1 min-h-0">
                <EmptyHeader>
                  <EmptyMedia variant="icon"><ListChecks /></EmptyMedia>
                  <EmptyTitle>No results yet</EmptyTitle>
                  <EmptyDescription>Run the prompt on this note to see what it extracts.</EmptyDescription>
                </EmptyHeader>
              </Empty>
            )
          ) : !active ? (
            <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
              No testing note. Add one from the menu above.
            </div>
          ) : view === "raw" ? (
            <textarea
              value={active.text}
              onChange={(e) => editText(active.id, e.target.value)}
              placeholder="Paste a clinical note…"
              spellCheck={false}
              className="flex-1 min-h-0 w-full resize-none bg-transparent p-3 font-mono text-xs leading-relaxed outline-none placeholder:text-muted-foreground"
            />
          ) : (
            <NoteReader
              key={active.id}
              document={{ id: active.id, type: active.name, date: "", author: "", text: active.text }}
              citations={[]}
              className="px-3 py-3"
            />
          )}
        </div>
      </section>

      <section className="flex-1 min-w-0 flex flex-col min-h-0">
        <header className="h-10 shrink-0 border-b px-3 flex items-center gap-2 min-w-0">
          <ResourceSelect
            types={types}
            active={activeRt}
            onSelect={(rt) => { setActiveRt(rt); setConfirming(null) }}
            lane={lane}
            onLane={(l) => { setLane(l); setConfirming(null) }}
          />
          <div className="flex-1" />
          <div className="flex items-center gap-0.5 shrink-0">
            <Tip label="Test on note">
              <button
                onClick={runTest}
                disabled={!active || drafting || running || confirming !== null}
                aria-label="Test on note"
                className="size-7 inline-flex items-center justify-center rounded-md text-primary hover:bg-primary/10 cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
              >
                {running ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-3.5" />}
              </button>
            </Tip>
            <Tip label="Save">
              <button
                onClick={() => setConfirming("save")}
                disabled={!dirty || drafting || running}
                aria-label="Save"
                className={cn(
                  "size-7 inline-flex items-center justify-center rounded-md text-primary hover:bg-primary/10 cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent",
                  confirming === "save" && "bg-primary/10",
                )}
              >
                <Check className="size-4" />
              </button>
            </Tip>
            <Tip label="Revert to saved">
              <button
                onClick={() => setConfirming("revert")}
                disabled={!dirty || drafting || running}
                aria-label="Revert to saved"
                className={cn(
                  "size-7 inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent",
                  confirming === "revert" && "bg-accent text-foreground",
                )}
              >
                <Undo2 className="size-3.5" />
              </button>
            </Tip>
          </div>
        </header>

        {confirming ? (
          <PromptConfirmView
            action={confirming}
            rt={activeRt}
            lane={lane}
            onCancel={() => setConfirming(null)}
            onConfirm={() => { confirming === "save" ? save() : revert(); setConfirming(null) }}
          />
        ) : (
          <>
            <div className="flex-1 min-h-0 flex flex-col">
              <textarea
                value={addonText}
                onChange={(e) => editAddon(e.target.value)}
                placeholder={lane === "capture"
                  ? `Add capture rules — which sentences count as ${activeRt}…`
                  : `Add extraction rules for ${activeRt}…`}
                spellCheck={false}
                disabled={running}
                className="flex-1 min-h-0 w-full resize-none bg-transparent p-3 font-mono text-xs leading-relaxed outline-none placeholder:text-muted-foreground disabled:opacity-50 disabled:cursor-not-allowed"
              />
            </div>

            <Composer
              onSend={draftPrompt}
              isLoading={drafting}
              disabled={running}
              placeholder={lane === "capture" ? "Describe what it should capture…" : "Describe a rule to add…"}
            />
          </>
        )}
      </section>
    </div>
  )
}

function NoteSelect({
  notes,
  active,
  onSelect,
  onAdd,
  onUpload,
  onRename,
  onDelete,
}: {
  notes: TestNote[]
  active: TestNote | null
  onSelect: (id: string) => void
  onAdd: () => void
  onUpload: (file: File) => void | Promise<void>
  onRename: (id: string, name: string) => void
  onDelete: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])

  return (
    <div className="relative min-w-0 flex items-center gap-0.5" ref={ref}>
      {active ? (
        <input
          value={active.name}
          onChange={(e) => onRename(active.id, e.target.value)}
          onBlur={(e) => { if (!e.target.value.trim()) onRename(active.id, "Untitled note") }}
          onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur() }}
          spellCheck={false}
          aria-label="Note name"
          size={Math.max(active.name.length, 2)}
          className="bg-transparent text-sm font-medium outline-none cursor-text field-sizing-content min-w-[3ch] max-w-[130px]"
        />
      ) : (
        <span className="text-sm font-medium text-muted-foreground px-1">No note</span>
      )}
      <Tip label="Switch note">
        <button
          onClick={() => setOpen((o) => !o)}
          aria-label="Switch note"
          className="shrink-0 size-6 inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground cursor-pointer"
        >
          <ChevronDown className="size-3.5" />
        </button>
      </Tip>

      {open && (
        <div className="absolute left-0 top-8 z-20 w-44 rounded-md border bg-card text-card-foreground shadow-md py-1">
          {notes.map((n) => (
            <div
              key={n.id}
              onClick={() => { onSelect(n.id); setOpen(false) }}
              className={cn(
                "group flex items-center gap-2 px-2 py-1.5 text-xs cursor-pointer",
                active?.id === n.id ? "bg-muted font-medium" : "hover:bg-accent",
              )}
            >
              <span className="truncate flex-1 text-left">{n.name}</span>
              {!n.base && (
                <button
                  onClick={(e) => { e.stopPropagation(); onDelete(n.id) }}
                  aria-label="Delete note"
                  className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive shrink-0 cursor-pointer"
                >
                  <Trash2 className="size-3" />
                </button>
              )}
            </div>
          ))}
          <div className="my-1 border-t" />
          <button
            onClick={() => { onAdd(); setOpen(false) }}
            className="w-full flex items-center gap-1.5 px-2 py-1.5 text-xs hover:bg-accent cursor-pointer"
          >
            <Plus className="size-3" /> New note
          </button>
          <button
            onClick={() => fileRef.current?.click()}
            className="w-full flex items-center gap-1.5 px-2 py-1.5 text-xs hover:bg-accent cursor-pointer"
          >
            <Upload className="size-3" /> Upload file…
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".txt,.md,.markdown,text/*"
            className="hidden"
            onChange={async (e) => {
              const f = e.target.files?.[0]
              if (f) await onUpload(f)
              e.target.value = ""
              setOpen(false)
            }}
          />
        </div>
      )}
    </div>
  )
}

function ResultList({ result }: { result: TestResult }) {
  if (result.items.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground px-6 text-center">
        No {result.rt} extracted from this note.
      </div>
    )
  }
  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="divide-y">
        {result.items.map((item, i) => {
          const tk = titleKeyOf(item)
          const title = tk ? (item[tk] as string) : null
          const skip = new Set(FIELD_SKIP)
          if (tk) skip.add(tk)
          const fields = flatten(item, skip)
          return (
            <div key={i} className="px-3 py-2.5">
              {title && <div className="text-sm font-medium leading-snug">{title}</div>}
              <dl className={cn("flex flex-wrap gap-x-4 gap-y-0.5", title && "mt-1")}>
                {fields.map(([k, v]) => (
                  <div key={k} className="text-xs leading-snug">
                    <dt className="inline text-muted-foreground">{k} </dt>
                    <dd className="inline">{v}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function Tip({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side="bottom" sideOffset={4}>{label}</TooltipContent>
    </Tooltip>
  )
}

function PromptConfirmView({
  action,
  rt,
  lane,
  onCancel,
  onConfirm,
}: {
  action: "save" | "revert"
  rt: string
  lane: Lane
  onCancel: () => void
  onConfirm: () => void
}) {
  const isSave = action === "save"
  const label = RT_LABEL[rt] ?? rt
  return (
    <Empty className="flex-1 min-h-0">
      <EmptyHeader>
        <EmptyMedia variant="icon" className={cn(isSave ? "text-primary" : "text-destructive")}>
          {isSave ? <Check className="size-5" /> : <Undo2 className="size-5" />}
        </EmptyMedia>
        <EmptyTitle>{isSave ? "Save prompt" : "Revert changes"}</EmptyTitle>
        <EmptyDescription>
          {isSave ? (
            <>Saves your <span className="font-medium text-foreground">{lane}</span> rules for <span className="font-medium text-foreground">{label}</span> as the active version used in extraction.</>
          ) : (
            <>Discards your unsaved edits to the <span className="font-medium text-foreground">{lane}</span> rules for <span className="font-medium text-foreground">{label}</span> and restores the last saved version.</>
          )}
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <div className="flex items-center justify-center gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
          <Button size="sm" variant={isSave ? "default" : "destructive"} onClick={onConfirm}>
            {isSave ? <Check className="size-3.5" /> : <Undo2 className="size-3.5" />}
            {isSave ? "Save" : "Revert"}
          </Button>
        </div>
      </EmptyContent>
    </Empty>
  )
}

function HdrBtn({
  children,
  active,
  onClick,
  label,
}: {
  children: React.ReactNode
  active: boolean
  onClick: () => void
  label: string
}) {
  return (
    <Tip label={label}>
      <button
        onClick={onClick}
        aria-label={label}
        className={cn(
          "size-7 inline-flex items-center justify-center rounded-md cursor-pointer transition-colors",
          active ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground",
        )}
      >
        {children}
      </button>
    </Tip>
  )
}

function ResourceSelect({
  types,
  active,
  onSelect,
  lane,
  onLane,
}: {
  types: string[]
  active: string
  onSelect: (rt: string) => void
  lane: Lane
  onLane: (l: Lane) => void
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
    <div className="relative min-w-0" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 text-sm font-medium cursor-pointer hover:opacity-80 outline-none max-w-full"
      >
        <span className="truncate max-w-[120px]">{RT_LABEL[active] ?? active ?? "Resource"}</span>
        <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          {lane === "capture" ? "C" : "E"}
        </span>
        <ChevronDown className="size-3.5 text-muted-foreground shrink-0" />
      </button>

      {open && (
        <div className="absolute left-0 top-8 z-20 w-52 rounded-md border bg-card text-card-foreground shadow-md p-1">
          <div className="flex gap-0.5 rounded-md bg-muted/50 p-0.5">
            {(["capture", "extract"] as Lane[]).map((l) => (
              <button
                key={l}
                onClick={() => onLane(l)}
                className={cn(
                  "h-6 flex-1 rounded text-xs capitalize cursor-pointer transition-colors",
                  lane === l ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {l}
              </button>
            ))}
          </div>
          <div className="mt-1" />
          {types.map((rt) => (
            <div
              key={rt}
              onClick={() => { onSelect(rt); setOpen(false) }}
              className={cn(
                "flex items-center rounded px-2 py-1.5 text-xs cursor-pointer",
                active === rt ? "bg-muted font-medium" : "hover:bg-accent",
              )}
            >
              <span className="truncate flex-1 text-left">{RT_LABEL[rt] ?? rt}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ViewToggle({
  value,
  onChange,
}: {
  value: "raw" | "rendered"
  onChange: (v: "raw" | "rendered") => void
}) {
  const editing = value === "raw"
  return (
    <Tip label={editing ? "Done editing" : "Edit note"}>
      <button
        onClick={() => onChange(editing ? "rendered" : "raw")}
        aria-label="Edit note"
        aria-pressed={editing}
        className={cn(
          "size-6 inline-flex items-center justify-center rounded-md transition-colors cursor-pointer",
          editing ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground",
        )}
      >
        <PenTool className="size-3.5" />
      </button>
    </Tip>
  )
}

function Composer({
  onSend,
  isLoading = false,
  disabled = false,
  placeholder = "Describe a rule to add…",
}: {
  onSend: (text: string) => void
  isLoading?: boolean
  disabled?: boolean
  placeholder?: string
}) {
  const [value, setValue] = useState("")
  const ref = useRef<HTMLTextAreaElement>(null)

  const resize = useCallback(() => {
    const ta = ref.current
    if (!ta) return
    ta.style.height = "0"
    const h = Math.min(ta.scrollHeight, MAX_HEIGHT)
    ta.style.height = `${h}px`
    ta.style.overflowY = ta.scrollHeight > MAX_HEIGHT ? "auto" : "hidden"
  }, [])

  const send = useCallback(() => {
    const msg = value.trim()
    if (!msg || isLoading || disabled) return
    setValue("")
    if (ref.current) ref.current.style.height = "auto"
    onSend(msg)
  }, [value, isLoading, disabled, onSend])

  const canSend = value.trim().length > 0 && !isLoading && !disabled

  return (
    <div className="shrink-0 border-t bg-background px-2.5 py-1.5 flex items-end gap-1.5">
      <textarea
        ref={ref}
        value={value}
        onInput={(e: FormEvent<HTMLTextAreaElement>) => { setValue(e.currentTarget.value); resize() }}
        onKeyDown={(e: KeyboardEvent<HTMLTextAreaElement>) => {
          if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send() }
        }}
        placeholder={placeholder}
        rows={1}
        disabled={disabled}
        className="flex-1 resize-none bg-transparent px-1 py-1 text-sm leading-5 outline-none placeholder:text-muted-foreground disabled:opacity-50 disabled:cursor-not-allowed"
        style={{ minHeight: 28, maxHeight: MAX_HEIGHT }}
      />
      <button
        type="button"
        onClick={send}
        disabled={!canSend}
        className={cn(
          "flex size-7 shrink-0 items-center justify-center rounded-full border transition-colors",
          canSend ? "cursor-pointer text-foreground hover:bg-accent" : "cursor-not-allowed text-muted-foreground opacity-50",
        )}
        aria-label="Send"
      >
        {isLoading ? <Loader2 className="size-4 animate-spin" /> : <ArrowUp className="size-4" />}
      </button>
    </div>
  )
}

const MOCK_ADDON = "- **Capture cancer staging as a separate Observation**, not in the Condition name — keep the Condition to the core diagnosis.\n- **Record laterality** (left/right/bilateral) when stated, as a body-site qualifier."

async function draftAddon(
  app: App | null, lane: Lane, rt: string, note: string, ideas: string, current: string,
): Promise<string> {
  if (!app) { await new Promise((r) => setTimeout(r, 600)); return MOCK_ADDON }
  const res = await callTool(app, "DraftPromptAddon", {
    resource_type: rt, note, ideas, current_addon: current, lane,
  })
  return parseStructured<{ addon: string }>(res)?.addon ?? ""
}
