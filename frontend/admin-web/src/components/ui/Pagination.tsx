'use client'

import { cn } from '@/lib/utils'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import Button from './Button'

interface PaginationProps {
  current: number
  pageSize: number
  total: number
  onChange: (page: number) => void
  onPageSizeChange?: (pageSize: number) => void
  pageSizeOptions?: number[]
  showTotal?: boolean
  showSizeChanger?: boolean
}

const Pagination = ({
  current,
  pageSize,
  total,
  onChange,
  onPageSizeChange,
  pageSizeOptions = [10, 20, 50, 100],
  showTotal = true,
  showSizeChanger = true,
}: PaginationProps) => {
  const totalPages = Math.ceil(total / pageSize) || 1
  const startItem = (current - 1) * pageSize + 1
  const endItem = Math.min(current * pageSize, total)

  const getPageNumbers = (): (number | string)[] => {
    const pages: (number | string)[] = []
    
    if (totalPages <= 7) {
      for (let i = 1; i <= totalPages; i++) {
        pages.push(i)
      }
    } else {
      if (current <= 3) {
        pages.push(1, 2, 3, 4, '...', totalPages)
      } else if (current >= totalPages - 2) {
        pages.push(1, '...', totalPages - 3, totalPages - 2, totalPages - 1, totalPages)
      } else {
        pages.push(1, '...', current - 1, current, current + 1, '...', totalPages)
      }
    }
    
    return pages
  }

  return (
    <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200">
      {/* 左侧：总数信息 */}
      {showTotal && (
        <div className="text-sm text-gray-600">
          共 <span className="font-medium">{total}</span> 条记录
          {total > 0 && (
            <span className="ml-1">
              (第 {startItem}-{endItem} 条)
            </span>
          )}
        </div>
      )}

      {/* 右侧：分页控制 */}
      <div className="flex items-center gap-4">
        {/* 每页条数选择 */}
        {showSizeChanger && onPageSizeChange && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-600">每页</span>
            <select
              value={pageSize}
              onChange={(e) => onPageSizeChange(Number(e.target.value))}
              className="h-8 px-2 text-sm border border-gray-300 rounded focus:outline-none focus:border-primary-500"
            >
              {pageSizeOptions.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
            <span className="text-sm text-gray-600">条</span>
          </div>
        )}

        {/* 页码按钮 */}
        <div className="flex items-center gap-1">
          <button
            onClick={() => onChange(current - 1)}
            disabled={current <= 1}
            className={cn(
              'p-1.5 rounded border transition-colors',
              current <= 1
                ? 'border-gray-200 text-gray-300 cursor-not-allowed'
                : 'border-gray-300 text-gray-600 hover:bg-gray-50 hover:border-gray-400'
            )}
          >
            <ChevronLeft className="w-4 h-4" />
          </button>

          {getPageNumbers().map((page, index) => (
            <button
              key={index}
              onClick={() => typeof page === 'number' && onChange(page)}
              disabled={page === '...'}
              className={cn(
                'min-w-[32px] h-8 px-2 text-sm rounded border transition-colors',
                page === current
                  ? 'bg-primary-600 text-white border-primary-600'
                  : page === '...'
                  ? 'border-transparent text-gray-400 cursor-default'
                  : 'border-gray-300 text-gray-600 hover:bg-gray-50 hover:border-gray-400'
              )}
            >
              {page}
            </button>
          ))}

          <button
            onClick={() => onChange(current + 1)}
            disabled={current >= totalPages}
            className={cn(
              'p-1.5 rounded border transition-colors',
              current >= totalPages
                ? 'border-gray-200 text-gray-300 cursor-not-allowed'
                : 'border-gray-300 text-gray-600 hover:bg-gray-50 hover:border-gray-400'
            )}
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  )
}

export default Pagination
