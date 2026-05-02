"use client"

import { use, useEffect } from "react"
import { useSearchParams } from "next/navigation"
import { useAppStore } from "@/lib/store"
import { ProposalListPanel } from "@/components/layout/proposal-list-panel"
import { ProposalDetailPanel } from "@/components/layout/proposal-detail-panel"

export default function RunPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = use(params)
  const searchParams = useSearchParams()
  const fetchProposals = useAppStore((s) => s.fetchProposals)
  const setToken = useAppStore((s) => s.setToken)

  useEffect(() => {
    const token = searchParams.get("token")
    if (token) setToken(token)
    fetchProposals(runId)
  }, [runId, fetchProposals, searchParams, setToken])

  return (
    <div className="flex-1 flex min-w-0 h-full min-h-0 border-b">
      <ProposalListPanel />
      <ProposalDetailPanel />
      <div className="flex-1 min-w-0" />
    </div>
  )
}
