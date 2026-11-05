// case_ids: MC-243
/**
 * `components/orders/order-create/LineItemBlock.tsx` —— 下单页切片的**部位行**
 * （issue #8725 第一档，1,804 行，是切片里最大的一块）。
 *
 * 单一职责：把一行帘子的**全部录入面与推导读数**渲染出来，并把改动交回页面。
 * 本文件不复制任何算料口径（那在 `lib/order-create/calc.ts` 有单一真值源与自己的判据），
 * 只钉「它是不是真的把这几块渲染出来了、回调是不是真的交回去了」——
 * 也就是切片最容易切坏的两种形态：**搬漏一块** / **回调接错一根线**。
 */
import { describe, it, expect, vi } from 'vitest'
import type { ComponentProps } from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { LineItemBlock } from '@/components/orders/order-create/LineItemBlock'
import { createEmptyLineItem } from '@/lib/order-create/calc'

/** 一行空白帘子的全套 props（缺省全是不抛错的替身，用例只覆盖自己那一根线） */
type BlockProps = ComponentProps<typeof LineItemBlock>

function props(overrides: Partial<BlockProps> = {}): BlockProps {
  const line = createEmptyLineItem('g1')
  return {
    line,
    errors: {},
    errorFocus: { key: '', tick: 0 },
    processingLoading: false,
    onChangeQty: vi.fn(),
    onRestoreFormula: vi.fn(),
    onChangePrice: vi.fn(),
    onToggleProcessing: vi.fn(),
    onChangeCraft: vi.fn(),
    onAutoFeatureDecision: vi.fn(),
    onEdgeMetersChange: vi.fn(),
    onEdgeUnitPriceChange: vi.fn(),
    feeRow: null,
    calcConfig: null,
    onChangePlanOverrides: vi.fn(),
    onDerivedOptionDecision: vi.fn(),
    onProcessingFeeOverrideChange: vi.fn(),
    onRecommendedDecision: vi.fn(),
    onChangeRemark: vi.fn(),
    onChangeInstallRoom: vi.fn(),
    ...overrides,
  }
}

describe('LineItemBlock — 部位行', () => {
  it('两块录入面都在场：① 用料与规格、② 加工项（切片前是同一个组件的两步）', () => {
    render(<LineItemBlock {...props()} />)
    expect(screen.getByRole('button', { name: /^1\s*用料与规格/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^2\s*加工项/ })).toBeInTheDocument()
  })

  it('用料与规格里印出「用料米数 / 单价」两个**可编辑**录入面（常态可编辑，不是只读）', () => {
    render(<LineItemBlock {...props()} />)
    const meters = screen.getByText('用料米数').closest('div')!.querySelector('input')!
    expect(meters.readOnly).toBe(false)
    expect(meters.value).toBe('1')
    expect(screen.getByText('单价 (¥/米)')).toBeInTheDocument()
  })

  it('算料配置读失败 ⇒ **具名**提示（不是静默按缺省口径假装已加载）', () => {
    const { container } = render(<LineItemBlock {...props({ calcConfig: null })} />)
    expect(container.textContent).toContain('算料配置未加载')
    expect(container.textContent).toContain('本次按缺省口径试算')
  })

  it('改用料米数把**数值**交回页面（切片最容易接错的一根线）', () => {
    const onChangeQty = vi.fn()
    render(<LineItemBlock {...props({ onChangeQty })} />)
    const meters = screen.getByText('用料米数').closest('div')!.querySelector('input')!
    fireEvent.change(meters, { target: { value: '13.8' } })
    expect(onChangeQty).toHaveBeenCalledWith(13.8)
  })

  it('行级错误按 `line_<id>_<field>` 具名渲染（不是一处通用提示）', () => {
    const p = props()
    const { getByText } = render(
      <LineItemBlock {...p} errors={{ [`line_${p.line.id}_quantity`]: '用料米数必须大于 0' }} />
    )
    expect(getByText('用料米数必须大于 0')).toBeInTheDocument()
  })
})
