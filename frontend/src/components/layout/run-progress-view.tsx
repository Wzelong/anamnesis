"use client"

import { useEffect, useState, useRef } from "react"
import Image from "next/image"
import { Check, Circle, Loader2 } from "lucide-react"
import { Progress } from "@/components/ui/progress"
import { api } from "@/lib/api"
import { useAppStore } from "@/lib/store"

const STAGES = [
  { key: "guardrail", label: "Document guardrail", format: (d: Record<string, unknown>) => `${d.documents_accepted} documents accepted` },
  { key: "stage1_preprocess", label: "Preprocessing", format: (d: Record<string, unknown>) => `${d.sentences} sentences` },
  { key: "stage2_extract", label: "Extracting candidates", format: (d: Record<string, unknown>) => `${d.candidates} candidates` },
  { key: "stage3_merge", label: "Deduplicating", format: (d: Record<string, unknown>) => `${d.candidates} merged` },
  { key: "stage4_code", label: "Coding terminology", format: (d: Record<string, unknown>) => `${d.coded} coded` },
  { key: "stage5_reconcile", label: "Reconciling with chart", format: (d: Record<string, unknown>) => {
    const parts = Object.entries(d).filter(([, v]) => typeof v === "number" && v > 0).map(([k, v]) => `${v} ${k}`)
    return parts.join(", ") || "done"
  }},
  { key: "stage6_assemble", label: "Assembling proposals", format: (d: Record<string, unknown>) => `${d.proposals} proposals` },
]

function elapsed(startedAt: string | null): string {
  if (!startedAt) return ""
  const ms = Date.now() - new Date(startedAt).getTime()
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${s % 60}s`
}

interface Props {
  runId: string
  patientName?: string | null
}

export function RunProgressView({ runId, patientName }: Props) {
  const [progress, setProgress] = useState<{
    current_stage: string
    stages_completed: Array<{ name: string; [key: string]: unknown }>
  } | null>(null)
  const [startedAt, setStartedAt] = useState<string | null>(null)
  const [status, setStatus] = useState<string>("running")
  const [error, setError] = useState<string | null>(null)
  const [, setTick] = useState(0)
  const fetchRuns = useAppStore((s) => s.fetchRuns)
  const fetchProposals = useAppStore((s) => s.fetchProposals)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const failCountRef = useRef(0)

  const stop = () => {
    if (pollRef.current) clearInterval(pollRef.current)
    if (tickRef.current) clearInterval(tickRef.current)
  }

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      if (startedAt) {
        const elapsed = Date.now() - new Date(startedAt).getTime()
        if (elapsed > 5 * 60 * 1000) {
          stop()
          setStatus("failed")
          setError("Pipeline timed out after 5 minutes.")
          fetchRuns()
          return
        }
      }
      try {
        const data = await api.getRunProgress(runId)
        if (cancelled) return
        failCountRef.current = 0
        setProgress(data.progress)
        setStartedAt(data.started_at)
        setStatus(data.status)
        setError(data.error)
        if (data.status !== "running") {
          stop()
          fetchRuns()
          fetchProposals(runId)
        }
      } catch {
        failCountRef.current += 1
        if (failCountRef.current >= 5) {
          stop()
          setStatus("failed")
          setError("Lost connection to backend.")
          fetchRuns()
        }
      }
    }
    poll()
    pollRef.current = setInterval(poll, 2000)
    tickRef.current = setInterval(() => setTick((t) => t + 1), 1000)
    return () => {
      cancelled = true
      stop()
    }
  }, [runId, fetchRuns, fetchProposals, startedAt])

  const completedKeys = new Set(
    (progress?.stages_completed ?? []).map((s) => s.name)
  )
  const completedMap = Object.fromEntries(
    (progress?.stages_completed ?? []).map((s) => [s.name, s])
  )
  const currentStage = progress?.current_stage
  const completedCount = completedKeys.size
  const pct = Math.round((completedCount / STAGES.length) * 100)

  if (status === "failed") {
    return (
      <div className="flex-1 flex items-center justify-center px-4">
        <div className="w-full max-w-sm space-y-4 text-center">
          <p className="text-sm font-medium text-destructive">Pipeline failed</p>
          {error && <p className="text-xs text-muted-foreground">{error}</p>}
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex items-center justify-center px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center space-y-1.5">
          <Image src="/logo.png" alt="Anamnesis" width={48} height={48} className="size-12 mx-auto animate-pulse" />
          <p className="text-sm font-medium">
            Augmenting {patientName ? `${patientName}'s` : ""} chart
          </p>
          <p className="text-xs text-muted-foreground">
            Stage {completedCount} of {STAGES.length}
            {startedAt ? ` · ${elapsed(startedAt)}` : ""}
          </p>
        </div>

        <Progress value={pct} className="h-1.5" />

        <div className="space-y-2">
          {STAGES.map((stage) => {
            const done = completedKeys.has(stage.key)
            const active = currentStage === stage.key && !done
            const detail = completedMap[stage.key]
            return (
              <div key={stage.key} className="flex items-start gap-2.5 text-xs">
                {done ? (
                  <Check className="size-3.5 text-green-500 mt-0.5 shrink-0" />
                ) : active ? (
                  <Loader2 className="size-3.5 animate-spin text-foreground mt-0.5 shrink-0" />
                ) : (
                  <Circle className="size-3.5 text-muted-foreground/40 mt-0.5 shrink-0" />
                )}
                <div className="min-w-0">
                  <span className={done || active ? "text-foreground" : "text-muted-foreground/60"}>
                    {stage.label}
                  </span>
                  {done && detail && (
                    <span className="text-muted-foreground ml-1.5">
                      — {stage.format(detail)}
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
