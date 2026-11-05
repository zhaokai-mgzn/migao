// case_ids: MC-216, MC-217
/**
 * 发货页「取号」按钮 —— **能力位驱动**（issue #8698 P0；口径 §3-2 / §3-5）。
 *
 * 三条判据（都能红）：
 * 1. **不能取号 ⇒ 禁用 + 说清原因**（未接入取号 / 读不到能力位都走这里），
 *    红证：把 `waybillCapabilityFor` 改成恒 `canCreate=true` ⇒ 本组红；
 * 2. **能取号 ⇒ 可点**，点完只把运单号回填输入框，**不调发货端点**（取号 ≠ 发货），
 *    红证：在 `handleCreateWaybill` 里加一句 `productionApi.shipOrder(...)` ⇒ 判据 2 红；
 * 3. **能力面读失败 ⇒ 仍禁用**（fail-closed），不因为"没读到"就当成"能取号"。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { WaybillCapabilities } from '@/types/waybill'

const mockGetOrder = vi.fn()
const mockShipOrder = vi.fn()
const mockGetCustomers = vi.fn()
const mockProcessingOrderDetail = vi.fn()
const mockGetCapabilities = vi.fn()
const mockCreateWaybill = vi.fn()
const mockToastSuccess = vi.fn()
const mockToastError = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: { getOrder: (...args: any[]) => mockGetOrder(...args) },
  productionApi: { shipOrder: (...args: any[]) => mockShipOrder(...args) },
  customerApi: { getCustomers: (...args: any[]) => mockGetCustomers(...args) },
  processingOrderApi: { detail: (...args: any[]) => mockProcessingOrderDetail(...args) },
}))

vi.mock('@/lib/api-waybill', () => ({
  waybillApi: {
    getCapabilities: (...args: any[]) => mockGetCapabilities(...args),
    createWaybill: (...args: any[]) => mockCreateWaybill(...args),
    saveCarrier: vi.fn(),
  },
}))

vi.mock('@/lib/use-route-id', () => ({ useRouteId: () => 'test-order-456' }))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))
vi.mock('sonner', () => ({
  toast: {
    success: (...args: any[]) => mockToastSuccess(...args),
    error: (...args: any[]) => mockToastError(...args),
  },
}))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector: any) => selector({ user: { id: 'u-1', name: '王五' } }),
}))

const mockOrder = {
  id: 'test-order-456',
  orderNo: 'MG202606002',
  status: 'pending_shipment',
  customerName: '李四',
  customerPhone: '13900139000',
  customerAddress: '上海市浦东新区张江路 1 号 2 幢',
  actualAmount: 3500,
  // 承运商 = 顺丰（能力位判定的输入；名字与服务端注册表 displayName 逐字对齐）
  logisticsType: 'express',
  logisticsCompany: '顺丰速运',
  items: [
    {
      id: 'item2',
      productId: 'prod2',
      productName: '遮光窗帘',
      productCode: 'SKU-002',
      unitPrice: 175,
      quantity: 20,
      amount: 3500,
    },
  ],
  processingItems: [],
  work_order_kind: null,
}

import ShipOrder from '@/app/(dashboard)/orders/[id]/ship/ShipOrder'

const manual = {
  code: 'manual',
  displayName: '手填单号',
  logisticsType: null,
  trackQueryCode: null,
  canCreate: false,
  canCancel: false,
  canTrack: false,
  mode: 'manual' as const,
}

function capabilitiesFor(canCreate: boolean): WaybillCapabilities {
  const sf = {
    code: 'sf',
    displayName: '顺丰速运',
    logisticsType: 'express' as const,
    trackQueryCode: 'SF',
    canCreate,
    canCancel: false,
    canTrack: false,
    mode: canCreate ? ('api' as const) : ('manual' as const),
  }
  return {
    carriers: [manual, sf],
    configuredCarrier: 'sf',
    effectiveCarrier: sf,
    manualFallback: !canCreate,
  }
}

describe('发货页取号按钮（issue #8698 P0：能力位驱动）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetOrder.mockResolvedValue({ data: { data: mockOrder } })
    mockGetCustomers.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
    mockShipOrder.mockResolvedValue({ data: { data: { status: 'shipped' } } })
  })

  it('判据 1：承运商未接入取号 ⇒ 按钮禁用 + 提示手填', async () => {
    mockGetCapabilities.mockResolvedValue({ data: { data: capabilitiesFor(false) } })

    render(<ShipOrder />)

    const button = await screen.findByTestId('ship-waybill-create')
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(true))
    expect((button as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByTestId('ship-waybill-hint').textContent).toContain('未接入取号')
    expect(screen.getByTestId('ship-waybill-hint').textContent).toContain('手填单号')
  })

  it('判据 3：能力位读失败 ⇒ 仍禁用（fail-closed，不把「没读到」当「能取号」）', async () => {
    mockGetCapabilities.mockRejectedValue(new Error('network down'))

    render(<ShipOrder />)

    const button = await screen.findByTestId('ship-waybill-create')
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(true))
    expect(screen.getByTestId('ship-waybill-hint').textContent).toContain('请手填单号')
  })

  it('判据 2：能取号 ⇒ 可点；点完只回填运单号，**不调发货端点**（取号 ≠ 发货）', async () => {
    mockGetCapabilities.mockResolvedValue({ data: { data: capabilitiesFor(true) } })
    mockCreateWaybill.mockResolvedValue({ data: { data: { trackingNo: 'SF0001', carrierCode: 'sf', carrierName: '顺丰速运' } } })

    render(<ShipOrder />)

    const button = await screen.findByTestId('ship-waybill-create')
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false))
    await userEvent.click(button)

    await waitFor(() => expect(mockCreateWaybill).toHaveBeenCalledTimes(1))
    expect(mockCreateWaybill.mock.calls[0][0]).toBe('test-order-456')
    // 运单号回填到既有输入框（人工仍需点「确认发货」）
    const input = await screen.findByPlaceholderText('请输入快递单号')
    await waitFor(() => expect((input as HTMLInputElement).value).toBe('SF0001'))
    // 🔴 取号成功后**没有**发货调用：订单状态不变（判据 1 的前端半边）
    expect(mockShipOrder).not.toHaveBeenCalled()
    expect(mockToastSuccess).toHaveBeenCalledWith(expect.stringContaining('仍需点「确认发货」'))
  })
})
