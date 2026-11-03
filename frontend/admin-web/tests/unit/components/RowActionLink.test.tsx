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

  // ==================== issue #7082：变体 = 迁移点"外观逐字不变"的承载体 ====================
  //
  // 每个变体都对应一个**真实**消费点（不留投机 API）。这四条的读数是「迁移前那一串 class」
  // 的**冻结记录**：变体映射被改（字号 / 字重 / 禁用态观感 / 色族）⇒ 迁移点的观感就变了 ⇒ 红。

  it('`size="sm"` = `text-sm`（售后列表行内「查看」改前的那一串：token 集合逐字相同）', () => {
    render(
      <RowActionLink size="sm" onClick={() => {}}>
        查看
      </RowActionLink>,
    )
    const el = screen.getByRole('button', { name: '查看' })
    // 改前 = `text-primary-600 hover:text-primary-700 hover:underline transition-colors text-sm`
    for (const token of ['text-primary-600', 'hover:text-primary-700', 'hover:underline', 'transition-colors', 'text-sm']) {
      expect(el.className).toContain(token)
    }
    // 反向自证：`xs` / `md` 不得带 `text-sm`（否则「字号由 prop 决定」是空断言）
    expect(el.className).not.toContain('text-xs')
  })

  it('`size="xs"` = `text-xs`（工人档案面板「默认页面」改前的 `text-xs`）', () => {
    render(
      <RowActionLink size="xs" onClick={() => {}}>
        默认页面
      </RowActionLink>,
    )
    const el = screen.getByRole('button', { name: '默认页面' })
    expect(el.className).toContain('text-xs')
    expect(el.className).not.toContain('text-sm')
  })

  it('`emphasis` = `font-medium`（员工列表「姓名」那一格改前的字重）', () => {
    render(
      <RowActionLink size="sm" emphasis onClick={() => {}}>
        张三
      </RowActionLink>,
    )
    const el = screen.getByRole('button', { name: '张三' })
    expect(el.className).toContain('font-medium')
    // 反向自证：不传 emphasis ⇒ 不得有 font-medium（否则强调是空断言）
    render(
      <RowActionLink size="sm" onClick={() => {}}>
        李四
      </RowActionLink>,
    )
    expect(screen.getByRole('button', { name: '李四' }).className).not.toContain('font-medium')
  })

  it('`disabledStyle="keep"` = 保持字色 + `cursor-default`（员工姓名无写权限时**不得**变灰占位）', () => {
    render(
      <RowActionLink size="sm" emphasis disabledStyle="keep" disabled onClick={() => {}}>
        张三
      </RowActionLink>,
    )
    const el = screen.getByRole('button', { name: '张三' })
    expect(el).toBeDisabled()
    // 改前 = `text-primary-600 … text-sm font-medium disabled:cursor-default`
    expect(el.className).toContain('text-primary-600')
    expect(el.className).toContain('cursor-default')
    expect(el.className).toContain('font-medium')
    expect(el.className).not.toContain('text-neutral-400')
    expect(el.className).not.toContain('cursor-not-allowed')
  })

  it('`tone="danger"` = 红字（加工项面板行内「删除」改前的 `text-red-500 hover:text-red-600`）', () => {
    render(
      <RowActionLink size="sm" tone="danger" onClick={() => {}}>
        删除
      </RowActionLink>,
    )
    const el = screen.getByRole('button', { name: '删除' })
    expect(el.className).toContain('text-red-500')
    expect(el.className).toContain('hover:text-red-600')
    expect(el.className).not.toContain('text-primary-600')
    // 反向自证：默认 tone 仍是主题色（不然 danger 会把所有行内动作染红）
    render(
      <RowActionLink size="sm" onClick={() => {}}>
        编辑
      </RowActionLink>,
    )
    expect(screen.getByRole('button', { name: '编辑' }).className).toContain('text-primary-600')
  })
})
