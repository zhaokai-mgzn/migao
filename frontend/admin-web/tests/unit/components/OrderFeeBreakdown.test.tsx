// case_ids: UI-076, UI-151
// @vitest-environment jsdom
/**
 * 订单详情页「费用构成」组件（issue #5843）—— 组件级判据（页面级判据见
 * `frontend/admin-web/tests/unit/pages/order-detail.test.tsx`，构成判定见
 * `frontend/admin-web/tests/unit/lib/order-fee-display.test.ts`）。
 *
 * 本文件钉的是**渲染面**的硬口径（用户 2026-10-01 报障后的展示裁定）：
 * ① 等式在页面上看得见（商品合计 + 加工费 = 订单金额，逐值闭合）；
 * ② 未定价不渲染 `¥0.00` —— 那格写「未定价 · 组合名」；
 * ③ 布料单不出现加工费空行 / `¥0.00` 行（**费用明细面板仍在**：商品合计 / 订单金额 / 实收款）；
 * ④ 人工改价显式标出、差额非 0 有「其它构成」解释行。
 *
 * 2026-11-11 用户口径（issue #8896）：卡头「订单实收款」、费用构成、底部金额汇总三处重复
 * ⇒ 合并成**一张「费用明细」**：商品合计 → 加工费 → 其它构成 → 订单金额 → 优惠/已退款 → 实收款；
 * 优惠 / 已退款为 0 时不占行。
 */
import { describe, it, expect } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import OrderFeeBreakdown from '@/components/orders/OrderFeeBreakdown'
import type { OrderItem } from '@/types'

/** 用户报障那一单的行形状：单价 ¥23.80 × 10.3 米 = 245.14；10.3 米 × ¥12.00/米 = 123.60 */
const makeItem = (overrides: Partial<OrderItem> = {}): OrderItem => ({
  id: 'item-1',
  productName: '全遮光雪尼尔',
  quantity: 10.3,
  unitPrice: 23.8,
  amount: 245.14,
  subtotal: 245.14,
  processingFee: 123.6,
  processingInfo: {
    processingFeeDetail: {
      composition: '韩褶 + 定型',
      unit_price: 12,
      meters: 10.3,
      fee_source: 'matched',
      amount: 123.6,
    },
  },
  ...overrides,
})

