"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { useTheme } from "next-themes"
import CodeMirror, { EditorView, type Extension, type ReactCodeMirrorRef } from "@uiw/react-codemirror"
import { json, jsonParseLinter } from "@codemirror/lang-json"
import { linter } from "@codemirror/lint"
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language"
import {
  SearchQuery,
  SearchCursor,
  closeSearchPanel,
  findNext,
  findPrevious,
  search,
  setSearchQuery,
} from "@codemirror/search"
import { tags as t } from "@lezer/highlight"
import { Check, ChevronDown, ChevronUp, Copy, Search, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface Props {
  value: string
  editable?: boolean
  onChange?: (next: string) => void
  hideTypeLabel?: boolean
}

const buildBaseTheme = (dark: boolean) => EditorView.theme({
  "&": {
    fontSize: "12px",
    backgroundColor: "transparent",
    color: "var(--foreground)",
    height: "auto",
  },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": {
    fontFamily: "var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace)",
    lineHeight: "1.6",
    overflow: "auto",
  },
  ".cm-content": { padding: "12px", caretColor: "var(--foreground)", minHeight: "100%" },
  ".cm-activeLine": { backgroundColor: "transparent" },
  ".cm-selectionBackground, ::selection": {
    backgroundColor: "color-mix(in oklch, var(--ring) 25%, transparent) !important",
  },
  ".cm-cursor": { borderLeftColor: "var(--foreground)" },
  ".cm-tooltip": {
    backgroundColor: "var(--popover)",
    color: "var(--popover-foreground)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius-md)",
    fontSize: "12px",
  },
  ".cm-diagnostic": { padding: "4px 8px" },
  ".cm-diagnostic-error": { borderLeftColor: "var(--destructive)" },
  ".cm-lintRange-error": {
    backgroundImage: "none",
    textDecoration: "underline wavy var(--destructive)",
    textUnderlineOffset: "2px",
  },
  ".cm-panels": { display: "none" },
  ".cm-searchMatch": {
    backgroundColor: "color-mix(in oklch, var(--warning-fg) 25%, transparent)",
    borderRadius: "2px",
  },
  ".cm-searchMatch-selected": {
    backgroundColor: "color-mix(in oklch, var(--warning-fg) 50%, transparent)",
    outline: "1px solid var(--warning-fg)",
    borderRadius: "2px",
  },
}, { dark })

const highlight = HighlightStyle.define([
  { tag: t.propertyName, color: "var(--foreground)", fontWeight: "500" },
  { tag: [t.string, t.special(t.string)], color: "var(--success-fg)" },
  { tag: t.number, color: "var(--warning-fg)" },
  { tag: t.bool, color: "var(--warning-fg)", fontStyle: "italic" },
  { tag: t.null, color: "var(--muted-foreground)", fontStyle: "italic" },
  { tag: t.keyword, color: "var(--muted-foreground)", fontStyle: "italic" },
  {
    tag: [t.brace, t.bracket, t.punctuation, t.separator],
    color: "color-mix(in oklch, var(--muted-foreground) 65%, transparent)",
  },
])

interface ResourceMeta {
  resourceType: string
  fieldCount: number
  parsed: boolean
}

function inspect(value: string): ResourceMeta {
  try {
    const obj = JSON.parse(value)
    if (obj && typeof obj === "object") {
      return {
        resourceType: typeof obj.resourceType === "string" ? obj.resourceType : "JSON",
        fieldCount: Object.keys(obj).length,
        parsed: true,
      }
    }
  } catch {
    /* noop */
  }
  return { resourceType: "JSON", fieldCount: 0, parsed: false }
}

