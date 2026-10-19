// case_ids: UI-112
/**
 * `RowActionLink` —— 「单据列表**行内动作**的唯一形态」的单元判据（2026-10-17 用户裁定）。
 *
 * 用户逐字：「这里的操作行内的按钮样式能否保持让全部单据统一向订单保持一致，不要有多种风格设计」
 * ⇒ 形态 = 销售订单那一版（主题色文字 + hover 下划线），收成**一处定义**（本组件），
 * 作业看板与销售订单都引用它；不再各抄一份 class 串。
 *
 * 判据要会红：描边按钮（`border`）回归 / 冒泡到行点击 / `disabled` 仍触发回调 —— 任一条改坏即红。
 */
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import RowActionLink from '@/components/ui/RowActionLink'

describe('RowActionLink（UI-112：单据列表行内动作的唯一形态）', () => {
  it('形态 = 链接式（主题色文字 + hover 下划线），**不是**描边按钮', () => {
    render(<RowActionLink onClick={() => {}}>生产明细</RowActionLink>)
    const el = screen.getByRole('button', { name: '生产明细' })
    // 注入：改回 `Button variant="secondary"`（带边框的按钮）⇒ 后两条红
    expect(el.className).toContain('text-primary-600')
    expect(el.className).toContain('hover:underline')
    expect(el.className).not.toContain('border')
  })

  it('点击触发回调，且**不冒泡**（列表行将来加整行点击不会误触）', () => {
    const onClick = vi.fn()
    const rowClick = vi.fn()
    render(
      <div onClick={rowClick}>
        <RowActionLink onClick={onClick}>订单详情</RowActionLink>
      </div>,
    )
    fireEvent.click(screen.getByRole('button', { name: '订单详情' }))
    // 注入：删掉 `e.stopPropagation()` ⇒ 第二条红
    expect(onClick).toHaveBeenCalledTimes(1)
    expect(rowClick).not.toHaveBeenCalled()
  })

  it('`disabled` ⇒ 淡色 + 不触发回调（禁用态是**控制**，不是只改颜色）', () => {
    const onClick = vi.fn()
    render(
      <RowActionLink onClick={onClick} disabled>
        生产明细
      </RowActionLink>,
    )
    const el = screen.getByRole('button', { name: '生产明细' })
    expect(el).toBeDisabled()
    // 反向自证：可用态**不是**这个色（否则「淡色」这条是空断言）
    expect(el.className).toContain('text-neutral-400')
    fireEvent.click(el)
    expect(onClick).not.toHaveBeenCalled()
  })
})
