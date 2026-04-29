"use client"

import { useState, useEffect, useRef } from "react"
import { Progress } from "@/components/ui/progress"
import { cn } from "@/lib/utils"

interface Stage {
  at: number
  message: string
}

interface ProgressProfile {
  estimatedMs: number
  stages: Stage[]
}

const PROFILES: Record<string, ProgressProfile> = {
  "resume-init": {
    estimatedMs: 20000,
    stages: [
      { at: 0, message: "Reading document..." },
      { at: 15, message: "Analyzing structure..." },
      { at: 35, message: "Extracting information..." },
      { at: 55, message: "Processing details..." },
      { at: 75, message: "Reviewing quality..." },
      { at: 90, message: "Finalizing..." },
    ],
  },
  "resume-generate": {
    estimatedMs: 40000,
    stages: [
      { at: 0, message: "Building strategy..." },
      { at: 40, message: "Selecting content and framing narrative..." },
      { at: 60, message: "Writing resume..." },
      { at: 85, message: "Polishing bullets..." },
      { at: 95, message: "Finalizing..." },
    ],
  },
  "sales-lead": {
    estimatedMs: 12000,
    stages: [
      { at: 0, message: "Analyzing resume..." },
      { at: 25, message: "Generating insights..." },
      { at: 50, message: "Identifying skills..." },
      { at: 70, message: "Assessing risks..." },
      { at: 85, message: "Creating lead..." },
      { at: 95, message: "Finalizing..." },
    ],
  },
  "sales-parse": {
    estimatedMs: 15000,
    stages: [
      { at: 0, message: "Reading document..." },
      { at: 20, message: "Extracting text..." },
      { at: 40, message: "Analyzing structure..." },
      { at: 60, message: "Parsing details..." },
      { at: 80, message: "Validating data..." },
      { at: 92, message: "Finalizing..." },
    ],
  },
  "sales-plan": {
    estimatedMs: 25000,
    stages: [
      { at: 0, message: "Analyzing profile..." },
      { at: 15, message: "Evaluating background..." },
      { at: 30, message: "Identifying opportunities..." },
      { at: 45, message: "Building strategy..." },
      { at: 60, message: "Generating recommendations..." },
      { at: 75, message: "Creating action plan..." },
      { at: 90, message: "Finalizing..." },
    ],
  },
  "network-parse": {
    estimatedMs: 10000,
    stages: [
      { at: 0, message: "Reading text..." },
      { at: 20, message: "Identifying profile sections..." },
      { at: 45, message: "Extracting details..." },
      { at: 70, message: "Structuring data..." },
      { at: 90, message: "Finalizing..." },
    ],
  },
  "network-import": {
    estimatedMs: 90000,
    stages: [
      { at: 0, message: "Uploading file..." },
      { at: 8, message: "Parsing spreadsheet..." },
      { at: 15, message: "Validating data..." },
      { at: 25, message: "Analyzing contacts..." },
      { at: 45, message: "Processing rows..." },
      { at: 65, message: "Saving to database..." },
      { at: 85, message: "Finalizing..." },
    ],
  },
}

function getMessage(stages: Stage[], progress: number): string {
  for (let i = stages.length - 1; i >= 0; i--) {
    if (progress >= stages[i].at) return stages[i].message
  }
  return stages[0]?.message ?? "Processing..."
}

interface ProgressIndicatorProps {
  profile: keyof typeof PROFILES | ProgressProfile
  isActive: boolean
  isComplete: boolean
  onComplete?: () => void
  completeMessage?: string
  extraTimeMs?: number
  showEstimate?: boolean
  startedAt?: number
  className?: string
}

interface StageTiming {
  start: number
  end: number
  jumpAt: number | null
}

function generateStageTiming(stages: Stage[], totalMs: number): StageTiming[] {
  const stageCount = stages.length
  const baseInterval = totalMs / stageCount

  const rawTimings: number[] = [0]
  let cumulative = 0

  for (let i = 1; i < stageCount; i++) {
    const variance = 0.5 + Math.random() * 1.0
    cumulative += baseInterval * variance
    rawTimings.push(cumulative)
  }

  const scale = (totalMs * 0.95) / cumulative
  const scaledTimings = rawTimings.map(t => t * scale)

  const timings: StageTiming[] = []
  for (let i = 0; i < stageCount; i++) {
    const start = scaledTimings[i]
    const end = scaledTimings[i + 1] ?? totalMs * 0.95
    const hasJump = Math.random() < 0.4
    const jumpAt = hasJump ? start + (end - start) * (0.3 + Math.random() * 0.4) : null
    timings.push({ start, end, jumpAt })
  }

  return timings
}

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
}

