import type { ReactNode } from "react"
import type { FilterConfig, ToolbarButton, BulkAction, SelectionStatus, EmptyStateConfig } from "./data-table-types"

export interface DataListPaginationConfig {
  currentPage: number
  pageSize: number
  totalItems: number
  onPageChange: (page: number) => void
  /** When provided, DataList measures the list viewport and calls back with
   *  the number of rows that fit without overflow. Caller updates pageSize
   *  state so the list paginates to fill-but-not-overflow the visible area. */
  onPageSizeChange?: (size: number) => void
}

export interface DataListProps<T> {
  data: T[]
  getItemId: (item: T) => string
  renderItem: (item: T) => ReactNode
  searchPlaceholder?: string
  /** Omit `searchValue`/`onSearchChange` to hide the search input entirely. */
  searchValue?: string
  onSearchChange?: (value: string) => void
  searchDebounceMs?: number
  filters?: FilterConfig[]
  pagination: DataListPaginationConfig
  selectedIds?: Set<string>
  onSelectAll?: () => void
  onSelectOne?: (id: string) => void
  onClearSelection?: () => void
  activeId?: string
  toolbarButtons?: ToolbarButton[]
  bulkActions?: BulkAction[]
  selectionStatus?: SelectionStatus
  onItemClick?: (item: T) => void
  emptyState?: EmptyStateConfig
  isFetching?: boolean
}

export type { FilterConfig, ToolbarButton, BulkAction, SelectionStatus, EmptyStateConfig }
