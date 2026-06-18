import { useState } from "react"
import type { App } from "@modelcontextprotocol/ext-apps"
import { Check, ExternalLink, KeyRound, Loader2, ShieldCheck } from "lucide-react"
import { callTool, parseStructured } from "../mcp"
import type { UserConfig } from "../types"

export function ConfigView({
  app,
  config,
  byokEnabled,
  logoUrl,
  onSaved,
}: {
  app: App | null
  config: UserConfig | null
  byokEnabled: boolean
  logoUrl: string
  onSaved: (config: UserConfig) => void
}) {
  const existing = config?.byok?.gemini_api_key ?? null
  const [key, setKey] = useState("")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [last4, setLast4] = useState<string | null>(existing?.set ? existing.last4 : null)
  const [replacing, setReplacing] = useState(false)

  const configured = !!last4
  const showInput = byokEnabled && (!configured || replacing)

  async function save() {
    const trimmed = key.trim()
    if (!trimmed) return
    setSaving(true)
    setError(null)
    try {
      let l4 = trimmed.slice(-4)
      if (app) {
        const res = await callTool(app, "SetUserConfig", { patch: { byok: { gemini_api_key: trimmed } } })
        const data = parseStructured<{ config: UserConfig }>(res)
        if (!data?.config) throw new Error("save failed")
        l4 = data.config.byok?.gemini_api_key?.last4 ?? l4
        onSaved(data.config)
      } else {
        await new Promise((r) => setTimeout(r, 450))
        onSaved({ byok: { gemini_api_key: { set: true, last4: l4 } } })
      }
      setLast4(l4)
      setKey("")
      setReplacing(false)
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto flex items-center justify-center px-4 py-8">
      <div className="w-full max-w-[420px] flex flex-col items-center space-y-4">
        <img src={logoUrl} alt="Anamnesis" width={48} height={48} className="size-12" />
        <div className="text-center space-y-1.5">
          <h1 className="text-xl font-semibold tracking-tight">
            {configured && !replacing ? "Gemini connected" : "Connect Gemini"}
          </h1>
          <p className="text-sm text-muted-foreground leading-relaxed">
            {configured && !replacing
              ? "Anamnesis runs on your Gemini key. It's encrypted at rest and never leaves the server."
              : "Anamnesis runs on your Gemini key — the same one you use for the chat. Paste it to enable augmentation."}
          </p>
        </div>

        {!byokEnabled ? (
          <p className="text-xs text-muted-foreground text-center rounded-md border bg-muted/40 px-3 py-2">
            BYOK isn't enabled on this server (CONFIG_SECRET_KEY unset), so keys can't be
            stored. Augmentation is unavailable until the operator enables it.
          </p>
        ) : configured && !replacing ? (
          <div className="w-full space-y-2">
            <div className="flex items-center gap-2.5 rounded-md border bg-muted/40 px-3 py-2.5">
              <ShieldCheck className="size-4 text-success-fg shrink-0" />
              <div className="flex-1 min-w-0 text-left">
                <div className="text-sm font-medium">API key connected</div>
                <div className="text-xs text-muted-foreground font-mono tabular-nums">····{last4}</div>
              </div>
            </div>
            <button
              onClick={() => { setReplacing(true); setError(null) }}
              className="w-full h-9 text-sm rounded-md border hover:bg-accent transition-colors cursor-pointer font-medium"
            >
              Replace key
            </button>
          </div>
        ) : (
          <div className="w-full space-y-2">
            <div className="relative">
              <KeyRound className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground pointer-events-none" />
              <input
                type="password"
                value={key}
                onChange={(e) => { setKey(e.target.value); setError(null) }}
                onKeyDown={(e) => { if (e.key === "Enter") save() }}
                placeholder="AIza…"
                autoComplete="off"
                spellCheck={false}
                autoFocus
                className="w-full h-9 pl-8 pr-3 text-sm rounded-md border bg-transparent outline-none focus:border-foreground/40 transition-colors placeholder:text-muted-foreground font-mono"
              />
            </div>
            {error && <p className="text-xs text-destructive">{error}</p>}
            <button
              onClick={save}
              disabled={saving || !key.trim()}
              className="w-full h-9 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors cursor-pointer font-medium disabled:opacity-50 inline-flex items-center justify-center gap-2"
            >
              {saving && <Loader2 className="size-3.5 animate-spin" />}
              {saving ? "Saving…" : "Save key"}
            </button>
            {replacing && (
              <button
                onClick={() => { setReplacing(false); setKey(""); setError(null) }}
                className="w-full h-9 text-sm rounded-md border hover:bg-accent transition-colors cursor-pointer font-medium"
              >
                Cancel
              </button>
            )}
            <p className="text-[11px] text-muted-foreground inline-flex items-center gap-1.5">
              <Check className="size-3" /> Encrypted at rest · never leaves the server · never shown again
            </p>
          </div>
        )}

        {showInput && (
          <a
            href="https://aistudio.google.com/apikey"
            target="_blank"
            rel="noopener noreferrer"
            className="text-[11px] text-muted-foreground hover:text-foreground transition-colors inline-flex items-center gap-1"
          >
            Get a Gemini API key
            <ExternalLink className="size-3" />
          </a>
        )}
      </div>
    </div>
  )
}
