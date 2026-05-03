"use client"

import { useState, useEffect, useRef } from "react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuPortal,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Search, ListFilter, ChevronLeft, ChevronRight, CheckCheck } from "lucide-react"
import { cn } from "@/lib/utils"
import type { DataListProps } from "./data-list-types"

const BAR_DURATION = 1200

function LoadingBar({ active }: { active: boolean }) {
  const [visible, setVisible] = useState(false)
  const startRef = useRef(0)

  useEffect(() => {
    if (active) {
      startRef.current = Date.now()
      setVisible(true)
    } else if (visible) {
      const elapsed = Date.now() - startRef.current
      const remaining = Math.max(0, BAR_DURATION - (elapsed % BAR_DURATION))
      const timer = setTimeout(() => setVisible(false), remaining)
      return () => clearTimeout(timer)
    }
  }, [active])

  if (!visible) return null

  return (
    <div className="absolute inset-x-0 top-0 z-10 h-0.5 overflow-hidden">
      <div
        className="absolute h-full w-1/3 bg-muted-foreground/30 rounded-full"
        style={{ animation: `indeterminate ${BAR_DURATION}ms ease-in-out infinite` }}
      />
    </div>
  )
}

export function DataList<T>({
  data,
  getItemId,
  renderItem,
  searchPlaceholder = "Search...",
  searchValue,
  onSearchChange,
  searchDebounceMs = 0,
  filters,
  pagination,
  selectedIds = new Set(),
  onSelectAll,
  onSelectOne,
  onClearSelection,
  isItemSelectable,
  activeId,
  toolbarButtons = [],
  bulkActions = [],
  selectionStatus,
  onItemClick,
  emptyState,
  isFetching,
  headerExtra,
}: DataListProps<T>) {
  const [searchInputValue, setSearchInputValue] = useState(searchValue)
  const hasSelection = onSelectAll && onSelectOne
  const isAllSelected = data.length > 0 && selectedIds.size === data.length
  const hasActiveFilter = filters?.some((f) => f.value !== null) || false

  const totalPages = Math.max(1, Math.ceil(pagination.totalItems / pagination.pageSize))
  const safePage = Math.min(pagination.currentPage, totalPages)
  const startIdx = pagination.totalItems === 0 ? 0 : (safePage - 1) * pagination.pageSize
  const endIdx = Math.min(startIdx + pagination.pageSize, pagination.totalItems)

  const listRef = useRef<HTMLDivElement>(null)
  const firstItemRef = useRef<HTMLDivElement>(null)
  const onPageSizeChange = pagination.onPageSizeChange
  const currentPageSize = pagination.pageSize

  useEffect(() => {
    if (!onPageSizeChange) return
    const listEl = listRef.current
    if (!listEl) return

    let lastReported = currentPageSize
    const compute = () => {
      const listHeight = listEl.clientHeight
      const itemHeight = firstItemRef.current?.getBoundingClientRect().height ?? 0
      if (listHeight <= 0) return
      const effectiveItemHeight = itemHeight > 0 ? itemHeight : 48
      const next = Math.max(1, Math.floor(listHeight / effectiveItemHeight))
      if (next !== lastReported) {
        lastReported = next
        onPageSizeChange(next)
      }
    }

    compute()
    const ro = new ResizeObserver(compute)
    ro.observe(listEl)
    if (firstItemRef.current) ro.observe(firstItemRef.current)
    return () => ro.disconnect()
  }, [onPageSizeChange, currentPageSize, data.length])

  useEffect(() => {
    setSearchInputValue(searchValue)
  }, [searchValue])

  useEffect(() => {
    if (!onSearchChange) return
    if (searchInputValue === searchValue) return
    if (searchDebounceMs <= 0) {
      onSearchChange(searchInputValue ?? "")
      return
    }
    const timer = setTimeout(() => onSearchChange(searchInputValue ?? ""), searchDebounceMs)
    return () => clearTimeout(timer)
  }, [searchDebounceMs, searchInputValue, searchValue, onSearchChange])

  const clearSelection = () => {
    if (selectedIds.size > 0) onClearSelection?.()
  }

  const renderFilters = () => {
    if (!filters || filters.length === 0) return null

    return (
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className={cn("h-6 w-6 cursor-pointer text-muted-foreground", hasActiveFilter && "bg-accent")}
          >
            <ListFilter className="size-3" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-40">
          <DropdownMenuItem
            onClick={() => { filters.forEach((f) => f.onChange("")); clearSelection() }}
            className={cn("cursor-pointer", !hasActiveFilter && "bg-accent")}
          >
            <span className="flex-1">All</span>
          </DropdownMenuItem>
          {filters.map((filter, idx) => {
            if (filter.type === "toggle") {
              const isActive = filter.value !== null
              return (
                <DropdownMenuItem
                  key={idx}
                  onClick={() => { filter.onChange(isActive ? "" : "true"); clearSelection() }}
                  className={cn("cursor-pointer", isActive && "bg-accent")}
                >
                  <span className="flex-1 truncate">{filter.label}</span>
                  <span className="text-xs text-muted-foreground ml-2">{filter.count ?? 0}</span>
                </DropdownMenuItem>
              )
            }
            return (
              <DropdownMenuSub key={idx}>
                <DropdownMenuSubTrigger className={cn("cursor-pointer", filter.value !== null && "bg-accent")}>
                  <span className="flex-1">{filter.label}</span>
                </DropdownMenuSubTrigger>
                <DropdownMenuPortal>
                  <DropdownMenuSubContent className="w-40">
                    {filter.options.length === 0 ? (
                      <div className="px-2 py-1.5 text-xs text-muted-foreground">
                        {isFetching ? "Loading..." : "No options"}
                      </div>
                    ) : (
                      filter.options.map((option) => {
                        const isActive = filter.value === option.value
                        return (
                          <DropdownMenuItem
                            key={option.value}
                            onClick={() => { filter.onChange(isActive ? "" : option.value); clearSelection() }}
                            className={cn("cursor-pointer", isActive && "bg-accent")}
                          >
                            <span className="flex-1 truncate">{option.label}</span>
                            {option.count !== undefined && (
                              <span className="text-xs text-muted-foreground ml-2">{option.count}</span>
                            )}
                          </DropdownMenuItem>
                        )
                      })
                    )}
                  </DropdownMenuSubContent>
                </DropdownMenuPortal>
              </DropdownMenuSub>
            )
          })}
        </DropdownMenuContent>
      </DropdownMenu>
    )
  }

  return (
    <div className="flex flex-col h-full relative">
      <LoadingBar active={!!isFetching} />

      {/* Toolbar */}
      <div className="flex items-center justify-between gap-2 px-3 h-11 border-b shrink-0 select-none">
        {selectedIds.size > 0 ? (
          <>
            <span
              className={cn("text-xs flex-1", !selectionStatus?.variant && "text-muted-foreground")}
              style={{
                color: selectionStatus?.variant === "success"
                  ? "var(--success-fg)"
                  : selectionStatus?.variant === "loading"
                    ? "var(--warning-fg)"
                    : undefined,
              }}
            >
              {selectionStatus?.text || `${selectedIds.size} selected`}
            </span>
            <div className="flex items-center gap-1">
              {onSelectAll && (
                <Button
                  variant="ghost"
                  size="icon"
                  className={cn("h-6 w-6 cursor-pointer text-muted-foreground", isAllSelected && "bg-muted")}
                  onClick={onSelectAll}
                  aria-label={isAllSelected ? "Deselect all" : "Select all"}
                >
                  <CheckCheck className="size-3" />
                </Button>
              )}
              {bulkActions.map((action, idx) => (
                <Button
                  key={idx}
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 cursor-pointer text-muted-foreground"
                  onClick={() => action.onClick(selectedIds)}
                  disabled={selectionStatus?.variant === "loading" || selectionStatus?.variant === "success"}
                  aria-label={action.ariaLabel}
                >
                  {action.icon}
                </Button>
              ))}
            </div>
          </>
        ) : (
          <>
            {onSearchChange ? (
              <div className="relative flex-1 min-w-0 -ml-1">
                <Search className="absolute left-1 top-1.5 h-3.5 w-3.5 text-muted-foreground" />
                <input
                  placeholder={searchPlaceholder}
                  value={searchInputValue ?? ""}
                  onChange={(e) => { setSearchInputValue(e.target.value); clearSelection() }}
                  className="pl-6 h-7 text-xs w-full bg-transparent outline-none placeholder:text-muted-foreground"
                />
              </div>
            ) : (
              <div className="flex-1 min-w-0" />
            )}
            <div className="flex items-center gap-1">
              {renderFilters()}
              {toolbarButtons.map((button, idx) => (
                <Button
                  key={idx}
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 cursor-pointer text-muted-foreground"
                  onClick={button.onClick}
                  disabled={button.disabled}
                  aria-label={button.ariaLabel}
                >
                  {button.icon}
                </Button>
              ))}
            </div>
          </>
        )}
      </div>

      {headerExtra}

      {/* List */}
      <div ref={listRef} className="flex-1 overflow-y-auto min-h-0">
        {data.length === 0 && emptyState ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 px-4">
            {emptyState.icon}
            <p className={cn("text-sm text-muted-foreground text-center", isFetching && "shimmer-text")}>
              {emptyState.message}
            </p>
            {emptyState.actionLabel && emptyState.onAction && (
              <Button variant="outline" size="sm" onClick={emptyState.onAction} className="cursor-pointer">
                {emptyState.actionLabel}
              </Button>
            )}
          </div>
        ) : (
          data.map((item, idx) => {
            const itemId = getItemId(item)
            const isActive = activeId === itemId
            const isSelected = selectedIds.has(itemId)

            return (
              <div
                key={itemId}
                ref={idx === 0 ? firstItemRef : null}
                className={cn(
                  "flex items-start gap-2 px-2 py-2.5 border-b transition-colors select-none",
                  isActive ? "bg-muted" : "hover:bg-muted/50",
                  onItemClick && "cursor-pointer",
                )}
                onClick={() => onItemClick?.(item)}
              >
                {hasSelection && (
                  isItemSelectable && !isItemSelectable(item) ? (
                    <div className="size-4 mt-[3px] shrink-0" aria-hidden />
                  ) : (
                    <Checkbox
                      checked={isSelected}
                      onCheckedChange={() => onSelectOne?.(itemId)}
                      onClick={(e) => e.stopPropagation()}
                      className="cursor-pointer mt-[3px] shrink-0"
                      aria-label={`Select item ${itemId}`}
                    />
                  )
                )}
                <div className="flex-1 min-w-0">{renderItem(item)}</div>
              </div>
            )
          })
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-3 py-3 border-t shrink-0 select-none">
          <span className="text-xs text-muted-foreground">{startIdx + 1}-{endIdx} of {pagination.totalItems}</span>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 cursor-pointer text-muted-foreground"
              onClick={() => { pagination.onPageChange(Math.max(1, safePage - 1)); clearSelection() }}
              disabled={safePage === 1}
            >
              <ChevronLeft className="size-3" />
            </Button>
            <span className="text-xs text-muted-foreground min-w-[2rem] text-center">{safePage}/{totalPages}</span>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 cursor-pointer text-muted-foreground"
              onClick={() => { pagination.onPageChange(Math.min(totalPages, safePage + 1)); clearSelection() }}
              disabled={safePage === totalPages}
            >
              <ChevronRight className="size-3" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
