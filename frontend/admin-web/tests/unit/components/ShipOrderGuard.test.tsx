// @vitest-environment jsdom
// case_ids: UI-019, UI-030
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

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
      productCode: 'SKU-001',
      unitPrice: 175,
      quantity: 20,
      amount: 3500,
    },
  ],
  processingItems: [{ name: '打孔', unitPrice: 1, quantity: 2, amount: 2 }],
}

const po = (status: string) => ({
  id: 'po-1',
  orderId: 'po-order-1',
  processingOrderNo: 'JG-PO-1',
  status,
  items: [],
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