function formatRemaining(ms: number): string {
  const seconds = Math.ceil(ms / 1000)
  if (seconds <= 0) return ""
  if (seconds < 60) return `~${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const secs = seconds % 60
  return secs > 0 ? `~${minutes}m ${secs}s` : `~${minutes}m`
}

function formatElapsed(ms: number): string {
  const seconds = Math.ceil(ms / 1000)
  if (seconds <= 0) return "0s"
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const secs = seconds % 60
  return secs > 0 ? `${minutes}m ${secs}s` : `${minutes}m`
}

export function ProgressIndicator({
  profile,
  isActive,
  isComplete,
  onComplete,
  completeMessage = "Complete",
  extraTimeMs = 0,
  showEstimate = false,
  startedAt,
  className,
}: ProgressIndicatorProps) {
  const [animatedProgress, setAnimatedProgress] = useState(0)
  const startTimeRef = useRef<number | null>(null)
  const animationRef = useRef<number | null>(null)
  const stageTimingsRef = useRef<StageTiming[] | null>(null)
  const lastUpdateRef = useRef<number>(0)
  const baseConfig = typeof profile === "string" ? PROFILES[profile] : profile
  const config = { ...baseConfig, estimatedMs: baseConfig.estimatedMs + extraTimeMs }

  useEffect(() => {
    if (!isActive || isComplete) {
      startTimeRef.current = null
      stageTimingsRef.current = null
      lastUpdateRef.current = 0
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
        animationRef.current = null
      }
      return
    }

    if (!startTimeRef.current) {
      startTimeRef.current = startedAt ?? Date.now()
      stageTimingsRef.current = generateStageTiming(config.stages, config.estimatedMs)
    }

    const animate = () => {
      const now = Date.now()
      const elapsed = now - (startTimeRef.current ?? now)
      const timings = stageTimingsRef.current ?? []

      let currentStage = 0
      for (let i = 0; i < timings.length; i++) {
        if (elapsed >= timings[i].start) currentStage = i
      }

      const timing = timings[currentStage]
      const currentAt = config.stages[currentStage]?.at ?? 0
      const nextAt = config.stages[currentStage + 1]?.at ?? 95

      let smoothProgress: number
      if (elapsed >= config.estimatedMs) {
        const overtimeMs = elapsed - config.estimatedMs
        // After estimate is exceeded, creep toward 99% so UI doesn't appear stuck.
        smoothProgress = 95 + 4 * (1 - Math.exp(-overtimeMs / 15000))
      } else if (timing.jumpAt && elapsed >= timing.jumpAt) {
        smoothProgress = nextAt
      } else {
        const effectiveEnd = timing.jumpAt ?? timing.end
        const stageElapsed = elapsed - timing.start
        const stageDuration = effectiveEnd - timing.start
        const t = Math.min(stageElapsed / stageDuration, 1)
        const eased = easeInOutCubic(t)
        smoothProgress = currentAt + (nextAt - currentAt) * eased
      }

      if (now - lastUpdateRef.current >= 50) {
        lastUpdateRef.current = now
        setAnimatedProgress(Math.min(99, smoothProgress))
      }

      if (!isComplete) {
        animationRef.current = requestAnimationFrame(animate)
      }
    }

    animationRef.current = requestAnimationFrame(animate)
    return () => {
      if (animationRef.current) cancelAnimationFrame(animationRef.current)
    }
  }, [isActive, isComplete, config.estimatedMs, config.stages, extraTimeMs])

  const progress = !isActive ? 0 : isComplete ? 100 : animatedProgress

  useEffect(() => {
    if (progress >= 100 && onComplete) {
      const timer = setTimeout(onComplete, 500)
      return () => clearTimeout(timer)
    }
  }, [progress, onComplete])

  if (!isActive) return null

  const message = isComplete ? completeMessage : getMessage(config.stages, progress)
  const elapsed = startTimeRef.current ? Date.now() - startTimeRef.current : 0
  const remaining = (() => {
    if (!showEstimate || isComplete) return ""
    if (elapsed <= config.estimatedMs) return formatRemaining(config.estimatedMs - elapsed)
    return `+${formatElapsed(elapsed - config.estimatedMs)}`
  })()

  return (
    <div className={cn("space-y-2", className)}>
      <Progress
        value={progress}
        className={cn(
          "h-2 transition-colors duration-300",
          isComplete && "[&>[data-slot=progress-indicator]]:bg-success-fg"
        )}
      />
      <div
        className={cn(
          "flex items-center text-xs text-muted-foreground transition-opacity duration-500",
          !isComplete && "animate-pulse",
          remaining ? "justify-between" : "justify-center"
        )}
      >
        <span>{message}</span>
        {remaining && <span>{remaining}</span>}
      </div>
    </div>
  )
}

export { PROFILES, type ProgressProfile }
