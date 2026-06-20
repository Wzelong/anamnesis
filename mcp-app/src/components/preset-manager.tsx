import { useRef, useState } from "react"
import { Check, Pencil, Plus, Trash2 } from "lucide-react"
import { cn } from "../lib/cn"
import type { PresetMeta } from "../types"

// The preset switcher's "dropdown", inlined into the sidebar: it replaces the
// section nav while open. Adding drops an inline name input — type then commit
// (Enter / blur-with-text) creates and selects; Escape / blur-empty discards.
export function PresetRail({
  presets,
  activeId,
  onSelect,
  onAdd,
  onRename,
  onDelete,
}: {
  presets: PresetMeta[]
  activeId: string
  onSelect: (id: string) => void
  onAdd: (name: string) => void
  onRename: (id: string, name: string) => void
  onDelete: (id: string) => void
}) {
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [draft, setDraft] = useState("")
  const [adding, setAdding] = useState(false)
  const [addDraft, setAddDraft] = useState("")
  const addingRef = useRef(false)

  function startRename(p: PresetMeta) {
    setRenamingId(p.id)
    setDraft(p.name)
  }
  function commitRename() {
    if (renamingId && draft.trim()) onRename(renamingId, draft.trim())
    setRenamingId(null)
  }

  function startAdd() {
    addingRef.current = true
    setAdding(true)
    setAddDraft("")
  }
  // Idempotent: Enter commits then the unmounting input fires blur, which would
  // commit again — the ref guard makes the second call a no-op.
  function commitAdd() {
    if (!addingRef.current) return
    addingRef.current = false
    setAdding(false)
    const name = addDraft.trim()
    if (name) onAdd(name)
    setAddDraft("")
  }
  function cancelAdd() {
    addingRef.current = false
    setAdding(false)
    setAddDraft("")
  }

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      {presets.map((p) => {
        const active = p.id === activeId
        const renaming = renamingId === p.id
        return (
          <div
            key={p.id}
            className={cn(
              "group flex items-center gap-2 pl-3 pr-1.5 h-9 text-sm",
              active ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted/50",
            )}
          >
            <span className="size-4 shrink-0 flex items-center justify-center">
              {active && <Check className="size-3.5 text-primary" />}
            </span>
            {renaming ? (
              <input
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commitRename()
                  if (e.key === "Escape") setRenamingId(null)
                }}
                onBlur={commitRename}
                className="flex-1 min-w-0 h-6 px-1 text-sm rounded border bg-transparent outline-none focus:border-foreground/40"
              />
            ) : (
              <>
                <button onClick={() => onSelect(p.id)} title={p.name} className="flex-1 min-w-0 text-left truncate cursor-pointer">
                  {p.name}
                </button>
                <div className="flex items-center opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                  <button
                    onClick={() => startRename(p)}
                    aria-label="Rename"
                    className="size-5 inline-flex items-center justify-center rounded text-muted-foreground hover:text-foreground cursor-pointer"
                  >
                    <Pencil className="size-3" />
                  </button>
                  {presets.length > 1 && (
                    <button
                      onClick={() => onDelete(p.id)}
                      aria-label="Delete"
                      className="size-5 inline-flex items-center justify-center rounded text-muted-foreground hover:text-destructive cursor-pointer"
                    >
                      <Trash2 className="size-3" />
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        )
      })}
      {adding ? (
        <div className="flex items-center gap-2 pl-3 pr-1.5 h-9 text-sm">
          <span className="size-4 shrink-0 flex items-center justify-center">
            <Plus className="size-3.5 text-muted-foreground" />
          </span>
          <input
            autoFocus
            value={addDraft}
            onChange={(e) => setAddDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitAdd()
              if (e.key === "Escape") cancelAdd()
            }}
            onBlur={commitAdd}
            placeholder="Preset name"
            className="flex-1 min-w-0 h-6 px-1 text-sm rounded border bg-transparent outline-none focus:border-foreground/40 placeholder:text-muted-foreground"
          />
        </div>
      ) : (
        <button
          onClick={startAdd}
          className="w-full flex items-center gap-2 pl-3 pr-1.5 h-9 text-sm text-muted-foreground hover:bg-muted/50 cursor-pointer"
        >
          <Plus className="size-4 shrink-0" />
          <span className="truncate">New preset</span>
        </button>
      )}
    </div>
  )
}
