import { useEffect, useMemo, useRef } from "react"
import ReactMarkdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"
import { visit, SKIP } from "unist-util-visit"
import type { Root, Element as HastElement, Text as HastText } from "hast"
import type { Plugin } from "unified"
import type { ResolvedCitation, SourceDocument } from "../types"

interface Props {
  document: SourceDocument | null
  citations: ResolvedCitation[]
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
      srcIdx++
      continue
    }
    if (isSpace(sc)) {
      srcIdx++
      if (vc === " ") valIdx++
      continue
    }
    if (vc === " ") {
      valIdx++
      continue
    }
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

export function NoteReader({ document, citations }: Props) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const activeDoc = document

  const ranges = useMemo(() => buildRanges(citations), [citations])

  const rehypePlugins = useMemo(
    () => (activeDoc ? [rehypeHighlight(ranges, activeDoc.text)] : []),
    [ranges, activeDoc],
  )

  useEffect(() => {
    if (!activeDoc || ranges.length === 0) return
    let cancelled = false
    let raf = 0
    let attempts = 0
    const maxAttempts = 20
    const tryScroll = () => {
      if (cancelled) return
      const target = scrollRef.current?.querySelector('mark[data-citation-idx="0"]')
      if (target) {
        target.scrollIntoView({ block: "center", behavior: "smooth" })
        return
      }
      if (++attempts < maxAttempts) {
        raf = requestAnimationFrame(tryScroll)
      }
    }
    raf = requestAnimationFrame(tryScroll)
    return () => {
      cancelled = true
      cancelAnimationFrame(raf)
    }
  }, [activeDoc, ranges])

  if (!activeDoc) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm px-6 text-center">
        No source notes for this proposal.
      </div>
    )
  }

  return (
    <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden">
      <article className="markdown px-4 py-4 text-foreground/90">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={rehypePlugins}
          components={{ mark: markComponent }}
        >
          {activeDoc.text}
        </ReactMarkdown>
      </article>
    </div>
  )
}
