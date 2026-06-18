import { useState } from "react"
import type { App } from "@modelcontextprotocol/ext-apps"
import { Check, ExternalLink, KeyRound, Loader2 } from "lucide-react"
import { callTool, parseStructured } from "../mcp"
import type { UserConfig } from "../types"

export function ConnectGemini({
  app,
  byokEnabled,
  logoUrl,
  onSaved,
  onCancel,
}: {
  app: App | null
  byokEnabled: boolean
  logoUrl: string
  onSaved: (config: UserConfig) => void
  onCancel?: () => void // present = replace mode (shows Cancel); absent = the fixed gate
}) {
  const [key, setKey] = useState("")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    const trimmed = key.trim()
    if (!trimmed) return
    setSaving(true)
    setError(null)
    try {
      if (app) {
        const res = await callTool(app, "SetUserConfig", { patch: { byok: { gemini_api_key: trimmed } } })
        const data = parseStructured<{ config: UserConfig }>(res)
        if (!data?.config) throw new Error("save failed")
        onSaved(data.config)
      } else {
        await new Promise((r) => setTimeout(r, 450))
        onSaved({ byok: { gemini_api_key: { set: true, last4: trimmed.slice(-4) } } })
      }
      setKey("")
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto flex items-center justify-center px-4 py-6">
      <div className="w-full max-w-[380px] flex flex-col items-center space-y-3">
        <img src={logoUrl} alt="Anamnesis" width={36} height={36} className="size-9" />
        <div className="text-center space-y-1">
          <h1 className="text-base font-semibold tracking-tight">Connect Gemini</h1>
          <p className="text-xs text-muted-foreground leading-relaxed">
            Anamnesis runs on your Gemini key — the same one you use for the chat. Paste it
            to enable augmentation. It's encrypted at rest and never leaves the server.
          </p>
        </div>

        {!byokEnabled ? (
          <p className="text-xs text-muted-foreground text-center rounded-md border bg-muted/40 px-3 py-2">
            BYOK isn't enabled on this server (CONFIG_SECRET_KEY unset), so keys can't be
            stored. Augmentation is unavailable until the operator enables it.
          </p>
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
            {onCancel && (
              <button
                onClick={onCancel}
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

        {byokEnabled && (
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
