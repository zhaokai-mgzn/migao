// @vitest-environment jsdom
// case_ids: UI-019, UI-030
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'

/**
 * ShipOrder 加工单前置守卫（issue #3889）：
 * 含加工项且加工单未完成 → 渲染明确阻断说明，不再渲染发货表单（不再等提交才被后端拦）。
 * 守卫口径与后端 assertProcessingCompletedBeforeShip（countCompleted==0 拦截）一致。
 */

const mockGetOrder = vi.fn()
const mockPODetail = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    getOrder: (...args: any[]) => mockGetOrder(...args),
  },
  processingOrderApi: {
    detail: (...args: any[]) => mockPODetail(...args),
  },
  // 客户常用物流档案带出（issue #4419）：本文件不关心带出结果，给个「查不到客户」的空响应
  customerApi: {
    getCustomers: vi.fn().mockResolvedValue({ data: { data: { items: [], total: 0 } } }),
  },
}))

vi.mock('@/lib/use-route-id', () => ({
  useRouteId: () => 'po-order-1',
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/store/auth', () => ({
  useAuthStore: (selector: any) => selector({ user: { id: 'u-1', name: '王五' } }),
}))

import ShipOrder from '@/app/(dashboard)/orders/[id]/ship/ShipOrder'

const mockOrder = {
  id: 'po-order-1',
  orderNo: 'MG-PO-1',
  status: 'producing',
  customerName: '李四',
  customerPhone: '13900139000',
  customerAddress: '上海市浦东新区',
  actualAmount: 3500,
  items: [
    {
      id: 'item1',
      productId: 'prod1',
      productName: '遮光窗帘',
      // issue #6882：夹具按**真 wire 形态**（详情响应只有 `skuCode`；颜色/门幅在 processingInfo 里）。
      // 改前这里写的是 `productCode` / `color` / `specification` —— 三个键响应里都没有 ⇒
      // 夹具替纸面「补上」了不存在的键，真单上那三格恒 `-` 而判据照样绿。
      skuCode: 'SKU-001',
      unitPrice: 175,
      quantity: 20,
      amount: 3500,
      subtotal: 3500,
      processingInfo: { colorName: '米白', doorWidth: '2.8米' },
    },
  ],
  processingItems: [{ name: '打孔', quantity: 2 }],
}

const po = (status: string) => ({
  id: 'po-1',
  orderId: 'po-order-1',
  processingOrderNo: 'JG-PO-1',
  status,
  items: [],
})

/**
 * issue #6882：发货页商品表的「商品货号 / 颜色 / 门幅」三列必须印**真值**。
 * 改前读 `row.productCode` / `row.color` / `row.specification` —— 三个键都不在详情响应里 ⇒
 * 三列恒 `-`（判据若只断言「有这一列」就会恒绿）。本用例逐格判真值，改回旧写法必红。
 */
describe('ShipOrder 商品表：货号 / 颜色 / 门幅 印真值（issue #6882）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetOrder.mockResolvedValue({ data: { data: mockOrder } })
    mockPODetail.mockResolvedValue({ data: { data: po('completed') } })
  })

  it('三格取 skuCode / processingInfo.colorName / processingInfo.doorWidth，且表头是「门幅」', async () => {
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText('SKU-001')).toBeInTheDocument()
    })
    // 逐格判「同一行里」的真值（不用全局 `getByText`：颜色值可能在全页别处也出现）
    const row = screen.getByText('SKU-001').closest('tr') as HTMLElement
    expect(within(row).getByText('米白')).toBeInTheDocument()
    expect(within(row).getByText('2.8米')).toBeInTheDocument()
    expect(screen.getByText('门幅')).toBeInTheDocument()
    // 表头不再是那个读不到值的「规格尺寸」
    expect(screen.queryByText('规格尺寸')).not.toBeInTheDocument()
  })
})

describe('ShipOrder 加工单前置守卫', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetOrder.mockResolvedValue({ data: { data: mockOrder } })
  })

  it('含加工项且加工单未完成 → 渲染阻断说明、不渲染发货表单', async () => {
    mockPODetail.mockResolvedValue({ data: { data: po('issued') } })
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText(/须先完成加工单后再发货/)).toBeInTheDocument()
    })
    expect(screen.getByText('返回订单详情')).toBeInTheDocument()
    expect(screen.queryByText('确认发货')).not.toBeInTheDocument()
    expect(screen.queryByText('确认物流')).not.toBeInTheDocument()
  })

  it('含加工项但加工单查询失败/不存在 → 同样阻断（与后端 countCompleted==0 口径一致）', async () => {
    mockPODetail.mockRejectedValue(new Error('404'))
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText(/须先完成加工单后再发货/)).toBeInTheDocument()
    })
  })

  it('含加工项且加工单已完成 → 正常渲染发货表单', async () => {
    mockPODetail.mockResolvedValue({ data: { data: po('completed') } })
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText('确认发货')).toBeInTheDocument()
    })
    expect(screen.queryByText(/须先完成加工单后再发货/)).not.toBeInTheDocument()
  })

  it('无加工项订单不查询加工单、直接渲染发货表单', async () => {
    mockGetOrder.mockResolvedValue({ data: { data: { ...mockOrder, processingItems: [] } } })
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText('确认发货')).toBeInTheDocument()
    })
    expect(mockPODetail).not.toHaveBeenCalled()
  })
})
