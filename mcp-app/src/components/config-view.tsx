import { useEffect, useState } from "react"
import type { App } from "@modelcontextprotocol/ext-apps"
import type { LucideIcon } from "lucide-react"
import {
  BookPlus,
  KeyRound,
  ListChecks,
  Loader2,
  ScanText,
  ScrollText,
  ShieldCheck,
  UserRound,
} from "lucide-react"
import { callTool, parseStructured } from "../mcp"
import type { Preset, UsageData, UserConfig, UserRecognition } from "../types"
import { cn } from "../lib/cn"
import { BASE_IG } from "../lib/ig-catalog"
import { MOCK_USAGE } from "../mock"
import { IgSection } from "./ig-section"
import { ResourcesSection } from "./resources-section"
import { TerminologySection } from "./terminology-section"
import { PromptsSection } from "./prompts-section"

type Section = "account" | "ig" | "resources" | "coding" | "prompts"

type SectionDef = { id: Section; label: string; icon: LucideIcon }

const ACCOUNT: SectionDef = { id: "account", label: "Account", icon: UserRound }
// Preset-scoped sections — these change with the active preset.
const PRESET_SECTIONS: SectionDef[] = [
  { id: "ig", label: "FHIR IG", icon: ScrollText },
  { id: "resources", label: "Resources", icon: ListChecks },
  { id: "coding", label: "Terminology", icon: BookPlus },
  { id: "prompts", label: "Prompts", icon: ScanText },
]
const SECTIONS: SectionDef[] = [ACCOUNT, ...PRESET_SECTIONS]

export function ConfigView({
  app,
  config,
  onSaved,
  presets,
  activeId,
  onUpdatePreset,
  user,
}: {
  app: App | null
  config: UserConfig | null
  onSaved: (config: UserConfig) => void
  presets: Preset[]
  activeId: string
  onUpdatePreset: (id: string, patch: Partial<Preset>) => void
  user?: UserRecognition | null
}) {
  const [section, setSection] = useState<Section>("account")
  const activePreset = presets.find((p) => p.id === activeId) ?? presets[0]

  return (
    <div className="flex-1 min-h-0 flex">
      <nav className="w-36 shrink-0 border-r flex flex-col select-none">
        <div className="flex-1 min-h-0 overflow-y-auto">
          {PRESET_SECTIONS.map((s) => (
            <RailButton key={s.id} s={s} active={section === s.id} onClick={() => setSection(s.id)} />
          ))}
        </div>

        <div className="shrink-0 border-t">
          <RailButton s={ACCOUNT} active={section === "account"} onClick={() => setSection("account")} />
        </div>
      </nav>

      <div className="flex-1 min-w-0 min-h-0 flex flex-col">
        {section === "account" ? (
          <AccountSection app={app} config={config} onSaved={onSaved} user={user} />
        ) : section === "ig" && activePreset ? (
          <IgSection
            preset={activePreset}
            onChange={(specialty) => onUpdatePreset(activePreset.id, { ig: { base: activePreset.ig.base || BASE_IG, specialty } })}
          />
        ) : section === "resources" && activePreset ? (
          <ResourcesSection
            preset={activePreset}
            onChange={(resources) => onUpdatePreset(activePreset.id, { resources })}
          />
        ) : section === "coding" && activePreset ? (
          <TerminologySection
            app={app}
            preset={activePreset}
            onChange={(coding) => onUpdatePreset(activePreset.id, { coding })}
          />
        ) : section === "prompts" && activePreset ? (
          <PromptsSection
            app={app}
            preset={activePreset}
            onChange={(patch) => onUpdatePreset(activePreset.id, patch)}
          />
        ) : null}
      </div>
    </div>
  )
}