describe('OrderFeeBreakdown（订单详情页费用构成，issue #5843）', () => {
  it('三行读数 + 一行等式：¥245.14（商品合计） + ¥123.60（加工费） = ¥368.74（订单金额）', () => {
    render(<OrderFeeBreakdown items={[makeItem()]} goodsTotal={245.14} orderTotal={368.74} />)

    expect(screen.getByTestId('fee-breakdown-goods')).toHaveTextContent('¥245.14')
    expect(screen.getByTestId('fee-breakdown-processing')).toHaveTextContent('¥123.60')
    expect(screen.getByTestId('fee-breakdown-order-total')).toHaveTextContent('¥368.74')
    expect(screen.getByTestId('fee-breakdown-equation')).toHaveTextContent(
      '¥245.14（商品合计） + ¥123.60（加工费） = ¥368.74（订单金额）'
    )
  })

  it('多行：逐行给出算式（米数 × 单价/米 = 金额），加工费合计 = Σ 各行落库值', () => {
    render(
      <OrderFeeBreakdown
        items={[
          makeItem(),
          makeItem({
            id: 'item-2',
            productName: '遮光纱',
            processingFee: 76.4,
            processingInfo: {
              processingFeeDetail: {
                composition: '韩褶',
                unit_price: 8,
                meters: 9.55,
                fee_source: 'matched',
                amount: 76.4,
              },
            },
          }),
        ]}
        goodsTotal={600}
        orderTotal={800}
      />
    )

    const lines = screen.getAllByTestId('fee-breakdown-line')
    expect(lines).toHaveLength(2)
    expect(lines[0]).toHaveTextContent('10.3 米 × ¥12.00/米 = ¥123.60')
    expect(lines[1]).toHaveTextContent('9.55 米 × ¥8.00/米 = ¥76.40')
    // 合计 = 123.60 + 76.40（原样相加的两个落库值，不按单价重算）
    expect(screen.getByTestId('fee-breakdown-processing')).toHaveTextContent('¥200.00')
    expect(screen.getByTestId('fee-breakdown-equation')).toHaveTextContent(
      '¥600.00（商品合计） + ¥200.00（加工费） = ¥800.00（订单金额）'
    )
  })

  it('布料单（无加工费 / 无未定价 / 无差额）：费用明细仍在，但无加工费行、无 ¥0.00 行', () => {
    const { container } = render(
      <OrderFeeBreakdown
        items={[makeItem({ processingFee: 0, processingInfo: undefined })]}
        goodsTotal={245.14}
        orderTotal={245.14}
        actualAmount={245.14}
      />
    )

    // issue #8896：费用明细是商品信息的**唯一**金额面 ⇒ 布料单也要能一眼看到商品合计 / 订单金额 / 实收款
    expect(screen.getByTestId('order-fee-breakdown')).toBeInTheDocument()
    expect(screen.getByText('费用明细')).toBeInTheDocument()
    expect(screen.getByTestId('fee-breakdown-goods')).toHaveTextContent('¥245.14')
    expect(screen.getByTestId('fee-breakdown-order-total')).toHaveTextContent('¥245.14')
    expect(screen.getByTestId('fee-breakdown-actual')).toHaveTextContent('¥245.14')
    // 没有加工是正常：不出现加工费行、不出现 ¥0.00、也不出现「0 = 0」的对账等式噪音
    expect(screen.queryByTestId('fee-breakdown-processing')).toBeNull()
    expect(screen.queryByTestId('fee-breakdown-equation')).toBeNull()
    expect(container.textContent).not.toContain('¥0.00')
  })

  it('一张费用明细：优惠 / 已退款列在订单金额之后，实收款最后一行；0 值不占行', () => {
    const { rerender } = render(
      <OrderFeeBreakdown
        items={[makeItem()]}
        goodsTotal={245.14}
        orderTotal={368.74}
        discountAmount={20}
        refundAmount={0}
        actualAmount={348.74}
      />
    )

    expect(screen.getByText('费用明细')).toBeInTheDocument()
    expect(screen.getByTestId('fee-breakdown-discount')).toHaveTextContent('-¥20.00')
    expect(screen.queryByTestId('fee-breakdown-refund')).toBeNull()
    expect(screen.getByTestId('fee-breakdown-actual')).toHaveTextContent('¥348.74')

    rerender(
      <OrderFeeBreakdown
        items={[makeItem()]}
        goodsTotal={245.14}
        orderTotal={368.74}
        discountAmount={0}
        refundAmount={50}
        refundAt="2026-06-21T10:00:00Z"
        actualAmount={318.74}
      />
    )
    expect(screen.queryByTestId('fee-breakdown-discount')).toBeNull()
    expect(screen.getByTestId('fee-breakdown-refund')).toHaveTextContent('¥50.00')
    expect(screen.getByTestId('fee-breakdown-refund')).toHaveTextContent('2026-06-21')
    expect(screen.getByTestId('fee-breakdown-actual')).toHaveTextContent('¥318.74')
  })

  it('未定价：那格写「未定价 · 组合名」，整块里不出现 ¥0.00', () => {
    const { container } = render(
      <OrderFeeBreakdown
        items={[
          makeItem({
            processingFee: 0,
            processingInfo: {
              processingFeeDetail: {
                composition: '韩褶 + 定型',
                items: ['韩褶', '定型'],
                fee_source: 'unpriced',
                amount: 0,
              },
            },
          }),
        ]}
        goodsTotal={245.14}
        orderTotal={245.14}
      />
    )

    expect(screen.getByTestId('fee-breakdown-line')).toHaveTextContent('未定价 · 韩褶 + 定型')
    expect(screen.getByTestId('fee-breakdown-unpriced')).toHaveTextContent(
      '有 1 行加工费未定价（韩褶 + 定型）'
    )
    // 未定价那半按 0 计 ⇒ 不渲染「加工费 ¥0.00」（那与「本来就不收」长得一样 = 静默改钱的外观）
    expect(screen.queryByTestId('fee-breakdown-processing')).toBeNull()
    expect(container.textContent).not.toContain('¥0.00')
    // 但整块必须还在（否则商家看不到「这一行没定价」）
    expect(screen.getByTestId('fee-breakdown-equation')).toHaveTextContent(
      '¥245.14（商品合计） = ¥245.14（订单金额），其中 1 行未定价（见下）'
    )
  })

  it('人工改价显式标出；差额非 0 ⇒ 「其它构成」解释行把差额报出来', () => {
    render(
      <OrderFeeBreakdown
        items={[
          makeItem({
            processingInfo: {
              processingFeeDetail: {
                unit_price: 9.99,
                meters: 10.3,
                fee_source: 'manual',
                amount: 123.6,
              },
            },
          }),
        ]}
        goodsTotal={245.14}
        orderTotal={373.74}
      />
    )

    // 落库值 123.60（不是 9.99 × 10.3 = 102.90）
    expect(screen.getByTestId('fee-breakdown-processing')).toHaveTextContent('¥123.60')
    expect(within(screen.getByTestId('order-fee-breakdown')).getByText('人工改价')).toHaveTextContent(
      '人工改价'
    )
    expect(screen.getByTestId('fee-breakdown-other')).toHaveTextContent('¥5.00')
    expect(screen.getByTestId('fee-breakdown-equation')).toHaveTextContent(
      '¥245.14（商品合计） + ¥123.60（加工费） + ¥5.00（其它构成） = ¥373.74（订单金额）'
    )
  })

  it('订单金额未取到（null）：不编差额、不渲染「其它构成」', () => {
    render(<OrderFeeBreakdown items={[makeItem()]} goodsTotal={245.14} orderTotal={null} />)

    expect(screen.queryByTestId('fee-breakdown-other')).toBeNull()
    expect(screen.getByTestId('fee-breakdown-order-total')).toHaveTextContent('—')
    expect(screen.getByTestId('fee-breakdown-equation')).toHaveTextContent('订单金额未取到')
  })
})
