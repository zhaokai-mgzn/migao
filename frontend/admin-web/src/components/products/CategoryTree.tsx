'use client'

import { useState } from 'react'
import { ChevronRight, ChevronDown, Folder, FolderOpen } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Category } from '@/types'

interface CategoryTreeProps {
  categories: Category[]
  selectedId?: string
  onSelect?: (category: Category) => void
  onEdit?: (category: Category) => void
  onDelete?: (category: Category) => void
  showActions?: boolean
}

interface TreeNodeProps {
  category: Category
  level: number
  selectedId?: string
  onSelect?: (category: Category) => void
  onEdit?: (category: Category) => void
  onDelete?: (category: Category) => void
  showActions?: boolean
}

function TreeNode({ category, level, selectedId, onSelect, onEdit, onDelete, showActions }: TreeNodeProps) {
  const [expanded, setExpanded] = useState(true)
  const hasChildren = category.children && category.children.length > 0
  const isSelected = selectedId === category.id

  return (
    <div>
      <div
        className={cn(
          'flex items-center gap-1.5 px-2 py-1.5 rounded-md cursor-pointer group transition-colors',
          isSelected ? 'bg-primary-50 text-primary-700' : 'hover:bg-gray-50 text-gray-700'
        )}
        style={{ paddingLeft: `${level * 20 + 8}px` }}
        onClick={() => onSelect?.(category)}
      >
        {/* Expand/collapse toggle */}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            setExpanded(!expanded)
          }}
          className={cn('p-0.5 rounded hover:bg-gray-200 transition-colors', !hasChildren && 'invisible')}
        >
          {expanded ? (
            <ChevronDown className="w-3.5 h-3.5" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5" />
          )}
        </button>

        {/* Folder icon */}
        {expanded && hasChildren ? (
          <FolderOpen className="w-4 h-4 text-amber-500 flex-shrink-0" />
        ) : (
          <Folder className="w-4 h-4 text-amber-500 flex-shrink-0" />
        )}

        {/* Name */}
        <span className="text-sm truncate flex-1">{category.name}</span>

        {/* Actions */}
        {showActions && (
          <div className="hidden group-hover:flex items-center gap-1">
            {onEdit && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onEdit(category)
                }}
                className="text-xs text-primary-600 hover:text-primary-700 px-1.5 py-0.5 rounded hover:bg-primary-50"
              >
                编辑
              </button>
            )}
            {onDelete && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onDelete(category)
                }}
                className="text-xs text-red-600 hover:text-red-700 px-1.5 py-0.5 rounded hover:bg-red-50"
              >
                删除
              </button>
            )}
          </div>
        )}
      </div>

      {/* Children */}
      {hasChildren && expanded && (
        <div>
          {category.children!.map((child) => (
            <TreeNode
              key={child.id}
              category={child}
              level={level + 1}
              selectedId={selectedId}
              onSelect={onSelect}
              onEdit={onEdit}
              onDelete={onDelete}
              showActions={showActions}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export default function CategoryTree({
  categories,
  selectedId,
  onSelect,
  onEdit,
  onDelete,
  showActions = false,
}: CategoryTreeProps) {
  if (categories.length === 0) {
    return (
      <div className="py-8 text-center text-sm text-gray-500">
        暂无分类数据
      </div>
    )
  }

  return (
    <div className="py-1">
      {categories.map((category) => (
        <TreeNode
          key={category.id}
          category={category}
          level={0}
          selectedId={selectedId}
          onSelect={onSelect}
          onEdit={onEdit}
          onDelete={onDelete}
          showActions={showActions}
        />
      ))}
    </div>
  )
}
