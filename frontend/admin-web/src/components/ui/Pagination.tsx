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
  /**
   * `total` 是否来自**成功**的读响应（issue #6703）。
   *
   * 读接口失败时调用方的 `total` 还停在初值 0 ⇒ 这一行会把「读不到」印成
   * 「共 0 条记录」—— 与 #6691「读面故障不得画成空态」同族的**事实性断言**：
   * 商家看一眼 toast 回到屏幕，只看到零，会读成「今天没有订单 / 没有客户」。
   * 传 `false` ⇒ 计数位印 `—`（不是 0、也不是空），与调用方的失败面同源。
   *
   * 默认 `true`：**不改**既有正常路径的显示（其余调用方零改动）。
   */
  totalReliable?: boolean
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
  totalReliable = true,
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
        <div className="text-sm text-gray-600" data-testid="pagination-total">
          共 <span className="font-medium">{totalReliable ? total : '—'}</span> 条记录
          {totalReliable && total > 0 && (
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
              aria-label="每页条数"
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
