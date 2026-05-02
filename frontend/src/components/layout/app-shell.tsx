"use client"

import { useEffect, useRef } from "react"
import { usePathname } from "next/navigation"
import { useAppStore } from "@/lib/store"
import { Header } from "./header"
import { RunListPanel } from "./run-list-panel"

export function AppShell({ children }: { children: React.ReactNode }) {
  const runs = useAppStore((s) => s.runs)
  const runsLoading = useAppStore((s) => s.runsLoading)
  const fetchRuns = useAppStore((s) => s.fetchRuns)
  const pathname = usePathname()

  useEffect(() => {
    fetchRuns()
  }, [fetchRuns])

  const lastRouteKind = useRef<"home" | "detail" | null>(null)
  const kind = pathname === "/" ? "home" : "detail"
  if (lastRouteKind.current !== kind) {
    lastRouteKind.current = kind
    useAppStore.setState({ runPanelOverride: null })
  }

  const isEmpty = !runsLoading && runs.length === 0
  const isHome = pathname === "/"

  if (isEmpty && isHome) {
    return <>{children}</>
  }

  return (
    <>
      <Header />
      <div className="flex h-dvh pt-12">
        <RunListPanel />
        <main className="flex-1 min-w-0 flex flex-col">
          {children}
        </main>
      </div>
    </>
  )
}
