"use client"

import { useState, useEffect, useRef } from "react"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
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
import { Search, X, ListFilter, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, ChevronUp, ChevronDown } from "lucide-react"
import type { DataTableProps } from "./data-table-types"

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

const hiddenClass = (hidden?: boolean | "sm" | "md" | "lg") =>
  hidden === true || hidden === "md" ? "hidden md:table-cell" :
  hidden === "sm" ? "hidden sm:table-cell" :
  hidden === "lg" ? "hidden lg:table-cell" : ""

const getActiveClass = (isActive: boolean) =>
  isActive ? "bg-accent" : ""

const getSubTriggerClass = (hasActiveFilter: boolean) =>
  `cursor-pointer ${hasActiveFilter ? "bg-accent" : ""}`

export function DataTable<T>({
  data,
  columns,
  searchPlaceholder = "Search...",
  searchValue,
  onSearchChange,
  searchDebounceMs = 0,
  filters,
  sort,
  pagination,
  form,
  toolbarButtons = [],
  bulkActions = [],
  selectedIds = new Set(),
  selectionStatus,
  onSelectAll,
  onSelectOne,
  onClearSelection,
  onRowClick,
  getItemId,
  emptyState,
  minHeight = "550px",
  isFetching,
}: DataTableProps<T>) {
  const [searchInputValue, setSearchInputValue] = useState(searchValue)
  const hasSelection = onSelectAll && onSelectOne
  const isAllSelected = data.length > 0 && selectedIds.size === data.length
  const hasActiveFilter = filters?.some(f => f.value !== null) || false

  const totalPages = Math.max(1, Math.ceil(pagination.totalItems / pagination.pageSize))
  const safePage = Math.min(pagination.currentPage, totalPages)

  const scrollRef = useRef<HTMLDivElement>(null)
  const headerRef = useRef<HTMLTableSectionElement>(null)
  const firstRowRef = useRef<HTMLTableRowElement>(null)
  const { autoPageSize, onPageSizeChange, pageSize: currentPageSize } = pagination

  useEffect(() => {
    if (!autoPageSize) return
    const scrollEl = scrollRef.current
    if (!scrollEl) return

    let lastReported = currentPageSize
    const compute = () => {
      const viewport = scrollEl.clientHeight
      const header = headerRef.current?.getBoundingClientRect().height ?? 0
      const row = firstRowRef.current?.getBoundingClientRect().height ?? 0
      if (viewport <= 0) return
      const rowHeight = row > 0 ? row : 40
      const available = Math.max(0, viewport - header)
      const next = Math.max(1, Math.floor(available / rowHeight))
      if (next !== lastReported) {
        lastReported = next
        onPageSizeChange(next)
      }
    }

    compute()
    const ro = new ResizeObserver(compute)
    ro.observe(scrollEl)
    if (headerRef.current) ro.observe(headerRef.current)
    if (firstRowRef.current) ro.observe(firstRowRef.current)
    return () => ro.disconnect()
  }, [autoPageSize, onPageSizeChange, currentPageSize, data.length])

  useEffect(() => {
    setSearchInputValue(searchValue)
  }, [searchValue])

  useEffect(() => {
    if (searchInputValue === searchValue) return

    if (searchDebounceMs <= 0) {
      onSearchChange(searchInputValue)
      return
    }

    const timer = setTimeout(() => onSearchChange(searchInputValue), searchDebounceMs)
    return () => clearTimeout(timer)
  }, [searchDebounceMs, searchInputValue, searchValue, onSearchChange])

  const startIdx = pagination.totalItems === 0 ? 0 : (safePage - 1) * pagination.pageSize
  const endIdx = Math.min(startIdx + pagination.pageSize, pagination.totalItems)

  const renderFilters = () => {
    if (!filters || filters.length === 0) return null

    return (
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            className={`h-7 w-7 sm:h-8 sm:w-8 p-0 cursor-pointer transition-colors relative focus-visible:ring-0 focus-visible:ring-offset-0 ${
              hasActiveFilter
                ? "bg-accent"
                : "hover:bg-muted/60 hover:text-muted-foreground"
            }`}
          >
            <ListFilter className="h-3 w-3 sm:h-3.5 sm:w-3.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-40">
          <DropdownMenuItem
            onClick={() => { filters.forEach(f => f.onChange("")); clearSelection() }}
            className={`cursor-pointer ${getActiveClass(!hasActiveFilter)}`}
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
                  className={`cursor-pointer ${getActiveClass(isActive)}`}
                >
                  <span className="flex-1 truncate">{filter.label}</span>
                  <span className="text-xs text-muted-foreground ml-2">{filter.count ?? 0}</span>
                </DropdownMenuItem>
              )
            }
            return (
              <DropdownMenuSub key={idx}>
                <DropdownMenuSubTrigger className={getSubTriggerClass(filter.value !== null)}>
                  <span className="flex-1">{filter.label}</span>
                </DropdownMenuSubTrigger>
                <DropdownMenuPortal>
                  <DropdownMenuSubContent className="w-40">
                    {filter.options.map((option) => {
                      const isActive = filter.value === option.value
                      return (
                        <DropdownMenuItem
                          key={option.value}
                          onClick={() => { filter.onChange(isActive ? "" : option.value); clearSelection() }}
                          className={`cursor-pointer ${getActiveClass(isActive)}`}
                        >
                          <span className="flex-1 truncate">{option.label}</span>
                          <span className="text-xs text-muted-foreground ml-2">
                            {option.count ?? 0}
                          </span>
                        </DropdownMenuItem>
                      )
                    })}
                  </DropdownMenuSubContent>
                </DropdownMenuPortal>
              </DropdownMenuSub>
            )
          })}
        </DropdownMenuContent>
      </DropdownMenu>
    )
  }

  const clearSelection = () => {
    if (selectedIds.size > 0) onClearSelection?.()
  }

  const handleSort = (columnKey: string) => {
    if (!sort) return
    clearSelection()
    if (sort.field !== columnKey) return sort.onChange(columnKey, "asc")
    sort.onChange(columnKey, sort.order === "asc" ? "desc" : "asc")
  }

  return (
    <div className="w-full">
      <div className="flex items-center gap-1 sm:gap-2 p-2 sm:p-3 border bg-card text-card-foreground shadow-sm rounded-t-lg select-none">
        {form?.show ? (
          <>
            <span className="text-sm font-semibold flex-1 pl-2">{form.title}</span>
            <Button
              variant="ghost"
              size="sm"
              onClick={form.onClose}
              className="h-7 w-7 sm:h-8 sm:w-8 p-0 cursor-pointer transition-colors hover:bg-muted/60 hover:text-muted-foreground focus-visible:ring-0 focus-visible:ring-offset-0"
            >
              <X className="h-3 w-3 sm:h-3.5 sm:w-3.5" />
            </Button>
          </>
        ) : (
          <>
            <div className="relative flex-1 min-w-0">
              <Search className="absolute left-2 top-1.5 sm:top-2 h-3 w-3 sm:h-3.5 sm:w-3.5 text-muted-foreground" />
              <Input
                placeholder={searchPlaceholder}
                value={searchInputValue}
                onChange={(e) => { setSearchInputValue(e.target.value); clearSelection() }}
                className="pl-6 sm:pl-7 h-7 sm:h-8 text-xs w-full"
              />
            </div>
            <div className="hidden sm:flex sm:flex-1" />
            <div className="flex items-center gap-0.5 sm:gap-1">
              {selectedIds.size > 0 ? (
                <>
                  <span
                    className={`text-xs px-2 ${!selectionStatus?.variant ? "text-muted-foreground" : ""}`}
                    style={{
                      color: selectionStatus?.variant === "success"
                        ? "var(--success-fg)"
                        : selectionStatus?.variant === "loading"
                          ? "var(--warning-fg)"
                          : undefined
                    }}
                  >
                    {selectionStatus?.text || `${selectedIds.size} of ${pagination.totalItems} Selected`}
                  </span>
                  {bulkActions.map((action, idx) => (
                    <Button
                      key={idx}
                      variant="ghost"
                      size="sm"
                      onClick={() => action.onClick(selectedIds)}
                      disabled={selectionStatus?.variant === "loading" || selectionStatus?.variant === "success"}
                      className="h-7 w-7 sm:h-8 sm:w-8 p-0 cursor-pointer transition-colors hover:bg-muted/60 hover:text-muted-foreground focus-visible:ring-0 focus-visible:ring-offset-0 disabled:opacity-50 disabled:cursor-not-allowed"
                      aria-label={action.ariaLabel}
                    >
                      {action.icon}
                    </Button>
                  ))}
                </>
              ) : (
                <>
                  {renderFilters()}
                  {toolbarButtons.map((button, idx) => (
                    <Button
                      key={idx}
                      variant={button.variant || "ghost"}
                      size="sm"
                      onClick={button.onClick}
                      disabled={button.disabled}
                      className={button.className || "h-7 w-7 sm:h-8 sm:w-8 p-0 cursor-pointer transition-colors hover:bg-muted/60 hover:text-muted-foreground focus-visible:ring-0 focus-visible:ring-offset-0"}
                      aria-label={button.ariaLabel}
                    >
                      {button.icon}
                    </Button>
                  ))}
                </>
              )}
            </div>
          </>
        )}
      </div>
      <Card className="relative w-full rounded-t-none border-t-0 p-0">
        <LoadingBar active={!!isFetching} />
        <div className="flex flex-col" style={{ minHeight }}>
          {form?.show ? (
            <div className="flex-1">
              {form.render()}
            </div>
          ) : data.length === 0 && emptyState ? (
            <div className="flex-1 flex flex-col items-center justify-center gap-4">
              {emptyState.icon}
              <p className={`text-sm text-muted-foreground ${isFetching ? "shimmer-text" : ""}`}>
                {emptyState.message}
              </p>
              {emptyState.actionLabel && emptyState.onAction && (
                <Button variant="outline" onClick={emptyState.onAction} className="cursor-pointer">
                  {emptyState.actionLabel}
                </Button>
              )}
            </div>
          ) : (
            <div ref={scrollRef} className="flex-1 overflow-auto">
              <Table>
                <TableHeader ref={headerRef} className="select-none">
                  <TableRow>
                    {hasSelection && (
                      <TableHead className="w-8 sm:w-9 pl-2 pr-0 sm:pl-3">
                        <Checkbox
                          checked={isAllSelected}
                          onCheckedChange={onSelectAll}
                          className="cursor-pointer"
                          aria-label="Select all"
                        />
                      </TableHead>
                    )}
                    {columns.map((column) => (
                      <TableHead
                        key={column.key}
                        className={`${column.width ? `w-[${column.width}]` : ""} ${hiddenClass(column.hidden)} ${column.sortable ? "cursor-pointer" : ""} ${column.headerClassName || ""}`}
                        onClick={() => column.sortable && handleSort(column.key)}
                      >
                        <div className="flex items-center gap-1">
                          <span>{column.header}</span>
                          {column.sortable && (
                            sort?.field === column.key ? (
                              sort.order === "asc" ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />
                            ) : (
                              <span className="w-3.5" />
                            )
                          )}
                        </div>
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.map((item, idx) => {
                    const itemId = getItemId(item)
                    const isGenerating = (item as Record<string, unknown>).isGenerating as boolean | undefined || false
                    const isClickable = onRowClick && !isGenerating

                    return (
                      <TableRow
                        key={itemId}
                        ref={idx === 0 ? firstRowRef : null}
                        className={`${isGenerating ? "opacity-70 pointer-events-none select-none" : isClickable ? "cursor-pointer select-none" : "select-none"}`}
                        onClick={isClickable ? () => onRowClick(item) : undefined}
                      >
                        {hasSelection && (
                          <TableCell className="pl-2 pr-0 sm:pl-3">
                            <Checkbox
                              checked={selectedIds.has(itemId)}
                              onCheckedChange={() => onSelectOne?.(itemId)}
                              onClick={(e) => e.stopPropagation()}
                              className="cursor-pointer"
                              aria-label={`Select item ${itemId}`}
                              disabled={isGenerating}
                            />
                          </TableCell>
                        )}
                        {columns.map((column) => (
                          <TableCell
                            key={`${itemId}-${column.key}`}
                            className={`${hiddenClass(column.hidden)} ${column.className || ""}`}
                          >
                            {column.render(item, isGenerating)}
                          </TableCell>
                        ))}
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          )}
          {!form?.show && (
            <div className="flex items-center justify-between p-2 sm:p-3 border-t text-xs text-muted-foreground select-none">
              <span>
                {pagination.totalItems === 0 ? "No results" : `Showing ${startIdx + 1}-${endIdx} of ${pagination.totalItems}`}
              </span>
              <div className="flex items-center gap-8">
                {!autoPageSize && (
                  <div className="hidden items-center gap-2 lg:flex">
                    <Label htmlFor="rows-per-page" className="text-xs font-medium">
                      Rows per page
                    </Label>
                    <Select
                      value={`${pagination.pageSize}`}
                      onValueChange={(value) => { pagination.onPageSizeChange(Number(value)); clearSelection() }}
                    >
                      <SelectTrigger size="sm" className="h-6 w-[70px] text-xs cursor-pointer" id="rows-per-page">
                        <SelectValue placeholder={pagination.pageSize} />
                      </SelectTrigger>
                      <SelectContent side="top">
                        {pagination.pageSizeOptions.map((size) => (
                          <SelectItem key={size} value={`${size}`} className="cursor-pointer">
                            {size}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}
                <div className="flex items-center justify-center text-xs font-medium">
                  Page {safePage} of {totalPages}
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    className="hidden h-8 w-8 p-0 cursor-pointer lg:flex"
                    size="icon"
                    onClick={() => { pagination.onPageChange(1); clearSelection() }}
                    disabled={safePage === 1}
                  >
                    <span className="sr-only">Go to first page</span>
                    <ChevronsLeft className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    className="h-6 w-6 p-0 cursor-pointer"
                    size="icon"
                    onClick={() => { pagination.onPageChange(Math.max(1, safePage - 1)); clearSelection() }}
                    disabled={safePage === 1}
                  >
                    <span className="sr-only">Go to previous page</span>
                    <ChevronLeft className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="outline"
                    className="h-6 w-6 p-0 cursor-pointer"
                    size="icon"
                    onClick={() => { pagination.onPageChange(Math.min(totalPages, safePage + 1)); clearSelection() }}
                    disabled={safePage === totalPages}
                  >
                    <span className="sr-only">Go to next page</span>
                    <ChevronRight className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="outline"
                    className="hidden h-8 w-8 p-0 cursor-pointer lg:flex"
                    size="icon"
                    onClick={() => { pagination.onPageChange(totalPages); clearSelection() }}
                    disabled={safePage === totalPages}
                  >
                    <span className="sr-only">Go to last page</span>
                    <ChevronsRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>
      </Card>
    </div>
  )
}
