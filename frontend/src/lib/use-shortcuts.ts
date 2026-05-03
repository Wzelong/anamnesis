"use client"

import { useEffect, useRef } from "react"

type Handler = (e: KeyboardEvent) => void
type ShortcutMap = Record<string, Handler>

export function useShortcuts(map: ShortcutMap, enabled = true) {
  const mapRef = useRef(map)
  useEffect(() => {
    mapRef.current = map
  })

  useEffect(() => {
    if (!enabled) return
    const handler = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const target = e.target as HTMLElement | null
      if (target) {
        const tag = target.tagName
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return
        if (target.isContentEditable) return
      }
      const fn = mapRef.current[e.key]
      if (!fn) return
      e.preventDefault()
      fn(e)
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [enabled])
}