function AccountSection({
  app,
  config,
  onSaved,
  user,
}: {
  app: App | null
  config: UserConfig | null
  onSaved: (config: UserConfig) => void
  user?: UserRecognition | null
}) {
  const last4 = config?.byok?.gemini_api_key?.last4 ?? null
  const [editing, setEditing] = useState(false)
  const [key, setKey] = useState("")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [usage, setUsage] = useState<UsageData | null>(null)

  useEffect(() => {
    if (!app) { setUsage(MOCK_USAGE); return }
    let cancelled = false
    ;(async () => {
      try {
        const res = await callTool(app, "GetUsage", {})
        const data = parseStructured<UsageData>(res)
        if (!cancelled && data) setUsage(data)
      } catch { /* usage is best-effort */ }
    })()
    return () => { cancelled = true }
  }, [app])

  async function save() {
    const trimmed = key.trim()
    if (!trimmed) return
    setSaving(true)
    setError(null)
    try {
      if (app) {
        const res = await callTool(app, "SetUserConfig", { patch: { byok: { gemini_api_key: trimmed } } })
        const data = parseStructured<{ config: UserConfig }>(res)
        if (!data?.config) throw new Error("Save failed")
        onSaved(data.config)
      } else {
        await new Promise((r) => setTimeout(r, 450))
        onSaved({ byok: { gemini_api_key: { set: true, last4: trimmed.slice(-4) } } })
      }
      setKey("")
      setEditing(false)
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="px-4 py-3 space-y-4 max-w-md">
      <section className="space-y-0.5">
        <h2 className="text-base font-semibold truncate">{user?.display_name ?? "Clinician"}</h2>
        {user && (
          <p className="text-xs text-muted-foreground">Member since {fmtAccountDate(user.first_seen_at)}</p>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-xs font-medium text-muted-foreground">Gemini API key</h2>
        {editing ? (
          <div className="space-y-1.5">
            <div className="relative">
              <KeyRound className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground pointer-events-none" />
              <input
                type="password"
                value={key}
                onChange={(e) => { setKey(e.target.value); setError(null) }}
                onKeyDown={(e) => { if (e.key === "Enter") save(); if (e.key === "Escape") { setEditing(false); setKey(""); setError(null) } }}
                placeholder="AIza…"
                autoComplete="off"
                spellCheck={false}
                autoFocus
                className="w-full h-9 pl-8 pr-3 text-sm rounded-md border bg-transparent outline-none focus:border-foreground/40 transition-colors placeholder:text-muted-foreground font-mono"
              />
            </div>
            {error && <p className="text-xs text-destructive">{error}</p>}
            <div className="flex items-center gap-2">
              <button
                onClick={save}
                disabled={saving || !key.trim()}
                className="h-8 px-3 text-xs rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 cursor-pointer font-medium inline-flex items-center gap-1.5"
              >
                {saving && <Loader2 className="size-3 animate-spin" />}
                {saving ? "Saving…" : "Save"}
              </button>
              <button
                onClick={() => { setEditing(false); setKey(""); setError(null) }}
                disabled={saving}
                className="h-8 px-3 text-xs rounded-md border hover:bg-accent cursor-pointer disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-2.5 rounded-md border bg-muted/40 px-3 py-2.5">
            <ShieldCheck className="size-4 text-primary shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium">Connected</div>
              <div className="text-xs text-muted-foreground font-mono tabular-nums">····{last4 ?? "????"}</div>
            </div>
            <button
              onClick={() => { setEditing(true); setKey(""); setError(null) }}
              className="text-xs px-2.5 h-7 rounded-md border hover:bg-accent cursor-pointer shrink-0"
            >
              Replace
            </button>
          </div>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-xs font-medium text-muted-foreground">Usage</h2>
        <p className="text-[11px] text-muted-foreground">Runs on Gemini 3.5 Flash · guardrail on 3.1 Flash-Lite.</p>
        {!usage ? (
          <div className="text-xs text-muted-foreground">Loading…</div>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-2">
              <Stat label="Runs" value={String(usage.summary.runs)} />
              <Stat label="Spend" value={`$${usage.summary.total_cost_usd.toFixed(4)}`} />
              <Stat label="Tokens" value={fmtTokens(usage.summary.input_tokens + usage.summary.output_tokens)} />
            </div>
            <div className="rounded-md border divide-y">
              {usage.runs.length === 0 ? (
                <div className="px-3 py-4 text-xs text-muted-foreground text-center">No runs yet</div>
              ) : (
                usage.runs.slice(0, 6).map((r) => (
                  <div
                    key={r.id}
                    title={fmtExact(r.ts)}
                    className="grid grid-cols-5 gap-2 px-3 py-1.5 text-xs tabular-nums"
                  >
                    <span className="text-muted-foreground truncate">{relativeTime(r.ts)}</span>
                    <span className="text-muted-foreground text-right">{r.doc_count} docs</span>
                    <span className="text-muted-foreground text-right">{fmtDuration(r.duration_ms)}</span>
                    <span className="text-muted-foreground text-right">{fmtTokens(r.input_tokens + r.output_tokens)}</span>
                    <span className="text-right">${r.cost_usd.toFixed(4)}</span>
                  </div>
                ))
              )}
            </div>
          </>
        )}
      </section>
      </div>
    </div>
  )
}

function RailButton({ s, active, onClick }: { s: SectionDef; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full flex items-center gap-2 px-3 h-10 text-sm cursor-pointer transition-colors",
        active ? "bg-muted text-foreground font-medium" : "text-muted-foreground hover:bg-muted/50",
      )}
    >
      <s.icon className="size-4 shrink-0" />
      <span className="truncate">{s.label}</span>
    </button>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border px-3 py-2">
      <div className="text-sm font-semibold tabular-nums truncate">{value}</div>
      <div className="text-[11px] text-muted-foreground">{label}</div>
    </div>
  )
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function relativeTime(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ""
  const s = Math.floor((Date.now() - d.getTime()) / 1000)
  if (s < 60) return "just now"
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const days = Math.floor(h / 24)
  if (days < 7) return `${days}d ago`
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" })
}

function fmtExact(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
  })
}

function fmtDuration(ms: number | null): string {
  if (!ms || ms <= 0) return ""
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${s % 60}s`
}

function fmtAccountDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (isNaN(d.getTime())) return "—"
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
}
