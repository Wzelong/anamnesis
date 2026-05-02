"use client"

import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react"
import { ArrowUp, Square } from "lucide-react"
import { cn } from "@/lib/utils"

const MAX_HEIGHT = 120

interface Props {
  onSend: (message: string) => void | Promise<void>
  onStop?: () => void
  isLoading?: boolean
  placeholder?: string
  initialValue?: string
  focusKey?: number
}

export function ChatInput({
  onSend,
  onStop,
  isLoading = false,
  placeholder = "Ask about this proposal…",
  initialValue,
  focusKey,
}: Props) {
  const [value, setValue] = useState(initialValue ?? "")
  const ref = useRef<HTMLTextAreaElement>(null)

  const resize = useCallback(() => {
    const ta = ref.current
    if (!ta) return
    ta.style.height = "0"
    const h = Math.min(ta.scrollHeight, MAX_HEIGHT)
    ta.style.height = `${h}px`
    ta.style.overflowY = ta.scrollHeight > MAX_HEIGHT ? "auto" : "hidden"
  }, [])

  useEffect(() => {
    if (initialValue !== undefined) {
      setValue(initialValue)
      requestAnimationFrame(() => {
        resize()
        ref.current?.focus()
        const len = ref.current?.value.length ?? 0
        ref.current?.setSelectionRange(len, len)
      })
    }
  }, [initialValue, focusKey, resize])

  const handleSend = useCallback(async () => {
    const msg = value.trim()
    if (!msg || isLoading) return
    setValue("")
    if (ref.current) ref.current.style.height = "auto"
    await onSend(msg)
  }, [value, isLoading, onSend])

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleInput = (e: FormEvent<HTMLTextAreaElement>) => {
    setValue(e.currentTarget.value)
    resize()
  }

  const canSend = value.trim().length > 0 && !isLoading

  return (
    <div className="flex items-end gap-1">
      <textarea
        ref={ref}
        value={value}
        onInput={handleInput}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={isLoading && !onStop}
        rows={1}
        className="flex-1 resize-none bg-transparent px-1 py-1.5 text-base md:text-sm leading-5 outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50"
        style={{ minHeight: 32, maxHeight: MAX_HEIGHT }}
      />
      {isLoading && onStop ? (
        <button
          type="button"
          onClick={onStop}
          className="flex size-8 shrink-0 items-center justify-center rounded-full border bg-foreground text-background hover:bg-foreground/80 cursor-pointer transition-colors"
          aria-label="Stop"
        >
          <Square className="size-3 fill-current" />
        </button>
      ) : (
        <button
          type="button"
          onClick={handleSend}
          disabled={!canSend}
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded-full border transition-colors",
            canSend
              ? "cursor-pointer text-foreground hover:bg-accent"
              : "cursor-not-allowed text-muted-foreground opacity-50",
          )}
          aria-label="Send"
        >
          <ArrowUp className="size-4" />
        </button>
      )}
    </div>
  )
}
