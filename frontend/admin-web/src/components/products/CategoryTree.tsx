'use client'

import { useState } from 'react'
import { ChevronRight, ChevronDown, Folder, FolderOpen, Plus, Pencil, Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Category } from '@/types'

interface CategoryTreeProps {
  categories: Category[]
  selectedId?: string
  onSelect?: (category: Category) => void
  onEdit?: (category: Category) => void
  onDelete?: (category: Category) => void
  onAddChild?: (parent: Category) => void
}

interface TreeNodeProps {
  category: Category
  level: number
  selectedId?: string
  onSelect?: (category: Category) => void
  onEdit?: (category: Category) => void
  onDelete?: (category: Category) => void
  onAddChild?: (parent: Category) => void
}

function TreeNode({ category, level, selectedId, onSelect, onEdit, onDelete, onAddChild }: TreeNodeProps) {
  const [expanded, setExpanded] = useState(true)
  const hasChildren = category.children && category.children.length > 0
  const isSelected = selectedId === category.id
  const canHaveChildren = level === 0  // 仅一级分类可添加子分类（限制最多二级）

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

        {/* Actions — 始终可见 */}
        <div className="flex items-center gap-0.5">
          {canHaveChildren && onAddChild && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onAddChild(category) }}
              className="p-1 rounded text-gray-400 hover:text-primary-600 hover:bg-primary-50"
              title="添加子分类"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
          )}
          {onEdit && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onEdit(category) }}
              className="p-1 rounded text-gray-400 hover:text-primary-600 hover:bg-primary-50"
              title="编辑"
            >
              <Pencil className="w-3.5 h-3.5" />
            </button>
          )}
          {onDelete && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onDelete(category) }}
              className="p-1 rounded text-gray-400 hover:text-red-600 hover:bg-red-50"
              title="删除"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
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
              onAddChild={onAddChild}
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
  onAddChild,
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
          onAddChild={onAddChild}
        />
      ))}
    </div>
  )
}
