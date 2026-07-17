'use client'

import { cn } from '@/lib/utils'
import { ChevronUp, ChevronDown } from 'lucide-react'
import { ReactNode } from 'react'

export interface TableColumn<T> {
  key: string
  title: string
  dataIndex?: keyof T
  width?: string
  align?: 'left' | 'center' | 'right'
  sortable?: boolean
  render?: (record: T, index: number) => ReactNode
}

interface TableProps<T> {
  columns: TableColumn<T>[]
  dataSource: T[]
  loading?: boolean
  rowKey: keyof T | ((record: T) => string)
  onRowClick?: (record: T) => void
  sortField?: string
  sortOrder?: 'asc' | 'desc'
  onSort?: (field: string) => void
  emptyText?: string
  minWidth?: number
}

function Table<T extends Record<string, any>>({
  columns,
  dataSource,
  loading,
  rowKey,
  onRowClick,
  sortField,
  sortOrder,
  onSort,
  emptyText = '暂无数据',
  minWidth,
}: TableProps<T>) {
  const data = dataSource || []

  const getRowKey = (record: T): string => {
    if (typeof rowKey === 'function') {
      return rowKey(record)
    }
    return String(record[rowKey])
  }

  const getCellValue = (record: T, column: TableColumn<T>): ReactNode => {
    if (column.render) {
      return column.render(record, data.indexOf(record))
    }
    if (column.dataIndex) {
      const value = record[column.dataIndex]
      return value as ReactNode
    }
    return null
  }

  return (
    <div className="w-full overflow-x-auto">
      <table
        className="w-full border-collapse"
        style={minWidth ? { minWidth: `${minWidth}px` } : undefined}
      >
        <thead>
          <tr className="bg-gray-50 border-b border-gray-200">
            {columns.map((column) => (
              <th
                key={column.key}
                title={column.title}
                className={cn(
                  'px-4 py-3 text-left text-sm font-semibold text-gray-600',
                  'whitespace-nowrap',
                  column.align === 'center' && 'text-center',
                  column.align === 'right' && 'text-right',
                  column.sortable && 'cursor-pointer select-none hover:bg-gray-100'
                )}
                style={{ width: column.width }}
                onClick={() => column.sortable && onSort?.(column.key)}
              >
                <div className={cn('flex items-center gap-1 min-w-0', column.align === 'center' && 'justify-center', column.align === 'right' && 'justify-end')}>
                  <span className="whitespace-nowrap truncate" title={column.title}>{column.title}</span>
                  {column.sortable && (
                    <span className="flex flex-col flex-shrink-0">
                      <ChevronUp className={cn('w-3 h-3 -mb-1', sortField === column.key && sortOrder === 'asc' ? 'text-primary-600' : 'text-gray-300')} />
                      <ChevronDown className={cn('w-3 h-3', sortField === column.key && sortOrder === 'desc' ? 'text-primary-600' : 'text-gray-300')} />
                    </span>
                  )}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr>
              <td colSpan={columns.length} className="px-4 py-12 text-center text-gray-500">
                <div className="flex items-center justify-center gap-2">
                  <div className="w-5 h-5 border-2 border-primary-600 border-t-transparent rounded-full animate-spin" />
                  加载中...
                </div>
              </td>
            </tr>
          ) : data.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-4 py-12 text-center text-gray-500">
                {emptyText}
              </td>
            </tr>
          ) : (
            data.map((record) => (
              <tr
                key={getRowKey(record)}
                className={cn(
                  'border-b border-gray-100 transition-colors',
                  onRowClick && 'cursor-pointer hover:bg-blue-50'
                )}
                onClick={() => onRowClick?.(record)}
              >
                {columns.map((column) => (
                  <td
                    key={`${getRowKey(record)}-${column.key}`}
                    className={cn(
                      'px-4 py-4 text-sm text-gray-700',
                      column.align === 'center' && 'text-center',
                      column.align === 'right' && 'text-right'
                    )}
                  >
                    {getCellValue(record, column)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

export default Table
