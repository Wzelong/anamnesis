"use client"

import { use, useEffect } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { useAppStore } from "@/lib/store"
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
    const token = searchParams.get("token")
    if (token) setToken(token)
    fetchProposals(runId)
  }, [runId, fetchProposals, searchParams, setToken])

  useEffect(() => {
    if (runsLoading) return
    if (!runs.some((r) => r.id === runId)) router.replace("/")
  }, [runId, runs, runsLoading, router])

  return (
    <div className="flex-1 flex min-w-0 h-full min-h-0 border-b">
      <ProposalListPanel />
      <ProposalDetailPanel />
      <RightPanel runId={runId} />
      {children}
    </div>
  )
}
