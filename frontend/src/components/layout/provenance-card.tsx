"use client"

import { useState } from "react"
import { Code, NotepadText } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { JsonEditor } from "@/components/ui/json-editor"

interface Props {
  resource: Record<string, unknown>
}

interface AgentEntry {
  type?: { coding?: Array<{ code?: string }> }
  who?: { display?: string; reference?: string }
}

interface EntityEntry {
  what?: { reference?: string }
}

interface SpanExtension {
  url?: string
  extension?: Array<{ url?: string; valueString?: string; valueInteger?: number }>
}

function formatRecorded(iso: string | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  })
}

function agentRoleLabel(a: AgentEntry): string {
  return a.type?.coding?.[0]?.code ?? "agent"
}

function ProvenanceForm({ resource }: { resource: Record<string, unknown> }) {
  const recorded = formatRecorded(resource.recorded as string | undefined)
  const activity = (resource.activity as { coding?: Array<{ code?: string }> } | undefined)?.coding?.[0]?.code ?? "—"
  const target = (resource.target as Array<{ reference?: string }> | undefined)?.[0]?.reference ?? "—"
  const agents = (resource.agent as AgentEntry[] | undefined) ?? []
  const entities = (resource.entity as EntityEntry[] | undefined) ?? []
  const extensions = (resource.extension as SpanExtension[] | undefined) ?? []

  return (
    <div className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-sm">
      <div className="text-muted-foreground">Recorded</div>
      <div className="tabular-nums">{recorded}</div>

      <div className="text-muted-foreground">Activity</div>
      <div>{activity}</div>

      <div className="text-muted-foreground">Target</div>
      <div className="font-mono text-xs break-all">{target}</div>

      {agents.length > 0 && (
        <>
          <div className="text-muted-foreground">Agents</div>
          <div className="flex flex-col gap-0.5">
            {agents.map((a, i) => (
              <div key={i} className="flex items-baseline gap-2">
                <span className="text-xs text-muted-foreground w-16 shrink-0">{agentRoleLabel(a)}</span>
                <span>{a.who?.display ?? a.who?.reference ?? "—"}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {entities.length > 0 && (
        <>
          <div className="text-muted-foreground">Sources</div>
          <div className="flex flex-col gap-0.5">
            {entities.map((e, i) => (
              <div key={i} className="font-mono text-xs break-all">{e.what?.reference ?? "—"}</div>
            ))}
          </div>
        </>
      )}

      {extensions.length > 0 && (
        <>
          <div className="text-muted-foreground">Spans</div>
          <div className="flex flex-col gap-1">
            {extensions.map((ext, i) => {
              const fields = Object.fromEntries(
                (ext.extension ?? []).map((x) => [x.url, x.valueString ?? x.valueInteger]),
              )
              return (
                <div key={i} className="text-xs">
                  <span className="text-muted-foreground">[{fields.start}–{fields.end}]</span>{" "}
                  <span className="italic">&ldquo;{String(fields.text ?? "").trim()}&rdquo;</span>
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}

export function ProvenanceCard({ resource }: Props) {
  const [tab, setTab] = useState<"form" | "json">("form")
  const json = JSON.stringify(resource, null, 2)

  return (
    <div className="max-w-2xl rounded-lg border">
      <div className="h-9 px-3 flex items-center gap-2 border-b">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Provenance</span>
        <div className="flex-1" />
        <div className="flex items-center gap-1 shrink-0">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className={cn("h-7 w-7 cursor-pointer text-muted-foreground", tab === "form" && "bg-muted")}
                onClick={() => setTab("form")}
                aria-label="Form view"
              >
                <NotepadText className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="top"><p>Form</p></TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className={cn("h-7 w-7 cursor-pointer text-muted-foreground", tab === "json" && "bg-muted")}
                onClick={() => setTab("json")}
                aria-label="JSON view"
              >
                <Code className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="top"><p>JSON</p></TooltipContent>
          </Tooltip>
        </div>
      </div>
      {tab === "form" ? (
        <div className="p-3">
          <ProvenanceForm resource={resource} />
        </div>
      ) : (
        <JsonEditor value={json} hideTypeLabel />
      )}
    </div>
  )
}
