"use client"

import { useState, type ReactNode } from "react"
import { ChevronRight } from "lucide-react"
import { cn } from "@/lib/utils"

interface Props {
  title: string
  children: ReactNode
  defaultOpen?: boolean
  suffix?: ReactNode
}

export function Disclosure({ title, children, defaultOpen, suffix }: Props) {
  const [open, setOpen] = useState(!!defaultOpen)
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-1.5 group cursor-pointer"
      >
        <ChevronRight
          className={cn(
            "size-3 text-muted-foreground transition-transform shrink-0",
            open && "rotate-90",
          )}
        />
        <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground group-hover:text-foreground transition-colors">
          {title}
        </span>
        {suffix && <div className="ml-auto">{suffix}</div>}
      </button>
      {open && <div className="mt-2 pl-4">{children}</div>}
    </div>
  )
}
