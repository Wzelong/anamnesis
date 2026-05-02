"use client"

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import Image from "next/image"
import {
  GitCompareArrows,
  ListOrdered,
  Lock,
  Microscope,
  Quote,
  ScanSearch,
  TriangleAlert,
} from "lucide-react"
import { useAppStore } from "@/lib/store"
import type { ChatMessage, Proposal, ProposalDetail } from "@/lib/types"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { ChatMessageBubble } from "./chat/chat-message-bubble"
import { ChatInput } from "./chat/chat-input"
import { LoadingIndicator } from "./chat/loading-indicator"
import { ActionChoices, extractChoices } from "./chat/action-choices"
import { ProposedEditCard } from "./chat/proposed-edit-card"
import { ToolBreadcrumb } from "./chat/tool-breadcrumb"

export function RightPanelChat() {
  const runId = useAppStore((s) => s.runId)
  const messages = useAppStore((s) => (runId ? s.chatByRun[runId] : undefined)) ?? []
  const streaming = useAppStore((s) => s.chatStreaming)
  const status = useAppStore((s) => s.chatStatus)
  const error = useAppStore((s) => s.chatError)
  const tokenValid = useAppStore((s) => s.tokenValid)
  const proposals = useAppStore((s) => s.proposals)
  const detail = useAppStore((s) => s.selectedDetail)
  const sendChatMessage = useAppStore((s) => s.sendChatMessage)
  const stopChat = useAppStore((s) => s.stopChat)
  const dismissProposedEdit = useAppStore((s) => s.dismissProposedEdit)
  const resetChatForRun = useAppStore((s) => s.resetChatForRun)

  const [draft, setDraft] = useState<string | undefined>(undefined)
  const [focusKey, setFocusKey] = useState(0)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!runId) return
    return () => {
      const next = useAppStore.getState().runId
      if (next !== runId) resetChatForRun(runId)
    }
  }, [runId, resetChatForRun])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [messages.length, streaming, status])

  const welcomeOptions = useMemo(() => buildWelcomeOptions(detail, proposals), [detail, proposals])

  const reviseFor = (rationale: string) => {
    setDraft(`Refine: ${rationale}`)
    setFocusKey((n) => n + 1)
  }

  if (!runId) return null

  if (tokenValid !== true) {
    return <UnauthenticatedChat verifying={tokenValid === null} />
  }

  const isEmpty = messages.length === 0

  return (
    <div className="flex flex-col flex-1 min-h-0 relative">
      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto">
        {isEmpty ? (
          <WelcomeScreen
            options={welcomeOptions}
            onPick={(opt) => sendChatMessage(opt)}
          />
        ) : (
          <div className="flex flex-col gap-3 px-4 py-4 pb-24">
            {messages.map((m) => (
              <RenderedMessage
                key={m.id}
                message={m}
                streaming={streaming}
                onPick={(opt) => sendChatMessage(opt)}
                onRevise={(rationale) => reviseFor(rationale)}
                onDismiss={() => dismissProposedEdit(m.id)}
              />
            ))}
            {streaming && <LoadingIndicator status={status} />}
          </div>
        )}
      </div>

      <div className="absolute inset-x-0 bottom-0 border-t bg-background px-3 py-2">
        {error && (
          <div className="mb-2 text-[11px] text-destructive">{error}</div>
        )}
        <ChatInput
          onSend={(text) => sendChatMessage(text)}
          onStop={streaming ? stopChat : undefined}
          isLoading={streaming}
          initialValue={draft}
          focusKey={focusKey}
        />
      </div>
    </div>
  )
}

function RenderedMessage({
  message,
  streaming,
  onPick,
  onRevise,
  onDismiss,
}: {
  message: ChatMessage
  streaming: boolean
  onPick: (opt: string) => void
  onRevise: (rationale: string) => void
  onDismiss: () => void
}) {
  if (message.role === "tool") {
    return <ToolBreadcrumb name={message.toolName ?? ""} status={message.toolStatus} summary={message.toolSummary} />
  }
  if (message.role === "user") {
    return <ChatMessageBubble role="user" content={message.content} />
  }
  if (message.proposedEdit) {
    return (
      <ProposedEditCard
        messageId={message.id}
        edit={message.proposedEdit}
        onRevise={() => {
          onDismiss()
          onRevise(message.proposedEdit?.rationale ?? "")
        }}
      />
    )
  }
  const { stripped, options } = extractChoices(message.content)
  return (
    <div className="flex flex-col gap-2">
      <ChatMessageBubble role="assistant" content={stripped} />
      {options.length > 0 && (
        <ActionChoices options={options} onPick={onPick} disabled={streaming} />
      )}
    </div>
  )
}

interface WelcomeOption {
  label: string
  icon: ReactNode
}

function WelcomeScreen({
  options,
  onPick,
}: {
  options: WelcomeOption[]
  onPick: (opt: string) => void
}) {
  return (
    <div className="h-full flex flex-col items-center justify-center px-6 pb-20 gap-4 text-center">
      <Image src="/logo.png" alt="Anamnesis" width={40} height={40} className="size-10" />
      <div className="space-y-1">
        <div className="text-sm font-medium">Ask about this proposal</div>
        <div className="text-xs text-muted-foreground max-w-sm">
          Cross-reference notes, the chart, and code systems. Edits go through the same review flow.
        </div>
      </div>
      {options.length > 0 ? (
        <div className="flex flex-col gap-1.5 w-full max-w-sm">
          {options.map((opt) => (
            <button
              key={opt.label}
              type="button"
              onClick={() => onPick(opt.label)}
              className="text-left text-sm rounded-md border px-3 py-2 hover:bg-muted cursor-pointer flex items-center gap-2"
            >
              <span className="text-muted-foreground shrink-0 [&>svg]:size-3.5">{opt.icon}</span>
              <span className="truncate">{opt.label}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function UnauthenticatedChat({ verifying }: { verifying: boolean }) {
  return (
    <Empty className="flex-1 border-0">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Lock />
        </EmptyMedia>
        <EmptyTitle>{verifying ? "Verifying access…" : "Sign in to chat"}</EmptyTitle>
        <EmptyDescription>
          {verifying
            ? "Checking your review token."
            : "Chat needs an alias of the clinician's Prompt Opinion session. Without it, no FHIR change — Provenance always names a verified clinician. Production would SSO-embed this surface."}
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  )
}

function buildWelcomeOptions(
  detail: ProposalDetail | null,
  proposals: Proposal[],
): WelcomeOption[] {
  const opts: WelcomeOption[] = [
    { label: "Show the source quote behind this", icon: <Quote /> },
  ]

  if (detail?.classification === "CONFLICTING") {
    opts.push({ label: "Why does this conflict with the chart?", icon: <GitCompareArrows /> })
  } else if (detail?.confidence_tier === "ATTENTION") {
    opts.push({ label: "Why was this flagged for attention?", icon: <TriangleAlert /> })
  } else if (detail?.confidence_tier === "REVIEW") {
    opts.push({ label: "Walk me through the reasoning", icon: <Microscope /> })
  }

  const pendingOthers = proposals.filter(
    (p) => p.status === "pending" && p.id !== detail?.id,
  ).length
  if (pendingOthers > 0) {
    opts.push({ label: "What should I review next?", icon: <ListOrdered /> })
  }

  opts.push({ label: "Anything in the notes I might have missed?", icon: <ScanSearch /> })

  return opts.slice(0, 4)
}
