// case_ids: OR-009, UI-038
/**
 * 部位级**特殊选项**录入（19 项多选）—— issue #4511 从 `OrderCraftFields` 抽出后的判据。
 *
 * 为什么迁到这里：用户 2026-09-19「**把加工项 - 工艺规格 - 特殊选项都放到平级**」——
 * 该组件不再自带折叠壳（折叠与序号由页面侧的向导步骤负责），所以
 * 「默认收起 / 展开」这两条**属于页面**，而「19 项一个不少 / 多选累积 / 不用 checkbox」
 * **属于本组件** —— 判据跟着职责走，不在两处重复钉同一件事。
 */
import { useState } from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import OrderExtraOptions from '@/components/orders/OrderExtraOptions'
import { SPECIAL_OPTIONS } from '@/lib/order-craft-fields'

/** 受控包装：模拟页面用 useState 持有已选列表 */
function Harness({ initial = [] as string[] }) {
  const [value, setValue] = useState<string[]>(initial)
  return <OrderExtraOptions value={value} onChange={setValue} />
}

describe('OrderExtraOptions（issue #4511 抽离）', () => {
  it('渲染 19 项特殊选项，且**逐字**与清单一致（选项名是 join key，错一个字就少发工人钱）', () => {
    render(<Harness />)
    const rendered = screen.getAllByRole('button').map((b) => b.textContent)
    expect(rendered).toEqual([...SPECIAL_OPTIONS])
    expect(rendered).toHaveLength(19)
  })

  it('多选：逐个累积，再点一次取消', () => {
    render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: '加铅块' }))
    fireEvent.click(screen.getByRole('button', { name: '拼2次' }))
    expect(screen.getByRole('button', { name: '加铅块' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '拼2次' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('button', { name: '加铅块' }))
    expect(screen.getByRole('button', { name: '加铅块' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: '拼2次' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('带既有值进入 ⇒ 该值显示为已选（编辑存量行的形态）', () => {
    render(<Harness initial={['加花边', '一分为二']} />)
    expect(screen.getByRole('button', { name: '加花边' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '一分为二' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '加铅块' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('用 toggle 按钮而非 checkbox —— 不得与「加工项」的 checkbox 选择器争用', () => {
    render(<Harness />)
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
  })

  it('**不自带折叠壳**（issue #4511）：19 项一开始就在 DOM 里，折叠由页面侧的向导步骤负责', () => {
    render(<Harness />)
    expect(screen.getByRole('button', { name: SPECIAL_OPTIONS[0] })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /特殊选项/ })).toBeNull()
  })
})
