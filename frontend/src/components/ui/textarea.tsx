import * as React from "react"

import { cn } from "@/lib/utils"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "border-input placeholder:text-muted-foreground dark:bg-input/30 flex field-sizing-content min-h-16 w-full rounded-md border bg-transparent px-3 py-2 text-base transition-colors outline-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
        "focus-visible:border-brand-light focus-visible:ring-0 focus-visible:shadow-none",
        "aria-invalid:border-destructive",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
