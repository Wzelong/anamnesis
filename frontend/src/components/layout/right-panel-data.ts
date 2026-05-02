"use client"

import { useEffect, useState } from "react"
import { api } from "@/lib/api"
import type { ChartContext, SourceDocument } from "@/lib/types"

const docCache = new Map<string, Promise<SourceDocument[]>>()
const chartCache = new Map<string, Promise<ChartContext>>()

export function loadDocuments(runId: string): Promise<SourceDocument[]> {
  let p = docCache.get(runId)
  if (!p) {
    p = api.getDocuments(runId).then((data) => (data as { documents: SourceDocument[] }).documents)
    docCache.set(runId, p)
  }
  return p
}

export function loadChart(runId: string): Promise<ChartContext> {
  let p = chartCache.get(runId)
  if (!p) {
    p = api.getChart(runId).then((data) => data as ChartContext)
    chartCache.set(runId, p)
  }
  return p
}

export function useDocuments(runId: string) {
  const [documents, setDocuments] = useState<SourceDocument[] | null>(null)
  useEffect(() => {
    let cancelled = false
    loadDocuments(runId)
      .then((d) => { if (!cancelled) setDocuments(d) })
      .catch(() => { if (!cancelled) setDocuments([]) })
    return () => { cancelled = true }
  }, [runId])
  return documents
}

export function useChart(runId: string, enabled: boolean) {
  const [chart, setChart] = useState<ChartContext | null>(null)
  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    loadChart(runId)
      .then((d) => { if (!cancelled) setChart(d) })
      .catch(() => { if (!cancelled) setChart(null) })
    return () => { cancelled = true }
  }, [runId, enabled])
  return chart
}
