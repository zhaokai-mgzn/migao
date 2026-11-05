// case_ids: MC-243
/**
 * `components/orders/order-create/primitives.tsx` —— 下单页切片的**内联小组件**
 * （issue #8725 第一档）。单一职责：只负责「一行字怎么排」，不含业务判断。
 */
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CostRow, Label, Row, SectionTitle } from '@/components/orders/order-create/primitives'

describe('primitives — 内联小组件', () => {
  it('`Label`：必填就带星号，小号只改字号不改文案', () => {
    const { container, rerender } = render(<Label required>数量</Label>)
    expect(screen.getByText('数量')).toBeInTheDocument()
    expect(container.textContent).toBe('数量*')

    rerender(<Label small>单价 (¥/米)</Label>)
    expect(container.textContent).toBe('单价 (¥/米)')
    expect(container.querySelector('label')?.className).toContain('text-xs')
  })

  it('`Row`：左标签右读数，highlight 只改颜色', () => {
    const { container, rerender } = render(<Row label="商品小计" value="¥1,380.00" />)
    expect(container.textContent).toBe('商品小计¥1,380.00')
    rerender(<Row label="订单金额" value="¥1,424.30" highlight />)
    expect(container.querySelectorAll('span')[1].className).toContain('text-orange-600')
  })

  it('`CostRow`：把算式与金额都印出来（可核对），未定价时**不许**渲染成 ¥0.00', () => {
    const { container, rerender } = render(
      <CostRow label="加工" expr="13.8 米 × ¥15.56/米" amount={214.66} />
    )
    expect(container.textContent).toBe('加工13.8 米 × ¥15.56/米¥214.66')

    rerender(<CostRow label="加工" expr="13.8 米 × —" amount={0} amountLabel="未定价" />)
    expect(container.textContent).toBe('加工13.8 米 × —未定价')
    expect(container.textContent).not.toContain('¥0.00')
  })

  it('`SectionTitle`：标题逐字渲染', () => {
    render(<SectionTitle icon={<span>icon</span>} title="商品信息" />)
    expect(screen.getByRole('heading', { name: '商品信息' })).toBeInTheDocument()
  })
})
