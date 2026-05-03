"use client"

import { useState } from "react"
import { Keyboard } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Kbd, KbdGroup } from "@/components/ui/kbd"
import { useShortcuts } from "@/lib/use-shortcuts"

interface Shortcut {
  label: string
  keys: string[][]
}

interface Group {
  title: string
  items: Shortcut[]
}

const GROUPS: Group[] = [
  {
    title: "Navigation",
    items: [
      { label: "Next proposal", keys: [["J"], ["↓"]] },
      { label: "Previous proposal", keys: [["K"], ["↑"]] },
    ],
  },
  {
    title: "Review",
    items: [
      { label: "Accept", keys: [["A"]] },
      { label: "Reject", keys: [["R"]] },
      { label: "Edit", keys: [["E"]] },
    ],
  },
  {
    title: "View",
    items: [
      { label: "Jump to source notes", keys: [["V"]] },
      { label: "Show keyboard shortcuts", keys: [["?"]] },
    ],
  },
]

export function ShortcutsDialog() {
  const [open, setOpen] = useState(false)

  useShortcuts({
    "?": () => setOpen((v) => !v),
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="cursor-pointer h-7 w-7 text-muted-foreground"
          aria-label="Keyboard shortcuts"
        >
          <Keyboard className="size-3.5" />
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-sm" onCloseAutoFocus={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle className="text-sm font-medium">Keyboard shortcuts</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-5">
          {GROUPS.map((group) => (
            <section key={group.title} className="flex flex-col gap-2">
              <h3 className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                {group.title}
              </h3>
              <ul className="flex flex-col">
                {group.items.map((item) => (
                  <li
                    key={item.label}
                    className="flex items-center justify-between py-1.5 text-sm"
                  >
                    <span className="text-foreground">{item.label}</span>
                    <div className="flex items-center gap-1.5">
                      {item.keys.map((combo, i) => (
                        <div key={i} className="flex items-center gap-1.5">
                          {i > 0 && (
                            <span className="text-[10px] text-muted-foreground/60">or</span>
                          )}
                          <KbdGroup>
                            {combo.map((k) => (
                              <Kbd key={k}>{k}</Kbd>
                            ))}
                          </KbdGroup>
                        </div>
                      ))}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
