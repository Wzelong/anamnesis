import * as React from "react"
import { CircleX } from "lucide-react"

import { cn } from "@/lib/utils"

const Input = React.forwardRef<
  HTMLInputElement,
  React.ComponentProps<"input"> & { onClear?: () => void }
>(({ className, type, onClear, value, ...props }, ref) => {
  const [showClear, setShowClear] = React.useState(false)

  React.useEffect(() => {
    setShowClear(!!value && value.toString().length > 0)
  }, [value])

  return (
    <div className="relative w-full">
      <input
        type={type}
        ref={ref}
        value={value}
        data-slot="input"
        className={cn(
          "file:text-foreground placeholder:text-muted-foreground selection:bg-primary selection:text-primary-foreground dark:bg-input/30 border-input h-9 w-full min-w-0 rounded-md border bg-transparent px-2 py-1 text-base shadow-xs transition-[color,box-shadow] outline-none file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
          "focus-visible:border-brand-light focus-visible:ring-0 focus-visible:shadow-none",
          "aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive",
          showClear && onClear && "pr-9",
          className
        )}
        {...props}
      />
      {showClear && onClear && (
        <button
          type="button"
          onClick={onClear}
          className="absolute right-2.5 top-1/2 -translate-y-1/2 cursor-pointer"
        >
          <CircleX className="h-3.5 w-3.5 text-muted-foreground hover:text-brand-light transition-colors" />
        </button>
      )}
    </div>
  )
})
Input.displayName = "Input"

export { Input }
