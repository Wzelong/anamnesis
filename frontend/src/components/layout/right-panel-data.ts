"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { api } from "@/lib/api"
import type { ChartContext, SourceDocument } from "@/lib/types"

const docCache = new Map<string, Promise<SourceDocument[]>>()
const chartCache = new Map<string, Promise<ChartContext>>()
const chartListeners = new Map<string, Set<(c: ChartContext) => void>>()

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

function notifyChart(runId: string, chart: ChartContext) {
  const set = chartListeners.get(runId)
  if (!set) return
  for (const cb of set) cb(chart)
}

export async function refreshChart(runId: string): Promise<ChartContext> {
  const next = await (api.refreshChart(runId) as Promise<ChartContext>)
  chartCache.set(runId, Promise.resolve(next))
  notifyChart(runId, next)
  return next
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
  const setChartRef = useRef(setChart)
  setChartRef.current = setChart

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    loadChart(runId)
      .then((d) => { if (!cancelled) setChart(d) })
      .catch(() => { if (!cancelled) setChart(null) })
    return () => { cancelled = true }
  }, [runId, enabled])

  useEffect(() => {
    const cb = (c: ChartContext) => setChartRef.current(c)
    let set = chartListeners.get(runId)
    if (!set) { set = new Set(); chartListeners.set(runId, set) }
    set.add(cb)
    return () => {
      set!.delete(cb)
      if (set!.size === 0) chartListeners.delete(runId)
    }
  }, [runId])

  return chart
}

export function useChartRefresh(runId: string) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const refresh = useCallback(async () => {
    setPending(true)
    setError(null)
    try {
      await refreshChart(runId)
    } catch (e) {
      setError(e instanceof Error ? e.message : "refresh failed")
    } finally {
      setPending(false)
    }
  }, [runId])
  return { refresh, pending, error }
}
