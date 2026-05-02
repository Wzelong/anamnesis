"use client"

import { Markdown } from "@/components/ui/markdown"
import { cn } from "@/lib/utils"

interface Props {
  role: "user" | "assistant"
  content: string
}

export function ChatMessageBubble({ role, content }: Props) {
  if (role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] bg-muted px-4 py-2 rounded-2xl text-sm whitespace-pre-wrap">
          {content}
        </div>
      </div>
    )
  }

  return (
    <div className={cn("max-w-[85%]")}>
      <Markdown content={content} compact className="text-sm" />
    </div>
  )
}
