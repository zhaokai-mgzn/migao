// case_ids: MC-243
/**
 * `components/orders/order-create/WizardStep.tsx` —— 下单页切片的**折叠骨架**
 * （issue #8725 第一档）。单一职责：折叠/展开的唯一实现（button 语义 + aria-expanded）。
 *
 * 病灶形态（issue #4679 立的规矩）：折叠开关做成 `div` + `onClick` ⇒ 键盘不可达、读屏读不出展开态。
 * 本文件钉的就是「它必须还是一个 button、且 aria-expanded 跟着状态走」。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import {
  CollapsibleHeader,
  WizardStep,
} from '@/components/orders/order-create/WizardStep'

describe('WizardStep — 折叠骨架', () => {
  it('`CollapsibleHeader`：收起显示摘要、展开不显示；两种态都是 button 且有 aria-expanded', () => {
    const { container, rerender } = render(
      <CollapsibleHeader open={false} onToggle={() => {}} summary="6.6 × 2.6 m · 13.8 米">
        组头
      </CollapsibleHeader>
    )
    const closed = container.querySelector('button')!
    expect(closed.getAttribute('aria-expanded')).toBe('false')
    expect(closed.textContent).toContain('6.6 × 2.6 m · 13.8 米')

    rerender(
      <CollapsibleHeader open onToggle={() => {}} summary="6.6 × 2.6 m · 13.8 米">
        组头
      </CollapsibleHeader>
    )
    const opened = container.querySelector('button')!
    expect(opened.getAttribute('aria-expanded')).toBe('true')
    expect(opened.textContent).not.toContain('6.6 × 2.6 m · 13.8 米')
  })

  it('点一下把展开态交回调用方（自己不持有状态）', () => {
    const onToggle = vi.fn()
    render(
      <CollapsibleHeader open={false} onToggle={onToggle}>
        组头
      </CollapsibleHeader>
    )
    fireEvent.click(screen.getByRole('button'))
    expect(onToggle).toHaveBeenCalledTimes(1)
  })

  it('`WizardStep`：编号 + 标题合成可访问名；收起时不渲染正文（不是藏起来）', () => {
    const { rerender } = render(
      <WizardStep step={1} title="用料与规格" open={false} onToggle={() => {}} summary="13.8 米">
        <span>正文</span>
      </WizardStep>
    )
    const btn = screen.getByRole('button', { name: /^1\s*用料与规格/ })
    expect(btn.getAttribute('aria-expanded')).toBe('false')
    expect(screen.queryByText('正文')).toBeNull()

    rerender(
      <WizardStep step={1} title="用料与规格" open onToggle={() => {}} summary="13.8 米">
        <span>正文</span>
      </WizardStep>
    )
    expect(screen.getByText('正文')).toBeInTheDocument()
  })
})
