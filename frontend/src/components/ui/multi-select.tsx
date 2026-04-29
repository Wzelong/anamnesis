import * as React from "react"
import { Check, ChevronDown, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Command,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Separator } from "@/components/ui/separator"

export interface MultiSelectOption {
  value: string
  label: string
}

export interface MultiSelectProps {
  fixedItems?: MultiSelectOption[]
  options: MultiSelectOption[]
  value: string[]
  onValueChange: (value: string[]) => void
  placeholder?: string
  disabled?: boolean
  className?: string
  size?: "default" | "sm"
  variant?: "outline" | "ghost"
  showSearch?: boolean
}

export function MultiSelect({
  fixedItems = [],
  options,
  value,
  onValueChange,
  placeholder = "Select options",
  disabled = false,
  className,
  size = "default",
  variant = "outline",
  showSearch = true,
}: MultiSelectProps) {
  const sm = size === "sm"
  const ghost = variant === "ghost"
  const [open, setOpen] = React.useState(false)
  const [search, setSearch] = React.useState("")

  const fixedValues = React.useMemo(
    () => fixedItems.map((item) => item.value),
    [fixedItems]
  )

  const toggleOption = (optionValue: string) => {
    if (fixedValues.includes(optionValue)) return

    const newValue = value.includes(optionValue)
      ? value.filter((v) => v !== optionValue)
      : [...value, optionValue]

    onValueChange(newValue)
  }

  const handleClear = () => {
    onValueChange(fixedValues)
  }

  const allItems = React.useMemo(
    () => [...fixedItems, ...options],
    [fixedItems, options]
  )

  const filteredOptions = React.useMemo(() => {
    if (!search) return options
    return options.filter((option) =>
      option.label.toLowerCase().includes(search.toLowerCase())
    )
  }, [options, search])

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant={ghost ? "ghost" : "outline"}
          role="combobox"
          aria-expanded={open}
          disabled={disabled}
          className={cn(
            "w-full justify-between h-auto cursor-pointer group",
            sm ? "min-h-7 px-2 py-0.5 text-xs" : "min-h-10 px-3 py-2",
            ghost && "border-0 shadow-none bg-transparent px-1 -mx-1 hover:bg-accent/50",
            className
          )}
        >
          {value.length > 0 ? (
            <div className="flex flex-wrap gap-1 flex-1">
              {value.map((val) => {
                const item = allItems.find((opt) => opt.value === val)
                if (!item) return null
                const isFixed = fixedValues.includes(val)
                return (
                  <Badge
                    key={val}
                    variant="outline"
                    className={cn(
                      "font-normal border-transparent",
                      sm && "text-[10px] px-1 py-0",
                      isFixed
                        ? "bg-muted text-muted-foreground"
                        : "bg-[oklch(0.93_0.002_286.375)] text-[oklch(0.30_0.01_285.885)] dark:bg-[oklch(0.35_0.01_286.033)] dark:text-[oklch(0.92_0_0)]"
                    )}
                  >
                    {item.label}
                  </Badge>
                )
              })}
            </div>
          ) : (
            <span className="text-muted-foreground">{placeholder}</span>
          )}
          <div className="flex items-center gap-2 ml-2 shrink-0">
            {value.length > fixedValues.length && (
              <>
                <div
                  role="button"
                  tabIndex={0}
                  onClick={(e) => {
                    e.stopPropagation()
                    handleClear()
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      e.stopPropagation()
                      handleClear()
                    }
                  }}
                  className="inline-flex items-center justify-center rounded hover:bg-accent transition-colors cursor-pointer"
                  aria-label="Clear all selections"
                >
                  <X className="h-4 w-4 text-muted-foreground hover:text-foreground" />
                </div>
                <Separator orientation="vertical" className="h-4" />
              </>
            )}
            <ChevronDown className={cn("text-muted-foreground group-hover:text-foreground transition-colors", sm ? "h-3 w-3" : "h-4 w-4")} />
          </div>
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="p-0"
        style={{
          width: "var(--radix-popover-trigger-width)",
        }}
        align="start"
      >
        <Command>
          {showSearch && (
            <CommandInput
              placeholder="Search..."
              value={search}
              onValueChange={setSearch}
            />
          )}
          <CommandList>
            <CommandEmpty>No results found.</CommandEmpty>
            {fixedItems.length > 0 && (
              <>
                {fixedItems.map((item) => {
                  const isSelected = value.includes(item.value)
                  return (
                    <CommandItem
                      key={item.value}
                      onSelect={() => {}}
                      className="cursor-default aria-selected:!bg-transparent hover:!bg-transparent data-[selected=true]:!bg-transparent"
                    >
                      <div
                        className={cn(
                          "mr-2 flex h-4 w-4 items-center justify-center rounded-sm border border-primary",
                          isSelected
                            ? "bg-primary"
                            : "opacity-50 [&_svg]:invisible"
                        )}
                      >
                        <Check className="h-4 w-4 text-white dark:text-black" />
                      </div>
                      {item.label}
                    </CommandItem>
                  )
                })}
                <CommandSeparator />
              </>
            )}
            {filteredOptions.map((option) => {
              const isSelected = value.includes(option.value)
              return (
                <CommandItem
                  key={option.value}
                  onSelect={() => toggleOption(option.value)}
                  className="cursor-pointer"
                >
                  <div
                    className={cn(
                      "mr-2 flex h-4 w-4 items-center justify-center rounded-sm border border-primary",
                      isSelected
                        ? "bg-primary"
                        : "opacity-50 [&_svg]:invisible"
                    )}
                  >
                    <Check className="h-4 w-4 text-white dark:text-black" />
                  </div>
                  {option.label}
                </CommandItem>
              )
            })}
          </CommandList>
          <CommandSeparator />
          <div className="p-1 flex items-center">
            <Button
              variant="ghost"
              size="sm"
              onClick={handleClear}
              className="flex-1 justify-center h-8"
            >
              Clear
            </Button>
            <Separator orientation="vertical" className="h-6" />
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setOpen(false)}
              className="flex-1 justify-center h-8"
            >
              Close
            </Button>
          </div>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
