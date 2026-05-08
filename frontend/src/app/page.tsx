"use client"

import { useState } from "react"
import Image from "next/image"
import { ArrowRight, Check, Copy, ClipboardList, Database } from "lucide-react"
import { Button } from "@/components/ui/button"
import { toast } from "sonner"
import { useRouter } from "next/navigation"
import { api } from "@/lib/api"
import { useAppStore } from "@/lib/store"
import {
  Empty,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  EmptyDescription,
} from "@/components/ui/empty"

const MCP_URL = process.env.NEXT_PUBLIC_MCP_URL ?? "https://anamnesis-demo.fly.dev/mcp"

function GettingStarted() {
  const [copied, setCopied] = useState(false)
  const [seeding, setSeeding] = useState(false)
  const fetchRuns = useAppStore((s) => s.fetchRuns)
  const router = useRouter()

  const handleCopy = async () => {
    await navigator.clipboard.writeText(MCP_URL)
    setCopied(true)
    toast.success("Copied to clipboard")
    setTimeout(() => setCopied(false), 2000)
  }

  const handleSeedDemo = async () => {
    setSeeding(true)
    try {
      const { run_id } = await api.seedDemo()
      await fetchRuns()
      router.push(`/${run_id}`)
      toast.success("Demo data loaded.")
    } catch {
      toast.error("Failed to load demo data.")
    } finally {
      setSeeding(false)
    }
  }

  return (
    <div className="min-h-dvh flex flex-col items-center justify-center px-4">
      <div className="w-full max-w-[440px] space-y-10">
        <div className="flex flex-col items-center space-y-3">
          <Image
            src="/logo.png"
            alt="Anamnesis"
            width={64}
            height={64}
            className="size-16"
          />
          <div className="text-center space-y-1.5">
            <h1 className="text-2xl font-semibold tracking-tight">
              Anamnesis
            </h1>
            <p className="text-sm text-muted-foreground leading-relaxed">
              AI-assisted chart review for clinicians.
              <br />
              Extract, reconcile, and write FHIR augmentations from clinical notes.
            </p>
          </div>
        </div>

        <div className="space-y-4">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Getting started
          </p>

          <div className="space-y-3.5">
            <div className="flex gap-3">
              <span className="flex size-5 shrink-0 items-center justify-center rounded-full border text-[11px] font-medium text-muted-foreground mt-0.5">
                1
              </span>
              <div className="space-y-2 flex-1 min-w-0">
                <p className="text-sm">Add the MCP server in Prompt Opinion</p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 min-w-0 truncate rounded bg-muted px-2.5 py-1.5 text-xs font-mono text-muted-foreground">
                    {MCP_URL}
                  </code>
                  <Button
                    variant="outline"
                    size="icon"
                    className="size-7 shrink-0"
                    onClick={handleCopy}
                  >
                    {copied
                      ? <Check className="size-3 text-green-500" />
                      : <Copy className="size-3" />}
                  </Button>
                </div>
              </div>
            </div>

            <div className="flex gap-3">
              <span className="flex size-5 shrink-0 items-center justify-center rounded-full border text-[11px] font-medium text-muted-foreground mt-0.5">
                2
              </span>
              <p className="text-sm">Open a patient in Prompt Opinion</p>
            </div>

            <div className="flex gap-3">
              <span className="flex size-5 shrink-0 items-center justify-center rounded-full border text-[11px] font-medium text-muted-foreground mt-0.5">
                3
              </span>
              <div className="space-y-1">
                <p className="text-sm">Ask the agent to review the chart</p>
                <p className="text-xs text-muted-foreground">
                  The agent returns a link to this workspace.
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-col items-center gap-4">
          <a
            href="https://app.promptopinion.ai"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            <span>Open Prompt Opinion</span>
            <ArrowRight className="size-3.5 translate-y-px" />
          </a>

          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span className="h-px w-8 bg-border" />
            <span>or</span>
            <span className="h-px w-8 bg-border" />
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={handleSeedDemo}
            disabled={seeding}
            className="gap-1.5"
          >
            <Database className="size-3.5" />
            {seeding ? "Loading demo data..." : "Load demo data"}
          </Button>
        </div>
      </div>
    </div>
  )
}

function SelectARun() {
  return (
    <Empty className="flex-1 border-0">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <ClipboardList />
        </EmptyMedia>
        <EmptyTitle>Select a run</EmptyTitle>
        <EmptyDescription>
          Choose a pipeline run from the list to view its proposals.
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  )
}

export default function Home() {
  const runs = useAppStore((s) => s.runs)
  const hasRuns = runs.length > 0

  return hasRuns ? <SelectARun /> : <GettingStarted />
}
