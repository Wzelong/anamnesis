"use client"

import { useRef, useCallback, useEffect, useState, type KeyboardEvent, type ChangeEvent } from "react"
import { ArrowUp } from "lucide-react"
import { cn } from "@/lib/utils"

const MAX_HEIGHT = 200
const MOBILE_BREAKPOINT = 768

interface AutoInputProps {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  disabled?: boolean
  loading?: boolean
  placeholder?: string
  className?: string
}

export function AutoInput({ value, onChange, onSend, disabled, loading, placeholder, className }: AutoInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [mobile, setMobile] = useState(false)
  const [focused, setFocused] = useState(false)

  const resize = useCallback(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`
  }, [])

  useEffect(() => {
    const media = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
    const update = () => setMobile(media.matches)
    update()
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", update)
    } else {
      media.addListener(update)
    }
    return () => {
      if (typeof media.removeEventListener === "function") {
        media.removeEventListener("change", update)
      } else {
        media.removeListener(update)
      }
    }
  }, [])

  useEffect(() => {
    resize()
  }, [value, resize])

  function handleChange(e: ChangeEvent<HTMLTextAreaElement>) {
    onChange(e.target.value)
    resize()
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      if (value.trim() && !disabled && !loading) onSend()
    }
  }

  const canSend = value.trim().length > 0 && !disabled && !loading
  const minHeight = mobile ? (focused ? 84 : 56) : undefined

  return (
    <div className={cn("relative flex items-end rounded-md border border-border bg-background", className)}>
      <textarea
        ref={textareaRef}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={disabled || loading}
        rows={1}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        className="flex-1 resize-none bg-transparent px-3 py-2 text-sm outline-none placeholder:text-muted-foreground disabled:opacity-50 transition-[min-height] duration-150"
        style={{ maxHeight: MAX_HEIGHT, minHeight }}
      />
      <button
        type="button"
        onClick={onSend}
        disabled={!canSend}
        className={cn(
          "mb-1.5 mr-1.5 flex size-6 shrink-0 items-center justify-center rounded-full transition-colors",
          canSend ? "bg-foreground text-background hover:bg-foreground/80 cursor-pointer" : "bg-muted text-muted-foreground cursor-default",
        )}
      >
        <ArrowUp className="size-3.5" />
      </button>
    </div>
  )
}
