"use client"

import { cn } from "@/lib/utils"

interface Props {
  options: string[]
  onPick: (option: string) => void
  disabled?: boolean
}

export function ActionChoices({ options, onPick, disabled }: Props) {
  if (options.length === 0) return null
  return (
    <div className="flex flex-wrap gap-1.5 mt-1">
      {options.map((opt) => (
        <button
          key={opt}
          type="button"
          onClick={() => onPick(opt)}
          disabled={disabled}
          className={cn(
            "rounded-full border border-border px-3 py-1 text-xs transition-colors",
            "hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer",
          )}
        >
          {opt}
        </button>
      ))}
    </div>
  )
}

const CHOICES_RE = /```choices\s*\n([\s\S]*?)```/

export function extractChoices(content: string): { stripped: string; options: string[] } {
  const match = content.match(CHOICES_RE)
  if (!match) return { stripped: content, options: [] }
  const options = match[1]
    .split("\n")
    .map((l) => l.replace(/^\s*-\s*/, "").trim())
    .filter(Boolean)
  const stripped = content.replace(CHOICES_RE, "").trimEnd()
  return { stripped, options }
}
