'use client'

import { Folder, Pencil, Trash2, ChevronUp, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Category } from '@/types'

interface CategoryTreeProps {
  categories: Category[]
  selectedId?: string
  onSelect?: (category: Category) => void
  onEdit?: (category: Category) => void
  onDelete?: (category: Category) => void
  /** 上移一行（首行禁用） */
  onMoveUp?: (category: Category) => void
  /** 下移一行（末行禁用） */
  onMoveDown?: (category: Category) => void
}

/**
 * 分类列表（扁平结构，issue #2905）
 *
 * - 无父子分类：平铺渲染全部分类，无折叠/展开、无「添加子分类」
 * - 排序方式：上移/下移按钮（首行禁上移、末行禁下移），不再使用排序数字输入
 */
export default function CategoryTree({
  categories,
  selectedId,
  onSelect,
  onEdit,
  onDelete,
  onMoveUp,
  onMoveDown,
}: CategoryTreeProps) {
  if (categories.length === 0) {
    return (
      <div className="py-8 text-center text-sm text-neutral-500">
        管理商品分类，支持对分类进行新增、编辑、删除和排序
      </div>
    )
  }

  return (
    <div className="py-1">
      {categories.map((category, index) => {
        const isSelected = selectedId === category.id
        const isFirst = index === 0
        const isLast = index === categories.length - 1
        return (
          <div
            key={category.id}
            className={cn(
              'flex items-center gap-1.5 px-2 py-1.5 rounded-md cursor-pointer group transition-colors',
              isSelected ? 'bg-primary-50 text-primary-700' : 'hover:bg-neutral-50 text-neutral-700'
            )}
            onClick={() => onSelect?.(category)}
          >
            {/* Folder icon */}
            <Folder className="w-4 h-4 text-amber-500 flex-shrink-0" />

            {/* Name */}
            <span className="text-sm truncate flex-1">{category.name}</span>

            {/* Move + Actions */}
            <div className="flex items-center gap-0.5">
              {onMoveUp && (
                <button
                  type="button"
                  disabled={isFirst}
                  onClick={(e) => {
                    e.stopPropagation()
                    onMoveUp(category)
                  }}
                  className="p-1 rounded text-neutral-400 hover:text-primary-600 hover:bg-primary-50 disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-neutral-400"
                  title={isFirst ? '已在最前' : '上移'}
                >
                  <ChevronUp className="w-3.5 h-3.5" />
                </button>
              )}
              {onMoveDown && (
                <button
                  type="button"
                  disabled={isLast}
                  onClick={(e) => {
                    e.stopPropagation()
                    onMoveDown(category)
                  }}
                  className="p-1 rounded text-neutral-400 hover:text-primary-600 hover:bg-primary-50 disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-neutral-400"
                  title={isLast ? '已在最后' : '下移'}
                >
                  <ChevronDown className="w-3.5 h-3.5" />
                </button>
              )}
              {onEdit && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    onEdit(category)
                  }}
                  className="p-1 rounded text-neutral-400 hover:text-primary-600 hover:bg-primary-50"
                  title="编辑"
                >
                  <Pencil className="w-3.5 h-3.5" />
                </button>
              )}
              {onDelete && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    onDelete(category)
                  }}
                  className="p-1 rounded text-neutral-400 hover:text-red-600 hover:bg-red-50"
                  title="删除"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}