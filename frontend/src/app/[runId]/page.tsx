"use client"

import { useEffect } from "react"
import { useAppStore } from "@/lib/store"

export default function RunIndexPage() {
  const setSelectedId = useAppStore((s) => s.setSelectedId)
  useEffect(() => {
    setSelectedId(null)
  }, [setSelectedId])
  return null
}
