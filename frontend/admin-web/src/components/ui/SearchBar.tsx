'use client'

import { useState } from 'react'
import { Search, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import Button from './Button'
import Input from './Input'
import Select from './Select'

export interface SearchField {
  key: string
  label: string
  type: 'input' | 'select'
  placeholder?: string
  options?: { value: string; label: string }[]
}

interface SearchBarProps {
  fields: SearchField[]
  onSearch: (values: Record<string, string>) => void
  onReset?: () => void
  loading?: boolean
  className?: string
}

/**
 * 单向筛选条（字段 + 查询 / 重置）—— **自带筛选状态**的旧形态共享件。
 *
 * ## 与 `SearchPanel` 的关系（issue #7007）
 *
 * 本仓的「筛选区」有两种原语，各有**明确适用面**，不要混用：
 *
 * | 原语 | 状态 | 版式 | 适用 |
 * |---|---|---|---|
 * | `frontend/admin-web/src/components/ui/SearchPanel.tsx` | **无状态**（`fields[].control` 由页面渲染） | 标签左置 + 单一响应式 grid（行行对齐 / 按钮独占一行） | **列表页**：页面已自己持有筛选 state（防抖 / URL 同步 / 首屏默认区间） |
 * | 本文件 `SearchBar` | **有状态**（原语内 `useState`） | 标签顶置 + `flex flex-wrap` | 轻量场景：页面不想为一次筛选各写一遍 state / 查询按钮 |
 *
 * ## 本次（issue #7007）改了什么 / 没改什么
 *
 * **改**：底色 `bg-gray-50` → **`bg-neutral-50`**。
 * `gray` **不在本仓 token 里**（`frontend/admin-web/tailwind.config.ts` 的暖色族是
 * `primary` / `accent` / `neutral`）⇒ 它落回 Tailwind 默认**冷灰**（`gray-50 = #f9fafb` / `gray-200` /
 * `gray-500`），在全站暖亚麻底（`neutral-50 = #faf7f2`）上是一块**另一个产品的颜色**。
 *
 * **没改**：字段渲染方式、`useState` 形状、`onSearch(values)` 契约、`data-testid="search-area"`
 * —— 调用方（`app/(dashboard)/customers/page.tsx`、`app/(dashboard)/knowledge/page.tsx`）
 * 零改动，行为逐值不变。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 本原语的**版式没有被本轮统一**（仍是 `flex-wrap` + `min-w-[200px]`）：把它改成 `SearchPanel`
 *   的 grid 需要把筛选 state 上提到页面（行为改造，不是视觉统一）⇒ 记为**有意不做**，
 *   重启条件 = 这两页各自需要「行行对齐」时，改为直接用 `SearchPanel`；
 * - 判据：本文件不得出现 Tailwind 默认冷色族（`gray-*` / `blue-*` / `indigo-*` …）——
 *   `frontend/admin-web/tests/unit/warm-token-palette-guard.test.ts` 判红。
 */
const SearchBar = ({ fields, onSearch, onReset, loading, className }: SearchBarProps) => {
  const [values, setValues] = useState<Record<string, string>>({})

  const handleSearch = () => {
    onSearch(values)
  }

  const handleReset = () => {
    setValues({})
    onReset?.()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSearch()
    }
  }

  return (
    <div className={cn('bg-neutral-50 p-4 rounded-lg', className)} data-testid="search-area">
      <div className="flex flex-wrap items-end gap-4">
        {fields.map((field) => (
          // 字段**参与伸缩**（issue #7397）：旧版是定宽 `min-w-[200px]` 且不 grow ⇒
          // 占位文案比 200px 长就必然被截断（知识库「搜索标题 / 关键词 / 常见问法 / 回答内容」），
          // 而按钮被 `ml-auto` 推到最右、中间留下整片空白。`flex-1` 让它吃掉那段空白，
          // `basis-[22rem]` 只定**换行前的初始宽度**（约等于最长占位文案 + 内边距），
          // 窄视口仍会正常换行（不写死最小宽度，免得在小屏撑出横向滚动）。
          <div
            key={field.key}
            data-testid={`search-field-${field.key}`}
            className="flex-1 basis-[22rem] min-w-0"
          >
            {field.type === 'input' ? (
              <Input
                label={field.label}
                placeholder={field.placeholder}
                value={values[field.key] || ''}
                onChange={(e) => setValues({ ...values, [field.key]: e.target.value })}
                onKeyDown={handleKeyDown}
              />
            ) : (
              <Select
                label={field.label}
                placeholder={field.placeholder || '请选择'}
                options={field.options || []}
                value={values[field.key] || ''}
                onChange={(e) => setValues({ ...values, [field.key]: e.target.value })}
              />
            )}
          </div>
        ))}

        <div className="flex items-center gap-2 ml-auto">
          <Button
            variant="secondary"
            onClick={handleReset}
            disabled={loading}
          >
            <X className="w-4 h-4 mr-1" />
            重置
          </Button>
          <Button
            onClick={handleSearch}
            loading={loading}
          >
            <Search className="w-4 h-4 mr-1" />
            查询
          </Button>
        </div>
      </div>
    </div>
  )
}

export default SearchBar
