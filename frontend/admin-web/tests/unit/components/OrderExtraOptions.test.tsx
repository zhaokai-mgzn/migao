// case_ids: OR-009, UI-038
/**
 * 部位级**特殊选项**录入 —— issue #4511 从 `OrderCraftFields` 抽出后的判据；
 * issue #8007（用户 2026-10-28 裁定）起录入词表是**语义选项**；issue #8108 起两族合并（19 项
 * join key ⇒ **17 个可点项**），布/纱派生键（`余料带回-布/-纱`、`布绑带/纱绑带`）不进 UI。
 *
 * 为什么迁到这里：用户 2026-09-19「**把加工项 - 工艺规格 - 特殊选项都放到平级**」——
 * 该组件不再自带折叠壳（折叠与序号由页面侧的向导步骤负责），所以
 * 「默认收起 / 展开」这两条**属于页面**，而「一个不少 / 多选累积 / 不用 checkbox」
 * **属于本组件** —— 判据跟着职责走，不在两处重复钉同一件事。
 *
 * 🔴 issue #8007 的两条实例判据：
 * ① 只出 `余料带回`（`余料带回-布` / `-纱` 不得成为可点项 —— 材料不是商家的选择题）；
 * ② 勾选落库值**按本行帘种派生**：无帘种 / 布帘 ⇒ `-布`，纱帘 ⇒ `-纱`。
 */
import { useState } from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import OrderExtraOptions from '@/components/orders/OrderExtraOptions'
import { specialOptionDisplayOptions } from '@/lib/order-craft-fields'

/** 受控包装：模拟页面用 useState 持有已选列表；`stored` 暴露**落库值**（派生键）供断言 */
function Harness({
  initial = [] as string[],
  curtainType,
}: {
  initial?: string[]
  curtainType?: string
}) {
  const [value, setValue] = useState<string[]>(initial)
  return (
    <div>
      <output data-testid="stored">{JSON.stringify(value)}</output>
      <OrderExtraOptions value={value} curtainType={curtainType} onChange={setValue} />
    </div>
  )
}

const stored = () => JSON.parse(screen.getByTestId('stored').textContent || '[]') as string[]

describe('OrderExtraOptions（issue #4511 抽离 / issue #8007 布纱归一）', () => {
  it('渲染 17 个**语义选项**，逐字与展示词表一致，且不含布/纱派生键', () => {
    render(<Harness />)
    const rendered = screen.getAllByRole('button').map((b) => b.textContent)
    expect(rendered).toEqual(specialOptionDisplayOptions())
    expect(rendered).toHaveLength(17)
    expect(rendered.filter((name) => /-(布|纱)$/.test(name ?? ''))).toEqual([])
    // 「余料带回」/「绑带」在册（两族各合并成一个可选项），位置沿用 join key 清单
    expect(rendered[0]).toBe('余料带回')
    expect(rendered[1]).toBe('绑带')
    expect(rendered).not.toContain('布绑带')
    expect(rendered).not.toContain('纱绑带')
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

  it('🔴 存量派生键 ⇒ 显示为「余料带回」已选，取消后落库值清空', () => {
    render(<Harness initial={['余料带回-布']} />)
    expect(screen.getByRole('button', { name: '余料带回' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('button', { name: '余料带回' }))
    expect(stored()).toEqual([])
  })

  it('🔴 勾「余料带回」⇒ 落库键按帘种派生：缺省/布帘 ⇒ -布，纱帘 ⇒ -纱', () => {
    const { unmount } = render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: '余料带回' }))
    expect(stored()).toEqual(['余料带回-布'])
    unmount()

    render(<Harness curtainType="纱帘" />)
    fireEvent.click(screen.getByRole('button', { name: '余料带回' }))
    expect(stored()).toEqual(['余料带回-纱'])
  })

  it('非族选项不派生：勾「加铅块」⇒ 原样落库（不因帘种改名）', () => {
    render(<Harness curtainType="纱帘" />)
    fireEvent.click(screen.getByRole('button', { name: '加铅块' }))
    expect(stored()).toEqual(['加铅块'])
  })

  it('用 toggle 按钮而非 checkbox —— 不得与「加工项」的 checkbox 选择器争用', () => {
    render(<Harness />)
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
  })

  it('**不自带折叠壳**（issue #4511）：选项一开始就在 DOM 里，折叠由页面侧的向导步骤负责', () => {
    render(<Harness />)
    expect(screen.getByRole('button', { name: '余料带回' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /特殊选项/ })).toBeNull()
  })

  it('🔴 issue #8108 勾「绑带」⇒ 落库键按帘种派生：缺省/布帘/帘头 ⇒ 布绑带，纱帘 ⇒ 纱绑带', () => {
    const { unmount } = render(<Harness />)
    fireEvent.click(screen.getByRole('button', { name: '绑带' }))
    expect(stored()).toEqual(['布绑带'])
    unmount()

    render(<Harness curtainType="纱帘" />)
    fireEvent.click(screen.getByRole('button', { name: '绑带' }))
    expect(stored()).toEqual(['纱绑带'])
  })

  it('🔴 issue #8108 存量派生键 ⇒ 显示为「绑带」已选；两键并存只出一个可点项', () => {
    render(<Harness initial={['布绑带', '纱绑带']} />)
    expect(screen.getByRole('button', { name: '绑带' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByRole('button', { name: '布绑带' })).toBeNull()
    expect(screen.queryByRole('button', { name: '纱绑带' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '绑带' }))
    expect(stored()).toEqual([])
  })
})
