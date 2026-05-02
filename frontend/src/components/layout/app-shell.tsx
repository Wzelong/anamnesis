"use client"

import { useEffect, useRef } from "react"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"
import { useAppStore } from "@/lib/store"
import { Header } from "./header"
import { RunListPanel } from "./run-list-panel"

export function AppShell({ children }: { children: React.ReactNode }) {
  const runs = useAppStore((s) => s.runs)
  const runsHydrated = useAppStore((s) => s.runsHydrated)
  const fetchRuns = useAppStore((s) => s.fetchRuns)
  const pathname = usePathname()

  useEffect(() => {
    fetchRuns()
  }, [fetchRuns])

  const lastRouteKind = useRef<"home" | "detail" | null>(null)
  const kind = pathname === "/" ? "home" : "detail"
  useEffect(() => {
    if (lastRouteKind.current !== kind) {
      lastRouteKind.current = kind
      useAppStore.setState({ runPanelOverride: null })
    }
  }, [kind])

  const isEmpty = runsHydrated && runs.length === 0
  const isHome = pathname === "/"

  if (!runsHydrated) return null

  if (isEmpty && isHome) {
    return <>{children}</>
  }

  return (
    <>
      <Header />
      <div className="flex h-dvh pt-12">
        <RunListPanel />
        <main className={cn("flex-1 min-w-0 flex flex-col", isHome && "hidden lg:flex")}>
          {children}
        </main>
      </div>
    </>
  )
}
