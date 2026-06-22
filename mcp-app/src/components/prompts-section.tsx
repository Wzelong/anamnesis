import { useState } from "react"
import type { App } from "@modelcontextprotocol/ext-apps"
import { ChevronDown, ChevronLeft, ChevronRight, Loader2, Sparkles } from "lucide-react"
import type { Preset, PromptOverride } from "../types"
import { IG_CATALOG, igById } from "../lib/ig-catalog"
import { cn } from "../lib/cn"
import { callTool, parseStructured } from "../mcp"
import { Textarea } from "./ui/textarea"

type Item = Record<string, unknown>

function activeAddon(preset: Preset, rt: string): string {
  const o = preset.prompts[rt]
  if (!o) return ""
  return o.versions.find((v) => v.version === o.active_version)?.text ?? o.versions.at(-1)?.text ?? ""
}

export function PromptsSection({
  app,
  preset,
  onChange,
}: {
  app: App | null
  preset: Preset
  onChange: (prompts: Preset["prompts"]) => void
}) {
  const [editing, setEditing] = useState<string | null>(null)
  const types = Object.keys((igById(preset.ig.base) ?? IG_CATALOG.base[0]).resources)

  if (editing) {
    return <PromptEditor app={app} preset={preset} rt={editing} onBack={() => setEditing(null)} onChange={onChange} />
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="px-4 py-3 max-w-md">
        <div className="space-y-0.5 mb-3">
          <h2 className="text-base font-semibold">Prompts</h2>
          <p className="text-xs text-muted-foreground">Add extraction rules on top of the validated base, per type.</p>
        </div>

        <div className="-mx-2">
          {types.map((rt) => {
            const custom = !!activeAddon(preset, rt)
            return (
              <button
                key={rt}
                onClick={() => setEditing(rt)}
                className="group w-full flex items-center gap-3 px-2 h-10 rounded-md text-left cursor-pointer hover:bg-muted/50 transition-colors"
              >
                <span className="text-sm shrink-0">{rt}</span>
                <span className="flex-1 min-w-0 text-xs text-muted-foreground text-right">{custom ? "Custom rules" : "Default"}</span>
                <ChevronRight className="size-4 shrink-0 text-muted-foreground/40 group-hover:text-muted-foreground transition-colors" />
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function PromptEditor({
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
  onChange: (prompts: Preset["prompts"]) => void
}) {
  const saved = activeAddon(preset, rt)
  const [note, setNote] = useState("")
  const [ideas, setIdeas] = useState("")
  const [addon, setAddon] = useState(saved)
  const [busy, setBusy] = useState<"draft" | "test" | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [test, setTest] = useState<{ base: Item[]; addon: Item[] } | null>(null)
  const [showBase, setShowBase] = useState(false)

  async function draft() {
    setBusy("draft"); setError(null)
    try {
      const res = await draftAddon(app, rt, note, ideas, addon)
      setAddon(res)
    } catch (e) { setError(String(e)) } finally { setBusy(null) }
  }

  async function runTest() {
    setBusy("test"); setError(null)
    try {
      setTest(await testAddon(app, rt, note, addon))
    } catch (e) { setError(String(e)) } finally { setBusy(null) }
  }

  function save() {
    const existing = preset.prompts[rt]
    const versions = existing?.versions ?? []
    const next = (versions.reduce((m, v) => Math.max(m, v.version), 0) || 0) + 1
    const override: PromptOverride = { active_version: next, versions: [...versions, { version: next, text: addon.trim() }] }
    onChange({ ...preset.prompts, [rt]: override })
  }

  function reset() {
    const prompts = { ...preset.prompts }
    delete prompts[rt]
    onChange(prompts)
    setAddon(""); setTest(null)
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="px-4 py-3 max-w-md space-y-5">
        <div>
          <div className="flex items-center gap-1">
            <button onClick={onBack} aria-label="Back to Prompts" className="-ml-1.5 size-7 inline-flex items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground cursor-pointer">
              <ChevronLeft className="size-4" />
            </button>
            <h2 className="text-base font-semibold">{rt} prompt</h2>
          </div>
          <p className="text-xs text-muted-foreground mt-1">Rules layer on top of the validated extractor — the base is never replaced.</p>
        </div>

        <section className="space-y-2">
          <Label>Failing note</Label>
          <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Paste a note this type extracted poorly…" className="text-xs min-h-20" spellCheck={false} />
        </section>

        <section className="space-y-2">
          <Label>What to change</Label>
          <Textarea value={ideas} onChange={(e) => setIdeas(e.target.value)} placeholder="Describe the rule to add (e.g. capture cancer stage as a separate Observation, not in the condition name)…" className="text-xs min-h-16" spellCheck={false} />
          <button
            onClick={draft}
            disabled={busy !== null || !ideas.trim()}
            className="h-8 px-3 text-xs rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 cursor-pointer font-medium inline-flex items-center gap-1.5"
          >
            {busy === "draft" ? <Loader2 className="size-3 animate-spin" /> : <Sparkles className="size-3" />}
            {busy === "draft" ? "Drafting…" : "Draft with AI"}
          </button>
        </section>

        <section className="space-y-2">
          <Label>Added rules</Label>
          <Textarea value={addon} onChange={(e) => setAddon(e.target.value)} placeholder="Drafted rules appear here — edit them directly, or refine via the box above." className="text-xs min-h-24" spellCheck={false} />
          <div className="flex items-center gap-2">
            <button
              onClick={runTest}
              disabled={busy !== null || !note.trim() || !addon.trim()}
              className="h-8 px-3 text-xs rounded-md border hover:bg-accent disabled:opacity-50 cursor-pointer inline-flex items-center gap-1.5"
            >
              {busy === "test" && <Loader2 className="size-3 animate-spin" />}
              {busy === "test" ? "Testing…" : "Run test"}
            </button>
            <button
              onClick={save}
              disabled={busy !== null || !addon.trim() || addon.trim() === saved}
              className="h-8 px-3 text-xs rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 cursor-pointer font-medium"
            >
              Save
            </button>
            {saved && (
              <button onClick={reset} disabled={busy !== null} className="h-8 px-3 text-xs rounded-md text-muted-foreground hover:text-foreground disabled:opacity-50 cursor-pointer ml-auto">
                Reset to default
              </button>
            )}
          </div>
        </section>

        {error && <p className="text-xs text-destructive">{error}</p>}

        {test && (
          <section className="space-y-2">
            <Label>Test on this note</Label>
            <div className="grid grid-cols-2 gap-2">
              <DiffList title="Default" items={test.base} />
              <DiffList title="With rules" items={test.addon} />
            </div>
          </section>
        )}

        <section className="space-y-1">
          <button onClick={() => setShowBase((v) => !v)} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground cursor-pointer">
            <ChevronDown className={cn("size-3.5 transition-transform", showBase && "rotate-180")} />
            {showBase ? "Hide" : "View"} default prompt
          </button>
          {showBase && <p className="text-[11px] text-muted-foreground">The base {rt} extraction prompt is maintained by Anamnesis and validated across general notes. Your rules are appended to it.</p>}
        </section>
      </div>
    </div>
  )
}

function DiffList({ title, items }: { title: string; items: Item[] }) {
  return (
    <div className="rounded-md border">
      <div className="px-2.5 py-1 text-[10px] uppercase tracking-wide text-muted-foreground border-b">{title}</div>
      <div className="divide-y max-h-40 overflow-y-auto">
        {items.length === 0 ? (
          <div className="px-2.5 py-2 text-[11px] text-muted-foreground">none</div>
        ) : (
          items.map((it, i) => <div key={i} className="px-2.5 py-1.5 text-[11px] truncate">{itemLabel(it)}</div>)
        )}
      </div>
    </div>
  )
}

function itemLabel(it: Item): string {
  return (it.name || it.full_name || it.substance || it.reaction || "item") as string
}

function Label({ children }: { children: React.ReactNode }) {
  return <h3 className="text-xs font-medium text-muted-foreground">{children}</h3>
}

const MOCK_ADDON = "Strip oncology staging (stage I-IV, TNM) from the condition name; keep only the core diagnosis."
const MOCK_TEST = {
  base: [{ name: "Stage IIIA non-small cell lung cancer" }, { name: "type 2 diabetes" }],
  addon: [{ name: "non-small cell lung cancer" }, { name: "type 2 diabetes" }],
}

async function draftAddon(app: App | null, rt: string, note: string, ideas: string, current: string): Promise<string> {
  if (!app) return MOCK_ADDON
  const res = await callTool(app, "DraftPromptAddon", { resource_type: rt, note, ideas, current_addon: current })
  return parseStructured<{ addon: string }>(res)?.addon ?? ""
}

async function testAddon(app: App | null, rt: string, note: string, addon: string): Promise<{ base: Item[]; addon: Item[] }> {
  if (!app) return MOCK_TEST
  const res = await callTool(app, "TestPromptAddon", { resource_type: rt, note, addon })
  const data = parseStructured<{ base: Item[]; addon: Item[] }>(res)
  return { base: data?.base ?? [], addon: data?.addon ?? [] }
}
