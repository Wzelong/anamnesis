"use client"

import { useEffect, useMemo, useRef } from "react"
import ReactMarkdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"
import { visit, SKIP } from "unist-util-visit"
import type { Root, Element as HastElement, Text as HastText } from "hast"
import type { Plugin } from "unified"
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
  idx: number
}

function buildRanges(citations: ResolvedCitation[]): Range[] {
  const sorted = [...citations].sort((a, b) => a.char_start - b.char_start)
  const out: Range[] = []
  let nextIdx = 0
  for (const c of sorted) {
    const last = out[out.length - 1]
    if (last && c.char_start <= last.end) {
      last.end = Math.max(last.end, c.char_end)
    } else {
      out.push({ start: c.char_start, end: c.char_end, idx: nextIdx++ })
    }
  }
  return out
}

function isSpace(ch: string): boolean {
  return ch === " " || ch === "\t" || ch === "\n" || ch === "\r"
}

function buildSourceToValueMap(srcSlice: string, value: string): number[] {
  // map[i] = best-effort index into `value` for source offset i within srcSlice.
  // Handles common transforms by walking both strings and resolving mismatches:
  //   - soft breaks (\n + leading whitespace -> single space or nothing)
  //   - leading whitespace stripped from line/list-item content
  //   - trailing whitespace stripped
  //   - escape characters (\* -> *) consumed in source but emitted as one char in value
  const map = new Array<number>(srcSlice.length + 1)
  let srcIdx = 0
  let valIdx = 0
  while (srcIdx < srcSlice.length) {
    map[srcIdx] = valIdx
    const sc = srcSlice[srcIdx]
    const vc = valIdx < value.length ? value[valIdx] : ""
    if (sc === vc) {
      srcIdx++
      valIdx++
      continue
    }
    if (sc === "\\" && srcIdx + 1 < srcSlice.length && srcSlice[srcIdx + 1] === vc) {
      // Markdown escape: consume the backslash, then the escaped char on next iter.
      srcIdx++
      continue
    }
    if (isSpace(sc)) {
      // Whitespace differences (soft break collapse, leading indent strip).
      srcIdx++
      if (vc === " ") valIdx++
      continue
    }
    if (vc === " ") {
      // Extra space inserted in value (rare).
      valIdx++
      continue
    }
    // Unknown mismatch: advance both to keep moving without runaway drift.
    srcIdx++
    valIdx++
  }
  map[srcSlice.length] = valIdx
  return map
}

function rehypeHighlight(ranges: Range[], source: string): Plugin<[], Root> {
  return () => (tree: Root) => {
    if (ranges.length === 0) return
    visit(tree, "text", (node: HastText, index, parent) => {
      if (!node.position || !parent || index === undefined) return
      const ns = node.position.start.offset
      const ne = node.position.end.offset
      if (ns === undefined || ne === undefined) return
      const overlapping = ranges
        .filter((r) => r.end > ns && r.start < ne)
        .sort((a, b) => a.start - b.start)
      if (overlapping.length === 0) return

      const srcSlice = source.slice(ns, ne)
      const map = buildSourceToValueMap(srcSlice, node.value)

      const clamp = (n: number) => Math.max(0, Math.min(node.value.length, n))
      const newNodes: Array<HastText | HastElement> = []
      let valCursor = 0

      for (const r of overlapping) {
        const localStartSrc = Math.max(r.start - ns, 0)
        const localEndSrc = Math.min(r.end - ns, srcSlice.length)
        const localStartVal = clamp(map[localStartSrc] ?? valCursor)
        const localEndVal = clamp(map[localEndSrc] ?? node.value.length)
        if (localEndVal <= localStartVal) continue
        if (localStartVal > valCursor) {
          newNodes.push({ type: "text", value: node.value.slice(valCursor, localStartVal) })
        }
        newNodes.push({
          type: "element",
          tagName: "mark",
          properties: { "data-citation-idx": r.idx },
          children: [{ type: "text", value: node.value.slice(localStartVal, localEndVal) }],
        })
        valCursor = localEndVal
      }
      if (valCursor < node.value.length) {
        newNodes.push({ type: "text", value: node.value.slice(valCursor) })
      }

      const parentChildren = (parent as { children: Array<HastText | HastElement> }).children
      parentChildren.splice(index, 1, ...newNodes)
      return [SKIP, index + newNodes.length]
    })
  }
}

const markComponent: Components["mark"] = ({ node: _node, children, ...props }) => (
  <mark
    {...props}
    className="bg-amber-200/80 dark:bg-amber-400/25 text-foreground rounded-[3px] px-1 -mx-0.5 [box-decoration-break:clone] [-webkit-box-decoration-break:clone]"
  >
    {children}
  </mark>
)

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

  const ranges = useMemo(() => buildRanges(activeCitations), [activeCitations])

  const rehypePlugins = useMemo(
    () => (activeDoc ? [rehypeHighlight(ranges, activeDoc.text)] : []),
    [ranges, activeDoc],
  )

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
        <article className="markdown px-5 py-4 text-foreground/90">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={rehypePlugins}
            components={{ mark: markComponent }}
          >
            {activeDoc.text}
          </ReactMarkdown>
        </article>
      </div>
    </div>
  )
}
