"use client"

import { Fragment, useEffect, useMemo, useRef } from "react"
import type { ResolvedCitation, SourceDocument } from "@/lib/types"

interface Props {
  selectedId: string | null
  citations: ResolvedCitation[]
  documents: SourceDocument[] | null
  activeDocId: string | null
  setActiveDocId: (id: string) => void
}

interface Range {
  start: number
  end: number
}

function mergeRanges(citations: ResolvedCitation[]): Range[] {
  const sorted = [...citations].sort((a, b) => a.char_start - b.char_start)
  const out: Range[] = []
  for (const c of sorted) {
    const last = out[out.length - 1]
    if (last && c.char_start <= last.end) {
      last.end = Math.max(last.end, c.char_end)
    } else {
      out.push({ start: c.char_start, end: c.char_end })
    }
  }
  return out
}

function renderHighlighted(text: string, ranges: Range[]) {
  if (ranges.length === 0) return text
  const parts: React.ReactNode[] = []
  let cursor = 0
  ranges.forEach((r, i) => {
    if (cursor < r.start) parts.push(text.slice(cursor, r.start))
    parts.push(
      <mark
        key={i}
        data-citation-idx={i}
        className="bg-warning-bg/50 text-foreground rounded-sm px-0.5 -mx-0.5"
      >
        {text.slice(r.start, r.end)}
      </mark>,
    )
    cursor = r.end
  })
  if (cursor < text.length) parts.push(text.slice(cursor))
  return parts.map((p, i) => <Fragment key={i}>{p}</Fragment>)
}

export function RightPanelNotes({ selectedId, citations, documents, activeDocId, setActiveDocId }: Props) {
  const scrollRef = useRef<HTMLDivElement | null>(null)

  const uniqueDocIds = useMemo(
    () => Array.from(new Set(citations.map((c) => c.document_id))),
    [citations],
  )

  useEffect(() => {
    if (uniqueDocIds.length === 0) return
    if (!activeDocId || !uniqueDocIds.includes(activeDocId)) {
      setActiveDocId(uniqueDocIds[0])
    }
  }, [uniqueDocIds, activeDocId, setActiveDocId])

  const activeDoc = useMemo(
    () => documents?.find((d) => d.id === activeDocId) ?? null,
    [documents, activeDocId],
  )

  const activeCitations = useMemo(
    () => citations.filter((c) => c.document_id === activeDocId),
    [citations, activeDocId],
  )

  const ranges = useMemo(() => mergeRanges(activeCitations), [activeCitations])

  useEffect(() => {
    if (!activeDoc || ranges.length === 0) return
    const raf = requestAnimationFrame(() => {
      const target = scrollRef.current?.querySelector('mark[data-citation-idx="0"]')
      if (target) target.scrollIntoView({ block: "center", behavior: "smooth" })
    })
    return () => cancelAnimationFrame(raf)
  }, [selectedId, activeDoc, ranges.length])

  if (!documents) {
    return <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">Loading…</div>
  }

  if (!activeDoc) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm px-6 text-center">
        No source notes for this proposal.
      </div>
    )
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden">
        <article className="px-3 py-6">
          <div className="whitespace-pre-wrap break-words font-sans text-[14.5px] leading-7 text-foreground/90">
            {renderHighlighted(activeDoc.text, ranges)}
          </div>
        </article>
      </div>
    </div>
  )
}
