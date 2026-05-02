"use client"

import { use, useEffect } from "react"
import { useRouter } from "next/navigation"
import { useAppStore } from "@/lib/store"

export default function ProposalPage({
  params,
}: {
  params: Promise<{ runId: string; proposalId: string }>
}) {
  const { runId, proposalId } = use(params)
  const router = useRouter()
  const setSelectedId = useAppStore((s) => s.setSelectedId)
  const proposals = useAppStore((s) => s.proposals)
  const loading = useAppStore((s) => s.loading)
  const storeRunId = useAppStore((s) => s.runId)

  useEffect(() => {
    setSelectedId(proposalId)
  }, [proposalId, setSelectedId])

  useEffect(() => {
    if (loading || storeRunId !== runId) return
    if (!proposals.some((p) => p.id === proposalId)) {
      router.replace(`/${runId}`)
    }
  }, [proposalId, runId, proposals, loading, storeRunId, router])

  return null
}