export function JsonEditor({ value, editable = false, onChange, hideTypeLabel = false }: Props) {
  const ref = useRef<ReactCodeMirrorRef | null>(null)
  const meta = useMemo(() => inspect(value), [value])
  const { resolvedTheme } = useTheme()
  const isDark = resolvedTheme === "dark"

  const [searchOpen, setSearchOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [matchCount, setMatchCount] = useState(0)
  const [copied, setCopied] = useState(false)
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current)
    }
  }, [])

  const extensions = useMemo<Extension[]>(
    () => [
      json(),
      linter(jsonParseLinter()),
      syntaxHighlighting(highlight),
      search({ top: true }),
      EditorView.lineWrapping,
      buildBaseTheme(isDark),
    ],
    [isDark],
  )

  useEffect(() => {
    const view = ref.current?.view
    if (!view) return
    closeSearchPanel(view)
    if (!searchOpen || !query) {
      view.dispatch({ effects: setSearchQuery.of(new SearchQuery({ search: "" })) })
      setMatchCount(0)
      return
    }
    const sq = new SearchQuery({ search: query })
    view.dispatch({ effects: setSearchQuery.of(sq) })
    let count = 0
    const cursor = new SearchCursor(view.state.doc, query)
    while (!cursor.next().done) count++
    setMatchCount(count)
    findNext(view)
  }, [query, searchOpen])

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current)
      copyTimerRef.current = setTimeout(() => setCopied(false), 3000)
    } catch {
      /* ignore */
    }
  }

  const closeSearch = () => {
    setSearchOpen(false)
    setQuery("")
    ref.current?.view?.focus()
  }

  const handleSearchKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    const view = ref.current?.view
    if (e.key === "Escape") {
      e.preventDefault()
      closeSearch()
      return
    }
    if (e.key === "Enter" && view) {
      e.preventDefault()
      if (e.shiftKey) findPrevious(view)
      else findNext(view)
    }
  }

  return (
    <div className="flex flex-col">
      <div className="h-8 shrink-0 border-b bg-muted/30 flex items-center px-3">
        {searchOpen ? (
          <div className="flex items-center gap-1 flex-1 min-w-0">
            <Search className="size-3.5 text-muted-foreground shrink-0" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleSearchKey}
              placeholder="Find in JSON"
              className="flex-1 min-w-0 h-7 text-base md:text-xs bg-transparent outline-none placeholder:text-muted-foreground"
            />
            {query && (
              <span className="text-[11px] text-muted-foreground tabular-nums shrink-0 px-1">
                {matchCount} {matchCount === 1 ? "match" : "matches"}
              </span>
            )}
            <div className="flex items-center gap-1 shrink-0">
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 cursor-pointer text-muted-foreground"
                onClick={() => ref.current?.view && findPrevious(ref.current.view)}
                disabled={matchCount === 0}
                aria-label="Previous match"
              >
                <ChevronUp className="size-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 cursor-pointer text-muted-foreground"
                onClick={() => ref.current?.view && findNext(ref.current.view)}
                disabled={matchCount === 0}
                aria-label="Next match"
              >
                <ChevronDown className="size-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 cursor-pointer text-muted-foreground"
                onClick={closeSearch}
                aria-label="Close search"
              >
                <X className="size-3.5" />
              </Button>
            </div>
          </div>
        ) : (
          <>
            {!hideTypeLabel && (
              <span className="text-xs font-mono text-foreground shrink-0">{meta.resourceType}</span>
            )}
            <span className={cn(
              "text-[11px] text-muted-foreground tabular-nums shrink-0",
              !hideTypeLabel && "ml-2",
            )}>
              {meta.parsed ? `${meta.fieldCount} field${meta.fieldCount === 1 ? "" : "s"}` : "Invalid JSON"}
            </span>
            <div className="flex-1" />
            <div className="flex items-center gap-1 shrink-0">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-7 w-7 cursor-pointer text-muted-foreground" onClick={() => setSearchOpen(true)} aria-label="Search">
                    <Search className="size-3.5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="top"><p>Search</p></TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-7 w-7 cursor-pointer text-muted-foreground" onClick={handleCopy} aria-label={copied ? "Copied" : "Copy"}>
                    {copied
                      ? <Check className="size-3.5 text-success-fg" />
                      : <Copy className="size-3.5" />}
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="top"><p>{copied ? "Copied" : "Copy"}</p></TooltipContent>
              </Tooltip>
            </div>
          </>
        )}
      </div>

      <div>
        <CodeMirror
          ref={ref}
          value={value}
          editable={editable}
          readOnly={!editable}
          theme="none"
          extensions={extensions}
          basicSetup={{
            lineNumbers: false,
            foldGutter: false,
            highlightActiveLine: false,
            highlightActiveLineGutter: false,
            highlightSelectionMatches: false,
            searchKeymap: false,
            indentOnInput: editable,
            bracketMatching: true,
            autocompletion: false,
          }}
          onChange={onChange}
        />
      </div>
    </div>
  )
}
