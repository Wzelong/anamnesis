// TODO(chat): wire transcript, input, streaming
"use client"

import { MessageSquare } from "lucide-react"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"

export function RightPanelChat() {
  return (
    <Empty className="flex-1 border-0">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <MessageSquare />
        </EmptyMedia>
        <EmptyTitle>Ask the agent</EmptyTitle>
        <EmptyDescription>
          Coming soon — discuss this proposal with the model.
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  )
}
