"use client"

import { Fragment, useEffect, useMemo, useRef, useState } from "react"
import { ChevronLeft, ChevronRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

interface TimeSlotPickerProps {
  value: Date[]
  onChange: (value: Date[]) => void
  startHour?: number
  endHour?: number
  stepMinutes?: number
  daysPerPage?: number
  daysPerPageSm?: number
  maxSelections?: number
  disabledBefore?: Date
  lockedSlots?: Date[]
  className?: string
}

function startOfDay(date: Date) {
  const d = new Date(date)
  d.setHours(0, 0, 0, 0)
  return d
}

function addDays(date: Date, n: number) {
  const d = new Date(date)
  d.setDate(d.getDate() + n)
  return d
}

function TimeSlotPicker({
  value,
  onChange,
  startHour = 9,
  endHour = 21,
  stepMinutes = 30,
  daysPerPage: daysPerPageLg = 7,
  daysPerPageSm,
  maxSelections = 5,
  disabledBefore,
  lockedSlots,
  className,
}: TimeSlotPickerProps) {
  const [isSmall, setIsSmall] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 640px)")
    setIsSmall(mq.matches)
    const handler = (e: MediaQueryListEvent) => setIsSmall(e.matches)
    mq.addEventListener("change", handler)
    return () => mq.removeEventListener("change", handler)
  }, [])

  const daysPerPage = isSmall && daysPerPageSm ? daysPerPageSm : daysPerPageLg
  const cutoff = disabledBefore ?? new Date()
  const [windowStart, setWindowStart] = useState(() => startOfDay(cutoff))

  const days = useMemo(
    () => Array.from({ length: daysPerPage }, (_, i) => addDays(windowStart, i)),
    [windowStart, daysPerPage]
  )

  const timeRows = useMemo(() => {
    const rows: { hour: number; minute: number }[] = []
    for (let h = startHour; h < endHour; h++) {
      for (let m = 0; m < 60; m += stepMinutes) {
        rows.push({ hour: h, minute: m })
      }
    }
    return rows
  }, [startHour, endHour, stepMinutes])

  const selectedSet = useMemo(() => {
    const set = new Set<number>()
    for (const d of value) set.add(d.getTime())
    return set
  }, [value])

  const lockedSet = useMemo(() => {
    const set = new Set<number>()
    if (lockedSlots) for (const d of lockedSlots) set.add(d.getTime())
    return set
  }, [lockedSlots])

  const atMax = value.length >= maxSelections

  // Drag-to-paint state: first cell sets add/remove mode
  const dragging = useRef(false)
  const dragMode = useRef<"add" | "remove">("add")

  function handlePointerDown(t: number, isSelected: boolean) {
    dragging.current = true
    dragMode.current = isSelected ? "remove" : "add"
    applySlot(t)
  }

  function handlePointerMove(e: React.PointerEvent) {
    if (!dragging.current) return
    const el = document.elementFromPoint(e.clientX, e.clientY) as HTMLElement | null
    const t = el?.dataset.t
    if (t) applySlot(Number(t))
  }

  function handlePointerUp() {
    dragging.current = false
  }

  function applySlot(t: number) {
    if (dragMode.current === "remove") {
      const next = value.filter((d) => d.getTime() !== t)
      if (next.length !== value.length) onChange(next)
    } else {
      if (value.length >= maxSelections) return
      if (!value.some((d) => d.getTime() === t)) onChange([...value, new Date(t)])
    }
  }

  function formatTime(hour: number, minute: number) {
    const d = new Date()
    d.setHours(hour, minute, 0, 0)
    return d.toLocaleTimeString("en-US", { hour: "numeric" })
  }

  const canGoBack = windowStart > startOfDay(cutoff)

  return (
    <div className={cn("space-y-2", className)}>
      {/* Navigation */}
      <div className="flex items-center justify-between">
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          disabled={!canGoBack}
          onClick={() => setWindowStart(addDays(windowStart, -daysPerPage))}
        >
          <ChevronLeft className="size-4" />
        </Button>
        <span className="text-xs text-muted-foreground">
          {windowStart.toLocaleDateString("en-US", { month: "short", day: "numeric" })}
          {" \u2013 "}
          {addDays(windowStart, daysPerPage - 1).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
          {" \u00b7 "}
          {value.length}/{maxSelections} selected
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          onClick={() => setWindowStart(addDays(windowStart, daysPerPage))}
        >
          <ChevronRight className="size-4" />
        </Button>
      </div>

      {/* Grid */}
      <div
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
      >
        <div
          className="grid w-fit mx-auto select-none"
          style={{
            gridTemplateColumns: `3.5rem repeat(${daysPerPage}, 3rem) 3.5rem`,
          }}
        >
          {/* Column headers */}
          <div />
          {days.map((day) => (
            <div
              key={day.getTime()}
              className="text-center pb-1.5 select-none"
            >
              <div className="text-[10px] text-muted-foreground">
                {day.toLocaleDateString("en-US", { month: "short", day: "numeric" })}
              </div>
              <div className="text-xs font-medium">
                {day.toLocaleDateString("en-US", { weekday: "short" })}
              </div>
            </div>
          ))}
          <div />

          {/* Time rows */}
          {timeRows.map(({ hour, minute }) => {
            const isHourBoundary = minute === 0
            return (
              <Fragment key={`row-${hour}-${minute}`}>
                {/* Row label */}
                <div
                  className={cn(
                    "flex items-center justify-end pr-2 select-none whitespace-nowrap",
                    isHourBoundary
                      ? "text-[11px] text-muted-foreground"
                      : "text-[10px] text-muted-foreground/50"
                  )}
                >
                  {isHourBoundary ? formatTime(hour, minute) : ""}
                </div>
                {/* Cells */}
                {days.map((day) => {
                  const slot = new Date(day)
                  slot.setHours(hour, minute, 0, 0)
                  const t = slot.getTime()
                  const isLocked = lockedSet.has(t)
                  const isSelected = selectedSet.has(t)
                  const isPast = slot < cutoff
                  const isDisabled = isLocked || isPast || (atMax && !isSelected)
                  return (
                    <div
                      key={t}
                      data-t={isDisabled && !isSelected ? undefined : t}
                      onPointerDown={(e) => {
                        if (isDisabled && !isSelected) return
                        e.preventDefault()
                        handlePointerDown(t, isSelected)
                      }}
                      className={cn(
                        "h-5 border border-border/40 transition-colors touch-none",
                        isHourBoundary && "border-t-border/80",
                        isLocked
                          ? "bg-muted-foreground/30"
                          : isSelected
                            ? "bg-primary border-primary-foreground/30"
                            : isPast
                              ? "bg-muted"
                              : isDisabled
                                ? "bg-muted"
                                : "bg-background hover:bg-accent cursor-pointer"
                      )}
                    />
                  )
                })}
                <div />
              </Fragment>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export { TimeSlotPicker }
export type { TimeSlotPickerProps }
