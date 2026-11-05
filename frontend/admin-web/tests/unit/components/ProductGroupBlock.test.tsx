// case_ids: MC-243
/**
 * `components/orders/order-create/ProductGroupBlock.tsx` —— 下单页切片的**商品组卡**
 * （issue #8725 第一档）。
 *
 * 单一职责：商品基础属性（选择商品 / 颜色 / 门幅 / 售卖形态 / 帘体）+ 净尺寸 + 组内排布；
 * 组级属性改一处就**组内所有行同步**。本文件钉三件事：
 * ① 空组只露出「选择商品」（不假装已经有一个商品）；
 * ② 售卖形态是**组级 radiogroup**（点它把新形态交回页面，由页面同步全组）；
 * ③ 组头能把「这儿缺 N 项」显示在**收起态**（否则商家只知道提交失败，不知道是哪张卡）。
 */
import { describe, it, expect, vi } from 'vitest'
import type { ComponentProps } from 'react'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { ProductGroupBlock } from '@/components/orders/order-create/ProductGroupBlock'
import { createEmptyLineItem } from '@/lib/order-create/calc'
import type { ProductGroup } from '@/lib/order-create/types'

/** 已选商品的最小形状（空组与有商品是两套版面，两种都要判） */
const PRODUCT = {
  id: 'p1',
  name: '测试窗帘',
  price: 100,
  skus: [
    { id: 's1', colorId: 'c1', colorName: '米白', doorWidth: '2.8', price: 118 },
  ],
}

function group(overrides: Partial<ProductGroup> = {}): ProductGroup {
  return {
    id: 'g1',
    product: null,
    productLoading: false,
    selectedColorId: null,
    selectedSku: null,
    saleForm: '成品帘',
    curtainBody: '布帘',
    lines: [createEmptyLineItem('g1')],
    ...overrides,
  }
}

type GroupProps = ComponentProps<typeof ProductGroupBlock>

function props(overrides: Partial<GroupProps> = {}): GroupProps {
  return {
    index: 0,
    group: group(),
    canRemove: false,
    errors: {},
    errorFocus: { key: '', tick: 0 },
    onPickProduct: vi.fn(),
    onSelectColor: vi.fn(),
    onSelectSku: vi.fn(),
    onChangeSaleForm: vi.fn(),
    onChangeCurtainBody: vi.fn(),
    onRemoveGroup: vi.fn(),
    onChangeWidth: vi.fn(),
    onChangeHeight: vi.fn(),
    renderPosition: () => null,
    onChangeQty: vi.fn(),
    onChangePrice: vi.fn(),
    onChangeRollCount: vi.fn(),
    onChangeRollLength: vi.fn(),
    ...overrides,
  }
}

describe('ProductGroupBlock — 商品组卡', () => {
  it('空组只露出「选择商品」（不假装已经有一个商品）', () => {
    const { container } = render(<ProductGroupBlock {...props()} />)
    expect(screen.getByText('选择商品')).toBeInTheDocument()
    expect(container.textContent).toContain('点击搜索并选择商品')
    // 反向：没有商品就不该出现净尺寸 / 帘体等「已有商品」才有的录入面
    expect(container.textContent).not.toContain('窗宽 (米)')
  })

  it('售卖形态是**组级** radiogroup：点「布料」把新形态交回页面（由页面同步全组）', () => {
    const onChangeSaleForm = vi.fn()
    render(
      <ProductGroupBlock
        {...props({ onChangeSaleForm, group: group({ product: PRODUCT as never }) })}
      />
    )
    const chips = screen.getAllByRole('radiogroup', { name: '售卖形态' })[0]
    fireEvent.click(within(chips).getByText('布料'))
    expect(onChangeSaleForm).toHaveBeenCalledWith('布料')
  })

  it('组头的「缺 N 项」在**收起态**也看得见（否则不知道是哪张卡出了事）', () => {
    const p = props({ group: group({ product: PRODUCT as never }) })
    const lineId = p.group.lines[0].id
    const { getByTestId } = render(
      <ProductGroupBlock {...p} errors={{ [`line_${lineId}_quantity`]: '用料米数必须大于 0' }} />
    )
    expect(getByTestId('group-error-badge').textContent).toBe('缺 1 项')
  })

  it('布料形态 ⇒ 组头显示「布料」（而不是印帘体）', () => {
    const { container } = render(
      <ProductGroupBlock
        {...props({ group: group({ product: PRODUCT as never, saleForm: '布料' }) })}
      />
    )
    expect(container.textContent).toContain('布料')
    expect(container.textContent).not.toContain('布帘')
  })
})
