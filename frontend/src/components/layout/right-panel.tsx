"use client"

import { useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { ArrowLeft, Check, ChevronDown, DatabaseSearch, FileSliders, FileText, Inbox, MessageCircleQuestionMark } from "lucide-react"
import { cn } from "@/lib/utils"
import { useAppStore } from "@/lib/store"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { shortDate } from "@/lib/fhir-summary"
import { formatTimeAgo } from "@/lib/time"
import type { ResolvedCitation, SourceDocument } from "@/lib/types"
import { RightPanelNotes } from "./right-panel-notes"
import { RightPanelChart } from "./right-panel-chart"
import { RightPanelChat } from "./right-panel-chat"
import { useChart, useDocuments } from "./right-panel-data"

type Tab = "notes" | "chart" | "chat"

interface Props {
  runId: string
}

const TABS: Array<{ value: Tab; label: string; icon: React.ReactNode }> = [
  { value: "notes", label: "Notes", icon: <FileText className="size-3.5" /> },
  { value: "chart", label: "FHIR store", icon: <DatabaseSearch className="size-3.5" /> },
  { value: "chat", label: "AI chat", icon: <MessageCircleQuestionMark className="size-3.5" /> },
]

const NAV_TABS: Array<{ value: "detail" | "notes" | "chart" | "chat"; label: string; icon: React.ReactNode }> = [
  { value: "detail", label: "Detail", icon: <FileSliders className="size-3.5" /> },
  { value: "notes", label: "Notes", icon: <FileText className="size-3.5" /> },
  { value: "chart", label: "FHIR store", icon: <DatabaseSearch className="size-3.5" /> },
  { value: "chat", label: "AI chat", icon: <MessageCircleQuestionMark className="size-3.5" /> },
]

export function RightPanel({ runId }: Props) {
  const router = useRouter()
  const tab = useAppStore((s) => s.rightTab)
  const setTab = useAppStore((s) => s.setRightTab)
  const contentView = useAppStore((s) => s.contentView)
  const setContentView = useAppStore((s) => s.setContentView)
  const [activeDocId, setActiveDocId] = useState<string | null>(null)
  const selectedId = useAppStore((s) => s.selectedId)
  const detail = useAppStore((s) => s.selectedDetail)

  const handleNavTab = (v: typeof NAV_TABS[number]["value"]) => {
    if (v === "detail") setContentView("detail")
    else { setContentView("right"); setTab(v) }
  }

  const documents = useDocuments(runId)
  const chart = useChart(runId, tab === "chart")

  const activeDoc = useMemo(
    () => documents?.find((d) => d.id === activeDocId) ?? null,
    [documents, activeDocId],
  )

  return (
    <section
      className={cn(
        "flex-1 min-w-0 flex-col h-full min-h-0",
        contentView === "right" ? "flex" : "hidden xl:flex",
      )}
    >
      {/* Below xl: navigation header (back + title + nav tabs) */}
      <div className="h-11 shrink-0 border-b px-3 flex items-center gap-2 min-w-0 xl:hidden">
        <ArrowLeft
          className="size-3.5 text-muted-foreground hover:text-foreground cursor-pointer lg:hidden shrink-0"
          onClick={() => router.push(`/${runId}`)}
          aria-label="Back to list"
        />
        <span className="text-sm font-medium truncate flex-1 min-w-0">
          {detail?.display_label ?? ""}
        </span>
        <div className="flex items-center gap-1 shrink-0">
          {NAV_TABS.map((t) => {
            const isActive = (t.value === "detail" && contentView === "detail") ||
                             (t.value !== "detail" && contentView === "right" && tab === t.value)
            return (
              <Tooltip key={t.value}>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className={cn(
                      "h-7 w-7 cursor-pointer text-muted-foreground",
                      isActive && "bg-muted",
                    )}
                    onClick={() => handleNavTab(t.value)}
                    aria-label={t.label}
                  >
                    {t.icon}
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="top"><p>{t.label}</p></TooltipContent>
              </Tooltip>
            )
          })}
        </div>
      </div>

      <div className="h-11 shrink-0 border-b px-3 flex items-center gap-2 min-w-0">
        <HeaderContext
          tab={tab}
          activeDoc={activeDoc}
          chart={chart}
          documents={documents}
          citations={detail?.citations ?? []}
          activeDocId={activeDocId}
          setActiveDocId={setActiveDocId}
          detailLabel={detail?.display_label}
        />
        <div className="flex-1" />
        <div className="hidden xl:flex items-center gap-1 shrink-0">
          {TABS.map((t) => (
            <Tooltip key={t.value}>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className={cn(
                    "h-7 w-7 cursor-pointer text-muted-foreground",
                    tab === t.value && "bg-muted",
                  )}
                  onClick={() => setTab(t.value)}
                  aria-label={t.label}
                >
                  {t.icon}
                </Button>
              </TooltipTrigger>
              <TooltipContent side="top"><p>{t.label}</p></TooltipContent>
            </Tooltip>
          ))}
        </div>
      </div>

      {!selectedId ? (
        <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground gap-2">
          <Inbox className="size-8" />
          <div className="text-sm">Select a proposal to see context</div>
        </div>
      ) : tab === "notes" ? (
        !detail ? (
          <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">Loading…</div>
        ) : (
          <RightPanelNotes
            selectedId={selectedId}
            citations={detail.citations}
            documents={documents}
            activeDocId={activeDocId}
            setActiveDocId={setActiveDocId}
          />
        )
      ) : tab === "chart" ? (
        <RightPanelChart
          chart={chart}
          classification={detail?.classification ?? "NEW"}
          chartMatches={detail?.chart_matches ?? []}
        />
      ) : (
        <RightPanelChat />
      )}
    </section>
  )
}

function HeaderContext({
  tab,
  activeDoc,
  chart,
  documents,
  citations,
  activeDocId,
  setActiveDocId,
  detailLabel,
}: {
  tab: Tab
  activeDoc: SourceDocument | null
  chart: import("@/lib/types").ChartContext | null
  documents: SourceDocument[] | null
  citations: ResolvedCitation[]
  activeDocId: string | null
  setActiveDocId: (id: string) => void
  detailLabel?: string | null
}) {
  if (tab === "notes") {
    return (
      <NotesHeader
        activeDoc={activeDoc}
        documents={documents}
        citations={citations}
        activeDocId={activeDocId}
        setActiveDocId={setActiveDocId}
      />
    )
  }
  if (tab === "chart") {
    return <ChartHeader chart={chart} />
  }
  return <ChatHeader detailLabel={detailLabel ?? null} />
}

function NotesHeader({
  activeDoc,
  documents,
  citations,
  activeDocId,
  setActiveDocId,
}: {
  activeDoc: SourceDocument | null
  documents: SourceDocument[] | null
  citations: ResolvedCitation[]
  activeDocId: string | null
  setActiveDocId: (id: string) => void
}) {
  const cited = useMemo(() => {
    if (!documents) return []
    const ids = Array.from(new Set(citations.map((c) => c.document_id)))
    return ids
      .map((id) => documents.find((d) => d.id === id))
      .filter((d): d is SourceDocument => Boolean(d))
  }, [documents, citations])

  if (!activeDoc) return null
  const meta = [shortDate(activeDoc.date), activeDoc.author].filter(Boolean).join(" · ")
  const others = cited.length - 1
  const hasMany = cited.length > 1

  return (
    <div className="min-w-0 flex items-baseline gap-2">
      {hasMany ? (
        <>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="inline-flex items-baseline gap-1 text-sm font-medium truncate cursor-pointer hover:opacity-80 outline-none"
              >
                <span className="truncate">{activeDoc.type || "Document"}</span>
                <ChevronDown className="size-3 self-center text-muted-foreground" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-[260px]">
              {cited.map((d) => {
                const label = [d.type, shortDate(d.date), d.author].filter(Boolean).join(" · ")
                return (
                  <DropdownMenuItem
                    key={d.id}
                    onClick={() => setActiveDocId(d.id)}
                    className="text-xs"
                  >
                    <span className="truncate flex-1">{label || d.id}</span>
                    {d.id === activeDocId && <Check className="size-3 ml-2 text-muted-foreground" />}
                  </DropdownMenuItem>
                )
              })}
            </DropdownMenuContent>
          </DropdownMenu>
          {others > 0 && (
            <span className="text-[11px] text-muted-foreground tabular-nums shrink-0">+{others}</span>
          )}
        </>
      ) : (
        <>
          <span className="text-sm font-medium truncate">{activeDoc.type || "Document"}</span>
          {meta && <span className="text-[11px] text-muted-foreground truncate">{meta}</span>}
        </>
      )}
    </div>
  )
}

function ChartHeader({ chart }: { chart: import("@/lib/types").ChartContext | null }) {
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!chart?.fetched_at) return
    const id = window.setInterval(() => setTick((n) => n + 1), 30_000)
    return () => window.clearInterval(id)
  }, [chart?.fetched_at])

  if (!chart) return null
  const ago = formatTimeAgo(chart.fetched_at)
  const meta = [chart.source, ago].filter(Boolean).join(" · ")
  return (
    <div className="min-w-0 truncate text-[11px] text-muted-foreground tabular-nums">
      {meta}
    </div>
  )
}

function ChatHeader({ detailLabel: _detailLabel }: { detailLabel: string | null }) {
  return (
    <div className="min-w-0 truncate text-[11px] text-muted-foreground tabular-nums">
      gpt-5.4-mini · low reasoning
    </div>
  )
}
