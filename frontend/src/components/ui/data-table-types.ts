import type { ReactNode } from "react"

export interface DataTableColumn<T> {
  key: string
  header: string
  width?: string
  hidden?: boolean | "sm" | "md" | "lg"
  sortable?: boolean
  className?: string
  headerClassName?: string
  render: (item: T, isGenerating: boolean) => ReactNode
}

export interface FilterOption {
  value: string
  label: string
  count?: number
}

interface SubmenuFilterConfig {
  type: "submenu" | "dropdown"
  label: string
  value: string | null
  options: FilterOption[]
  onChange: (value: string) => void
}

interface ToggleFilterConfig {
  type: "toggle"
  label: string
  value: string | null
  count?: number
  onChange: (value: string) => void
}

export type FilterConfig = SubmenuFilterConfig | ToggleFilterConfig

export interface SortConfig {
  field: string | null
  order: "asc" | "desc"
  onChange: (field: string | null, order: "asc" | "desc") => void
}

export interface PaginationConfig {
  currentPage: number
  pageSize: number
  totalItems: number
  pageSizeOptions: number[]
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
  /** When true, DataTable measures the scroll viewport and reports the number
   *  of rows that fit via onPageSizeChange. The manual rows-per-page selector
   *  is hidden. */
  autoPageSize?: boolean
}

export interface ToolbarButton {
  icon: ReactNode
  onClick: () => void
  disabled?: boolean
  ariaLabel: string
  variant?: "ghost" | "outline" | "default"
  className?: string
}

export interface BulkAction {
  icon: ReactNode
  onClick: (selectedIds: Set<string>) => void
  ariaLabel: string
}

export interface FormConfig {
  show: boolean
  title: string
  onClose: () => void
  render: () => ReactNode
}

export interface SelectionStatus {
  text: string
  variant?: "default" | "success" | "loading"
}

export interface EmptyStateConfig {
  icon?: ReactNode
  message: string
  actionLabel?: string
  onAction?: () => void
}

export interface DataTableProps<T> {
  data: T[]
  columns: DataTableColumn<T>[]
  searchPlaceholder?: string
  searchValue: string
  onSearchChange: (value: string) => void
  searchDebounceMs?: number
  filters?: FilterConfig[]
  sort?: SortConfig
  pagination: PaginationConfig
  form?: FormConfig
  toolbarButtons?: ToolbarButton[]
  bulkActions?: BulkAction[]
  selectedIds?: Set<string>
  selectionStatus?: SelectionStatus
  onSelectAll?: () => void
  onSelectOne?: (id: string) => void
  onClearSelection?: () => void
  onRowClick?: (item: T) => void
  getItemId: (item: T) => string
  emptyState?: EmptyStateConfig
  minHeight?: string
  isFetching?: boolean
}
