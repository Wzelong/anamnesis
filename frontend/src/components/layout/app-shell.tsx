"use client"

import { useEffect } from "react"
import { usePathname, useRouter } from "next/navigation"
import { useAppStore } from "@/lib/store"
import { Header } from "./header"
import { RunListPanel } from "./run-list-panel"

export function AppShell({ children }: { children: React.ReactNode }) {
  const runs = useAppStore((s) => s.runs)
  const runsLoading = useAppStore((s) => s.runsLoading)
  const fetchRuns = useAppStore((s) => s.fetchRuns)
  const runId = useAppStore((s) => s.runId)
  const pathname = usePathname()

  useEffect(() => {
    fetchRuns()
  }, [fetchRuns])

  const isEmpty = !runsLoading && runs.length === 0
  const isHome = pathname === "/"

  if (runsLoading && runs.length === 0) {
    return <div className="min-h-dvh" />
  }

  if (isEmpty && isHome) {
    return <>{children}</>
  }

  return (
    <>
      <Header />
      <div className="flex h-[calc(100dvh-48px)] pt-12">
        <RunListPanel />
        <main className="flex-1 min-w-0 flex flex-col">
          {children}
        </main>
      </div>
    </>
  )
}
