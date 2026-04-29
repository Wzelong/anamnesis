"use client"

import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { cn } from "@/lib/utils"

interface MarkdownProps {
  content: string
  compact?: boolean
  className?: string
}

export function Markdown({ content, compact, className }: MarkdownProps) {
  return (
    <div className={cn("markdown", compact && "text-sm", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  )
}
