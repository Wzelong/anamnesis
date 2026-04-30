"use client"

import { use, useEffect } from "react"
import { useSearchParams } from "next/navigation"
import { useAppStore } from "@/lib/store"

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
    <div className="flex-1 flex items-center justify-center">
      <p className="text-sm text-muted-foreground">Detail view coming next</p>
    </div>
  )
}
