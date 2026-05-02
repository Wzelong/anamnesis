"use client"

import { use, useEffect } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Inbox } from "lucide-react"
import { readPersistedToken, useAppStore } from "@/lib/store"
import { ProposalListPanel } from "@/components/layout/proposal-list-panel"
import { ProposalDetailPanel } from "@/components/layout/proposal-detail-panel"
import { RightPanel } from "@/components/layout/right-panel"

export default function RunLayout({
  children,
  params,
}: {
  children: React.ReactNode
  params: Promise<{ runId: string }>
}) {
  const { runId } = use(params)
  const router = useRouter()
  const searchParams = useSearchParams()
  const fetchProposals = useAppStore((s) => s.fetchProposals)
  const setToken = useAppStore((s) => s.setToken)
  const runs = useAppStore((s) => s.runs)
  const runsLoading = useAppStore((s) => s.runsLoading)

  useEffect(() => {
    const urlToken = searchParams.get("token")
    if (urlToken) {
      setToken(urlToken)
    } else if (!useAppStore.getState().token) {
      const stored = readPersistedToken()
      setToken(stored)
    }
    fetchProposals(runId)
  }, [runId, fetchProposals, searchParams, setToken])

  useEffect(() => {
    if (runsLoading) return
    if (!runs.some((r) => r.id === runId)) router.replace("/")
  }, [runId, runs, runsLoading, router])

  const selectedId = useAppStore((s) => s.selectedId)

  return (
    <div className="flex-1 flex min-w-0 h-full min-h-0 border-b">
      <ProposalListPanel />
      {selectedId ? (
        <>
          <ProposalDetailPanel />
          <RightPanel runId={runId} />
        </>
      ) : (
        <div className="flex-1 min-w-0 hidden lg:flex flex-col items-center justify-center text-muted-foreground gap-2">
          <Inbox className="size-8" />
          <div className="text-sm">Select a proposal to review</div>
        </div>
      )}
      {children}
    </div>
  )
}
