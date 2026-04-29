"use client"

import { useState, useEffect, useRef } from "react"
import { CalendarIcon, Clock } from "lucide-react"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Calendar } from "@/components/ui/calendar"
import { cn } from "@/lib/utils"

const HOURS = Array.from({ length: 24 }, (_, i) => i)
const MINUTES = Array.from({ length: 60 }, (_, i) => i)

function TimePickerColumn({ items, selected, onSelect }: { items: number[]; selected: number; onSelect: (v: number) => void }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const itemRefs = useRef<Map<number, HTMLButtonElement>>(new Map())

  useEffect(() => {
    const el = itemRefs.current.get(selected)
    if (el && containerRef.current) {
      el.scrollIntoView({ block: "center", behavior: "instant" })
    }
  }, [selected])

  return (
    <div ref={containerRef} className="h-48 overflow-y-auto flex-1 [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
      {items.map((item) => (
        <button
          key={item}
          ref={(el) => { if (el) itemRefs.current.set(item, el) }}
          onClick={() => onSelect(item)}
          className={cn(
            "w-full h-8 text-xs transition-colors rounded cursor-pointer",
            item === selected
              ? "bg-primary text-primary-foreground"
              : "hover:bg-accent text-muted-foreground hover:text-foreground"
          )}
        >
          {String(item).padStart(2, "0")}
        </button>
      ))}
    </div>
  )
}

interface DateTimePickerProps {
  value: string        // ISO string or ""
  onChange: (iso: string) => void
  className?: string
}

export function DateTimePicker({ value, onChange, className }: DateTimePickerProps) {
  const [dateOpen, setDateOpen] = useState(false)
  const [timeOpen, setTimeOpen] = useState(false)

  const date = value ? new Date(value) : undefined
  const dateStr = date
    ? `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`
    : ""
  const h = date ? date.getHours() : 9
  const m = date ? date.getMinutes() : 0

  const buildIso = (newDate: string, newH: number, newM: number) => {
    if (!newDate) return ""
    return new Date(`${newDate}T${String(newH).padStart(2, "0")}:${String(newM).padStart(2, "0")}`).toISOString()
  }

  const handleDateSelect = (d: Date | undefined) => {
    if (!d) return
    const y = d.getFullYear()
    const mo = String(d.getMonth() + 1).padStart(2, "0")
    const dy = String(d.getDate()).padStart(2, "0")
    onChange(buildIso(`${y}-${mo}-${dy}`, h, m))
    setDateOpen(false)
  }

  const displayDate = date
    ? date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
    : null
  const displayTime = date
    ? `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`
    : null

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <Popover open={dateOpen} onOpenChange={setDateOpen}>
        <PopoverTrigger asChild>
          <button className="h-8 rounded-md border border-input bg-background px-2 text-xs inline-flex items-center gap-1.5 hover:bg-accent/50 transition-colors cursor-pointer">
            <CalendarIcon className="size-3 text-muted-foreground" />
            {displayDate ?? <span className="text-muted-foreground">Pick date</span>}
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0" align="start">
          <Calendar
            mode="single"
            selected={date}
            onSelect={handleDateSelect}
            initialFocus
          />
        </PopoverContent>
      </Popover>

      <Popover open={timeOpen} onOpenChange={setTimeOpen}>
        <PopoverTrigger asChild>
          <button
            className="h-8 rounded-md border border-input bg-background px-2 text-xs inline-flex items-center gap-1.5 hover:bg-accent/50 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            disabled={!dateStr}
          >
            <Clock className="size-3 text-muted-foreground" />
            {displayTime ?? "Time"}
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-32 p-2" align="start">
          <div className="flex gap-1">
            <TimePickerColumn
              items={HOURS}
              selected={h}
              onSelect={(hour) => { onChange(buildIso(dateStr, hour, m)); setTimeOpen(false) }}
            />
            <div className="w-px bg-border" />
            <TimePickerColumn
              items={MINUTES}
              selected={m}
              onSelect={(minute) => { onChange(buildIso(dateStr, h, minute)); setTimeOpen(false) }}
            />
          </div>
        </PopoverContent>
      </Popover>
    </div>
  )
}
