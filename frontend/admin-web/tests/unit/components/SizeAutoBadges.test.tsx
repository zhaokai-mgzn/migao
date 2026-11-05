// case_ids: MC-243
/**
 * `components/orders/order-create/SizeAutoBadges.tsx` —— 下单页切片的**尺寸自动特征徽标**
 * （issue #8725 第一档）。单一职责：只读展示，不含裁决入口。
 *
 * 为什么要单独判：这块在切片前是「组级与行内共用同一实现」的（判据 8：
 * 手选控件里不许出现自动推导特征），搬成独立单元后**唯一性**必须仍成立 ——
 * 本文件只钉「什么条件下出哪个徽标」，不复制判定口径。
 */
import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { sizeAutoBadgesOf } from '@/components/orders/order-create/SizeAutoBadges'
import { createEmptyLineItem } from '@/lib/order-create/calc'

const renderOf = (node: React.ReactNode) => render(<div>{node}</div>)

describe('SizeAutoBadges — 尺寸自动特征徽标', () => {
  it('布料行**不出**徽标（布料没有宽高，徽标无意义）', () => {
    const line = createEmptyLineItem('g1')
    line.saleForm = '布料'
    line.selectedSku = { id: 's1', colorId: 'c1', price: 1, doorWidth: '' }
    const { container } = renderOf(sizeAutoBadgesOf(line))
    expect(container.textContent).toBe('')
  })

  it('还没选 SKU ⇒ 不出「门幅未维护」（否则「还没选规格」会被显示成「未维护」）', () => {
    const { container } = renderOf(sizeAutoBadgesOf(createEmptyLineItem('g1')))
    expect(container.textContent).toBe('')
  })

  it('选了 SKU 但门幅解析不到 ⇒ **具名**徽标「门幅未维护」，并说明为什么不猜', () => {
    const line = createEmptyLineItem('g1')
    line.selectedSku = { id: 's1', colorId: 'c1', price: 1, doorWidth: '' }
    const { container, getByTestId } = renderOf(sizeAutoBadgesOf(line))
    expect(getByTestId('size-door-width-missing').textContent).toBe('门幅未维护')
    expect(container.querySelector('[data-testid="size-door-width-missing"]')?.getAttribute('title')).toContain(
      '该 SKU 未维护门幅'
    )
  })

  it('门幅正常 ⇒ 不出徽标（没有噪音）', () => {
    const line = createEmptyLineItem('g1')
    line.selectedSku = { id: 's1', colorId: 'c1', price: 1, doorWidth: '2.8' }
    const { container } = renderOf(sizeAutoBadgesOf(line))
    expect(container.textContent).toBe('')
  })
})
