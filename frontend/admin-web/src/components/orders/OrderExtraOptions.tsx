'use client'

/**
 * 部位级**特殊选项**录入（19 项多选）—— issue #4511 从 `OrderCraftFields` **抽出来**。
 *
 * ⚠️ **文件名刻意避开 `spec`**（本组件是 `OrderExtraOptions` 而不是 `OrderSpecialOptions`）：
 * `growth_gate._is_test_file` 按「文件名含 test/spec」判定测试文件 ⇒ 含 `spec` 的**源文件**
 * 会被要求声明 `case_ids`（issue **#4376** 已登记该陷阱，结论是**只能改名**，不能靠补 case_ids 绕过）。
 *
 * 为什么抽出来：用户 2026-09-19 口径「**把加工项 - 工艺规格 - 特殊选项都放到平级**，
 * 不要把特殊选项放到工艺规格上」。原实现把它渲染在 `OrderCraftFields` 内部，
 * 而该组件被页面放在「工艺规格」区里 ⇒ 层级上**从属**，不是平级。
 *
 * 本组件**只渲染 19 个 toggle**（不自己带折叠壳）——
 * 折叠与序号由页面侧的「向导步骤」负责（同一份 UI 形态只在一处定义）。
 *
 * 两条不变：
 * - **选项名 = ERP 名，且它是 join key**（issue #4389 裁定 R-e）：改一个字 ⇒ 条件工序不加、
 *   计件系数静默退回 1.0（**少发工人钱**）⇒ 必须与 `routing.py` 及迁移 V59 ∪ V65 逐字一致；
 * - **用 toggle 按钮而非 checkbox**：避免与「加工项」的 checkbox 在选择器上争用（既有判据钉着）。
 */

import { SPECIAL_OPTIONS } from '@/lib/order-craft-fields'

export interface OrderExtraOptionsProps {
  /** 当前已选（缺省 = 一项没选） */
  value?: string[]
  /** 多选变化（**累积/取消**后的完整列表） */
  onChange: (next: string[]) => void
}

export default function OrderExtraOptions({ value, onChange }: OrderExtraOptionsProps) {
  const selected = value ?? []
  const toggle = (option: string) => {
    onChange(selected.includes(option) ? selected.filter((o) => o !== option) : [...selected, option])
  }

  return (
    <div className="flex flex-wrap gap-2">
      {SPECIAL_OPTIONS.map((option) => {
        const active = selected.includes(option)
        return (
          <button
            key={option}
            type="button"
            aria-pressed={active}
            onClick={() => toggle(option)}
            className={
              'h-8 px-2.5 rounded border text-xs transition-colors ' +
              (active
                ? 'border-primary-600 bg-primary-50 text-primary-700 ring-1 ring-primary-500/30'
                : 'border-neutral-300 bg-white text-neutral-700 hover:border-neutral-400')
            }
          >
            {option}
          </button>
        )
      })}
    </div>
  )
}
