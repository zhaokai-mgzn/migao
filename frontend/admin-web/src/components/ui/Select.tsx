'use client'

import { cn } from '@/lib/utils'
import { SelectHTMLAttributes, forwardRef } from 'react'

/**
 * 下拉控件的**唯一控件铬**（issue #7397）。
 *
 * ## 为什么要一个常量（病灶）
 *
 * 2026-10-20 用户三张截图 + 逐字「我们所有页面的下拉框都看着很别扭，不协调」：
 * 业务面 38 处原生 `<select>` 各自拼铬 —— 一部分没写 `appearance-none`（箭头交给操作系统画，
 * macOS 上是一个带框的原生箭头），写了的那几处又**没有自绘箭尖**（`products` / `ProcessingItemsPanel`
 * 的 `pr-9` 后面其实什么都没有 ⇒ 下拉看起来「没有箭头」）；而共享原语 `Select` 又是第三种形态
 * （`rounded-lg` + 叠层 `ChevronDown`）。同一产品里三种下拉语言，且**没有任何判据会红**。
 *
 * ## 形态（与「筛选区输入框」同一套语言）
 *
 * - 高度 `h-9`（= 设计基线的桌面主控件下限，与 `frontend/admin-web/src/components/ui/Input.tsx` 一致）；
 * - 圆角 `rounded`（4px）：**筛选面**的输入框是 4px（`SEARCH_CONTROL_CLASS`，`frontend/admin-web/src/components/ui/SearchPanel.tsx`）
 *   ⇒ 下拉跟着同面输入框走，不另立一套；表单字段面用 `Select` 原语（`rounded-lg`，跟 `Input` 一致）；
 * - 箭头**自绘**（内联 SVG 背景，`neutral-400` 暖色）：不再依赖操作系统 / 浏览器，
 *   macOS / Windows / Linux 同形，也与 `Select` 原语的叠层箭尖**同一份图形**；
 * - 聚焦：主色描边 + 主色半透明环（与输入框逐字同口径）。
 *
 * 🔴 业务面**不许**再自己拼这套铬：判据 = `frontend/admin-web/tests/unit/select-control-unification.test.tsx`
 * （业务面每个 `<select>` 必须引用 `SELECT_CONTROL`，未登记即红）。
 */
const CHEVRON_BG = 'select-chevron'

/**
 * **自绘箭尖**（背景图形 + 定位 + 不重复）：只借箭尖、尺寸自有口径的控件用它
 * （`frontend/admin-web/src/components/ui/Pagination.tsx` 的 h-8 紧凑档、
 * `frontend/admin-web/src/app/register/page.tsx` 的 h-11 入驻表单）。
 */
export const SELECT_CHEVRON = CHEVRON_BG

/** 尺寸 / 边框 / 焦点环 / 自绘箭尖（**不含**圆角与宽度 —— 由所在面决定，见上） */
export const SELECT_BASE =
  'h-9 pl-3 pr-9 text-sm text-neutral-900 appearance-none border border-neutral-300 bg-white ' +
  `${SELECT_CHEVRON} ` +
  'focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 ' +
  'disabled:bg-neutral-100 disabled:text-neutral-500 disabled:cursor-not-allowed'

/** **业务面筛选 / 行内下拉**的完整铬（4px 圆角，同面输入框同值）—— 页面直接 `className={SELECT_CONTROL}` */
export const SELECT_CONTROL = `rounded ${SELECT_BASE}`

/** 表单字段面的完整铬（8px 圆角，与 `Input` 同值）—— `Select` 原语内部用 */
export const SELECT_CONTROL_FIELD = `rounded-lg ${SELECT_BASE}`

interface SelectOption {
  value: string
  label: string
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string
  error?: string
  options: SelectOption[]
  placeholder?: string
}

const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, label, error, options, placeholder, ...props }, ref) => {
    return (
      <div className="w-full">
        {label && (
          <label className="block text-sm font-medium text-neutral-700 mb-1.5">
            {label}
            {props.required && <span className="text-red-500 ml-1">*</span>}
          </label>
        )}
        {/* 箭尖住在 `SELECT_CONTROL_FIELD` 的背景里（单一份图形）——这里**不再**叠一个 `ChevronDown`：
            两套箭头叠加正是 issue #7397 里「看着别扭」的成因之一。 */}
        <select
          ref={ref}
          className={cn(
            'w-full',
            SELECT_CONTROL_FIELD,
            error && 'border-red-500 focus:border-red-500 focus:ring-red-500/15',
            className
          )}
          {...props}
        >
          {placeholder && (
            <option value="" disabled>
              {placeholder}
            </option>
          )}
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        {error && <p className="mt-1 text-sm text-red-600">{error}</p>}
      </div>
    )
  }
)

Select.displayName = 'Select'

export default Select
