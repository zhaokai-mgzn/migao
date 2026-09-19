// case_ids: OR-034
// 原声明 `OR-001, UI-020` 是**借用式**（issue #4431 B7 核实并替换）：OR-001 是订单列表查询、
// UI-020 是订单列表「采购明细」的**加工费**展示 —— 两条都不覆盖本文件被测行为（工艺规格展示）。
// 改用 **OR-034**（本 PR 新增，判据即本文件 + craft-display.test.ts）。
// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'

/**
 * 订单详情「商品明细」表展示工艺规格（issue #4355 / 设计文档 §4.9 ② 订单）。
 *
 * 真值来源 = `order_items.processing_info`（camelCase，§4.5），**直读不二次推导**；
 * 缺值不渲染（键缺席 / null / 空串 ⇒ 该行不出现，绝不出现 undefined/null/NaN）。
 */

const mockGetOrder = vi.fn()
const mockPODetail = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    getOrder: (...args: any[]) => mockGetOrder(...args),
    closeOrder: vi.fn(),
    confirmPayment: vi.fn(),
    updateOrderStatus: vi.fn(),
    updateLogistics: vi.fn(),
    refundOrder: vi.fn(),
  },
  processingOrderApi: {
    detail: (...args: any[]) => mockPODetail(...args),
  },
}))

vi.mock('@/lib/use-route-id', () => ({
  useRouteId: () => 'od-order-1',
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import OrderDetailPage from '@/app/(dashboard)/orders/[id]/OrderDetail'

const orderWith = (processingInfo: Record<string, unknown> | null) => ({
  id: 'od-order-1',
  orderNo: 'MG-OD-1',
  status: 'producing',
  customerName: '张三',
  customerPhone: '13800138000',
  customerAddress: '北京市朝阳区',
  totalAmount: 1999,
  discountAmount: 0,
  actualAmount: 1999,
  createdAt: '2026-06-20T10:00:00Z',
  items: [
    {
      id: 'item1',
      productId: 'prod1',
      productName: '测试窗帘布',
      sku: 'TEST-SKU-001',
      unitPrice: 99.5,
      quantity: 20,
      subtotal: 1990,
      processingInfo,
    },
  ],
  processingItems: [],
})

describe('OrderDetail 商品明细展示工艺规格', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockPODetail.mockResolvedValue({ data: { data: null } })
  })

  it('渲染工艺规格：部位/工艺/加工类型/打开方式/是否定型/款式/特殊选项（§4.9 ②）', async () => {
    mockGetOrder.mockResolvedValue({
      data: {
        data: orderWith({
          colorName: '米白',
          sellingMethod: 'bulk_cut',
          doorWidth: '2.8米',
          curtainType: '布帘',
          craft: '韩褶',
          cuttingMode: '定高买宽',
          openCount: 2,
          isShaped: true,
          style: '拼色',
          specialOptions: ['加铅线', '双褶'],
        }),
      },
    })

    render(<OrderDetailPage />)

    // 断言限定在商品明细表的规格块内（发货单 ShipmentDoc 也渲染同一商品名，全页查询会歧义）
    const spec = await screen.findByTestId('order-craft-spec')
    expect(within(spec).getByText('韩褶')).toBeInTheDocument()
    expect(within(spec).getByText('定高买宽')).toBeInTheDocument()
    expect(within(spec).getByText('双开')).toBeInTheDocument()
    expect(within(spec).getByText('拼色')).toBeInTheDocument()
    expect(within(spec).getByText('加铅线、双褶')).toBeInTheDocument()
    expect(within(spec).getByText('布帘')).toBeInTheDocument()
    // 「是否定型」= 是（按行断言，避免与其它「是」歧义）
    expect(within(spec).getByText('是否定型').parentElement?.textContent).toContain('是')
    // 既有的销售信息（色号/方式/门幅）不受影响
    expect(screen.getByText('米白')).toBeInTheDocument()
    expect(screen.getByText(/门幅2\.8米/)).toBeInTheDocument()
  })

  it('渲染算料口径：总褶数/折数（每片）/褶距/幅数/褶倍/米数/是否对花/花距（§4.9 ②）', async () => {
    mockGetOrder.mockResolvedValue({
      data: {
        data: orderWith({
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
        }),
      },
    })

    render(<OrderDetailPage />)

    const spec = await screen.findByTestId('order-craft-spec')
    expect(within(spec).getByText('52')).toBeInTheDocument()
    expect(within(spec).getByText('26')).toBeInTheDocument()
    expect(within(spec).getByText('0.1米')).toBeInTheDocument()
    expect(within(spec).getByText('4')).toBeInTheDocument()
    expect(within(spec).getByText('2 倍')).toBeInTheDocument()
    expect(within(spec).getByText('1.86 倍')).toBeInTheDocument()
    // 面料米数 / 加工费米数 = §4.9 要求的**两个字段**（§6.1 口径拆两值）⇒ 同值时出现两次
    expect(within(spec).getAllByText('13.3米')).toHaveLength(2)
    expect(within(spec).getByText('是否对花')).toBeInTheDocument()
    expect(within(spec).getByText('0.32米')).toBeInTheDocument()
  })

  it('缺值不渲染：无工艺键 / null / 空串 ⇒ 无「工艺规格」块，且不出现 undefined/null/NaN', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: orderWith({ colorName: '米白', craft: null, openCount: null, style: '' }) },
    })

    const { container } = render(<OrderDetailPage />)

    // 发货单 ShipmentDoc 也渲染同一商品名 ⇒ 用 findAllByText 等待（不假定唯一）
    await waitFor(() => expect(screen.getAllByText('测试窗帘布').length).toBeGreaterThan(0))
    expect(screen.queryAllByTestId('order-craft-spec')).toHaveLength(0)
    expect(screen.queryByText('工艺规格')).toBeNull()
    expect(screen.queryByText('加工类型')).toBeNull()
    expect(screen.queryByText('打开方式')).toBeNull()
    expect(container.textContent).not.toMatch(/undefined|null|NaN/)
  })

  it('processingInfo=null（存量单形态）时页面正常渲染且无工艺块', async () => {
    mockGetOrder.mockResolvedValue({ data: { data: orderWith(null) } })

    render(<OrderDetailPage />)

    // 发货单 ShipmentDoc 也渲染同一商品名 ⇒ 用 findAllByText 等待（不假定唯一）
    await waitFor(() => expect(screen.getAllByText('测试窗帘布').length).toBeGreaterThan(0))
    expect(screen.queryAllByTestId('order-craft-spec')).toHaveLength(0)
  })
})
