// case_ids: OR-001, UI-020
// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import OrderItemList from '@/components/orders/OrderItemList'
import type { OrderItem } from '@/types'

const makeItem = (overrides: Partial<OrderItem> = {}): OrderItem => ({
  id: 'item-1',
  productName: '测试窗帘布',
  quantity: 5,
  unitPrice: 100,
  amount: 500,
  subtotal: 500,
  ...overrides,
})

describe('OrderItemList', () => {
  describe('header rendering', () => {
    it('renders table headers', () => {
      render(<OrderItemList items={[makeItem()]} />)
      expect(screen.getByText('商品信息')).toBeInTheDocument()
      expect(screen.getByText('数量')).toBeInTheDocument()
      expect(screen.getByText('单价')).toBeInTheDocument()
      expect(screen.getByText('加工费')).toBeInTheDocument()
      expect(screen.getByText('小计')).toBeInTheDocument()
    })
  })

  describe('item rendering', () => {
    it('renders product name', () => {
      render(<OrderItemList items={[makeItem()]} />)
      expect(screen.getByText('测试窗帘布')).toBeInTheDocument()
    })

    it('renders quantity with × prefix', () => {
      render(<OrderItemList items={[makeItem()]} />)
      expect(screen.getByText('×5')).toBeInTheDocument()
    })

    it('renders unit price formatted in CNY', () => {
      render(<OrderItemList items={[makeItem({ unitPrice: 88, subtotal: 880 })]} />)
      expect(screen.getByText('¥88.00')).toBeInTheDocument()
    })

    it('renders dash when no processing fee', () => {
      render(<OrderItemList items={[makeItem()]} />)
      // The dash appears in the processingFee column (no fee for this item) and also
      // could appear elsewhere; just verify it's present
      expect(screen.getByText('-')).toBeInTheDocument()
    })

    it('renders processing fee when present', () => {
      render(<OrderItemList items={[makeItem({ processingFee: 50 })]} />)
      // ¥50.00 appears in processingFee column and possibly 加工费合计 totals row
      const matches = screen.getAllByText('¥50.00')
      expect(matches.length).toBeGreaterThanOrEqual(1)
    })

    it('renders subtotal column as subtotal + processingFee', () => {
      render(<OrderItemList items={[makeItem({ processingFee: 50 })]} />)
      // subtotal (500) + processingFee (50) = 550 in the "小计" column
      // Also appears as "订单总金额" in totals. Just verify it's there.
      const matches = screen.getAllByText('¥550.00')
      expect(matches.length).toBeGreaterThanOrEqual(1)
    })

    it('renders SKU when provided', () => {
      render(<OrderItemList items={[makeItem({ sku: 'SKU-001' })]} />)
      expect(screen.getByText('SKU: SKU-001')).toBeInTheDocument()
    })

    it('renders specification when provided', () => {
      render(<OrderItemList items={[makeItem({ specification: '门幅2.8米' })]} />)
      expect(screen.getByText('规格: 门幅2.8米')).toBeInTheDocument()
    })

    it('renders width and height when provided', () => {
      render(<OrderItemList items={[makeItem({ width: 3.5, height: 2.8 })]} />)
      expect(screen.getByText('宽: 3.5m')).toBeInTheDocument()
      expect(screen.getByText('高: 2.8m')).toBeInTheDocument()
    })

    it('renders processingInfo details when present', () => {
      render(
        <OrderItemList
          items={[
            makeItem({
              processingInfo: {
                colorName: '深蓝色',
                sellingMethod: 'bulk_cut',
                doorWidth: '2.8m',
              },
            }),
          ]}
        />
      )
      expect(screen.getByText('深蓝色')).toBeInTheDocument()
      expect(screen.getByText('散剪')).toBeInTheDocument()
      expect(screen.getByText('门幅: 2.8m')).toBeInTheDocument()
    })

    it('renders processingInfo raw when keys present', () => {
      render(
        <OrderItemList
          items={[
            makeItem({
              processingInfo: { edgeType: '卷边', quantity: 10 },
            }),
          ]}
        />
      )
      expect(screen.getByText(/加工: edgeType: 卷边, quantity: 10/)).toBeInTheDocument()
    })

    it('renders multiple items', () => {
      const items = [
        makeItem({ id: 'item-1', productName: '窗帘A', quantity: 2, unitPrice: 80, subtotal: 160 }),
        makeItem({ id: 'item-2', productName: '窗帘B', quantity: 3, unitPrice: 120, subtotal: 360 }),
      ]
      render(<OrderItemList items={items} />)
      expect(screen.getByText('窗帘A')).toBeInTheDocument()
      expect(screen.getByText('窗帘B')).toBeInTheDocument()
    })
  })

  describe('totals section', () => {
    it('renders subtotal sum in totals area', () => {
      const items = [
        makeItem({ id: 'item-1', subtotal: 200 }),
        makeItem({ id: 'item-2', subtotal: 300 }),
      ]
      render(<OrderItemList items={items} />)
      // Validate the label exists
      expect(screen.getByText('商品金额')).toBeInTheDocument()
      // 500 appears in item rows too, so use getAllByText
      const matches = screen.getAllByText('¥500.00')
      expect(matches.length).toBeGreaterThanOrEqual(1)
    })

    it('shows processing fee sum when any item has processing fee', () => {
      const items = [
        makeItem({ id: 'item-1', subtotal: 200, processingFee: 30 }),
        makeItem({ id: 'item-2', subtotal: 300 }),
      ]
      render(<OrderItemList items={items} />)
      expect(screen.getByText('加工费合计')).toBeInTheDocument()
      // ¥30.00 also appears in the item row processingFee column
      const matches = screen.getAllByText('¥30.00')
      expect(matches.length).toBeGreaterThanOrEqual(1)
    })

    it('does not show processing fee sum when none have fees', () => {
      const items = [
        makeItem({ id: 'item-1', subtotal: 200 }),
        makeItem({ id: 'item-2', subtotal: 300 }),
      ]
      render(<OrderItemList items={items} />)
      expect(screen.queryByText('加工费合计')).not.toBeInTheDocument()
    })

    it('shows total order amount label', () => {
      const items = [
        makeItem({ id: 'item-1', subtotal: 200, processingFee: 30 }),
        makeItem({ id: 'item-2', subtotal: 300, processingFee: 20 }),
      ]
      render(<OrderItemList items={items} />)
      expect(screen.getByText('订单总金额')).toBeInTheDocument()
      // Total: (200+30) + (300+20) = 550. Also appears in item #2 subtotal column
      const matches = screen.getAllByText('¥550.00')
      expect(matches.length).toBeGreaterThanOrEqual(1)
    })
  })

  describe('empty state', () => {
    it('renders headers and zero totals with empty items', () => {
      render(<OrderItemList items={[]} />)
      // Headers should still render
      expect(screen.getByText('商品信息')).toBeInTheDocument()
      // Total rows show ¥0.00 for both 商品金额 and 订单总金额
      const zeroMatches = screen.getAllByText('¥0.00')
      expect(zeroMatches.length).toBeGreaterThanOrEqual(1)
    })
  })

  describe('className prop', () => {
    it('applies custom className', () => {
      const { container } = render(
        <OrderItemList items={[makeItem()]} className="custom-class" />
      )
      expect(container.firstChild).toHaveClass('custom-class')
    })
  })

  describe('currency formatting', () => {
    it('formats amounts with two decimal places', () => {
      // Use different values for unitPrice and subtotal to avoid overlap
      render(<OrderItemList items={[makeItem({ unitPrice: 99.5, subtotal: 497.5 })]} />)
      expect(screen.getByText('¥99.50')).toBeInTheDocument()
    })

    it('formats large numbers with thousand separators', () => {
      // Use different values for unitPrice and subtotal to avoid overlap
      render(<OrderItemList items={[makeItem({ unitPrice: 1234.56, subtotal: 12345.67 })]} />)
      const matches = screen.getAllByText('¥12,345.67')
      expect(matches.length).toBeGreaterThanOrEqual(1)
    })
  })

  // issue #4355 / 设计文档 §4.9 ② 订单：明细行展示工艺规格（渲染 order_items.processing_info）
  describe('craft spec', () => {
    it('渲染工艺规格行：部位/工艺/加工类型/打开方式/是否定型/款式/特殊选项', () => {
      render(
        <OrderItemList
          items={[
            makeItem({
              processingInfo: {
                curtainType: '布帘',
                craft: '韩褶',
                cuttingMode: '定高买宽',
                openCount: 2,
                isShaped: true,
                style: '拼色',
                specialOptions: ['加铅线', '双褶'],
              },
            }),
          ]}
        />
      )
      expect(screen.getByText('工艺规格')).toBeInTheDocument()
      expect(screen.getByText('布帘')).toBeInTheDocument()
      expect(screen.getByText('韩褶')).toBeInTheDocument()
      expect(screen.getByText('定高买宽')).toBeInTheDocument()
      expect(screen.getByText('双开')).toBeInTheDocument()
      expect(screen.getByText('拼色')).toBeInTheDocument()
      expect(screen.getByText('加铅线、双褶')).toBeInTheDocument()
      // 「是否定型」= 是（按行断言，避免与其它「是」歧义）
      expect(screen.getByText('是否定型').parentElement?.textContent).toContain('是')
    })

    it('渲染算料口径：总褶数/折数（每片）/褶距/幅数/褶倍/米数/是否对花/花距', () => {
      render(
        <OrderItemList
          items={[
            makeItem({
              processingInfo: {
                pleat_count: 52,
                per_panel_pleats: 26,
                pleatSpacing: 0.1,
                panels: 4,
                fullness: 2,
                fullness_actual: 1.86,
                fabric_meters: 13.3,
                processingMeters: 13.3,
                hasPattern: true,
                patternRepeat: 0.32,
              },
            }),
          ]}
        />
      )
      expect(screen.getByText('52')).toBeInTheDocument()
      expect(screen.getByText('26')).toBeInTheDocument()
      expect(screen.getByText('0.1米')).toBeInTheDocument()
      expect(screen.getByText('4')).toBeInTheDocument()
      expect(screen.getByText('2 倍')).toBeInTheDocument()
      expect(screen.getByText('1.86 倍')).toBeInTheDocument()
      // 面料米数 / 加工费米数 = §4.9 要求的**两个字段**（§6.1 口径拆两值）⇒ 同值时出现两次
      expect(screen.getAllByText('13.3米')).toHaveLength(2)
      expect(screen.getByText('0.32米')).toBeInTheDocument()
      expect(screen.getByText('是否对花')).toBeInTheDocument()
    })

    it('工艺键不再落进「加工: k: v」原始键值兜底行（同一真值不重复展示）', () => {
      render(
        <OrderItemList
          items={[makeItem({ processingInfo: { craft: '韩褶', edgeType: '卷边' } })]}
        />
      )
      expect(screen.getByText('韩褶')).toBeInTheDocument()
      // 兜底行只剩非工艺键
      expect(screen.getByText(/加工: edgeType: 卷边/)).toBeInTheDocument()
      expect(screen.queryByText(/加工:.*craft/)).toBeNull()
    })

    it('缺值不渲染：无工艺键时无「工艺规格」块，且不出现 undefined/null/NaN', () => {
      const { container } = render(
        <OrderItemList
          items={[
            makeItem({
              processingInfo: { colorName: '米白', craft: null, openCount: null, style: '' },
            }),
          ]}
        />
      )
      expect(screen.queryByText('工艺规格')).toBeNull()
      expect(screen.queryByText('工艺')).toBeNull()
      expect(screen.queryByText('打开方式')).toBeNull()
      expect(container.textContent).not.toMatch(/undefined|null|NaN/)
    })
  })
})
