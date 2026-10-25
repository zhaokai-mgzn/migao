// case_ids: WH-004
//
// V194（issue #7750）：出库单页面的**可达性**判据 —— 与后端 WH-004 配对。
//
// 守四件事：
//   ① 列表能渲染（单号 / 类别 / 来源 / 仓库 / 数量合计），读失败 ≠ 空态（常驻错误 + 重试）；
//   ② 「新建出库单」受 `inbound:create` 门控；提交体里 SKU id 是**字符串**（雪花号不许 Number()）；
//   ③ 提交成功后提示「已出库」（出库单无草稿态、无过账按钮）；
//   ④ 「成品库存」页签显示**仓位号**（打包时自动分配的成品仓仓位）。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const authMock = vi.hoisted(() => ({
  state: {
    user: { id: '1', username: 'admin', name: '管理员', permissions: ['*'] as string[], roles: [] as string[] },
  },
}))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) =>
    typeof selector === 'function' ? selector(authMock.state) : authMock.state,
}))

const mockList = vi.fn()
const mockDetail = vi.fn()
const mockCreate = vi.fn()
const mockFinished = vi.fn()
const mockWarehouses = vi.fn()

vi.mock('@/lib/api', () => ({
  outboundOrderApi: {
    list: (...a: unknown[]) => mockList(...a),
    detail: (...a: unknown[]) => mockDetail(...a),
    create: (...a: unknown[]) => mockCreate(...a),
  },
  finishedGoodsApi: {
    listInStock: (...a: unknown[]) => mockFinished(...a),
    locations: vi.fn(),
    finishedWarehouse: vi.fn(),
  },
  warehouseApi: {
    list: (...a: unknown[]) => mockWarehouses(...a),
  },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// SKU 选择器替换成两个真实按钮：只验「勾选 → 明细行 → 提交体」这一段接线，
// 不复测选择器自身的搜索/防抖（那由 SkuPicker.test.tsx 守）。
vi.mock('@/components/products/SkuPicker', () => ({
  default: ({
    selectedSkuIds,
    onToggle,
  }: {
    selectedSkuIds: readonly string[]
    onToggle: (choice: {
      product: { id: string; name: string }
      sku: { id: string; colorName: string; doorWidth: string }
    }) => void
  }) => (
    <div>
      <button
        type="button"
        data-testid="pick-sku"
        onClick={() =>
          onToggle({
            product: { id: 'prod-1', name: '遮光布' },
            sku: { id: '2097126615461462018', colorName: '米白', doorWidth: '2.8' },
          })
        }
      >
        勾选 SKU（已选 {selectedSkuIds.length}）
      </button>
    </div>
  ),
  skuLineLabel: (product: { name: string }, sku: { colorName: string; doorWidth: string }) =>
    `${product.name} / ${sku.colorName} / ${sku.doorWidth}`,
}))

import OutboundOrdersPage from '@/app/(dashboard)/outbound-orders/page'

const orderRow = {
  id: 'ck-1',
  outboundNo: 'CK-20261025-0001',
  bizCategory: 'fabric',
  source: 'manual',
  warehouse: '主仓',
  outboundDate: '2026-10-25',
  status: 'posted',
  totalAmount: 62.5,
  orderId: null,
  orderNo: null,
  itemCount: 1,
  totalQuantity: 5,
  items: [],
}

const finishedRow = {
  id: 1,
  binCode: 'A-01',
  orderId: 'order-1',
  orderNo: 'DD-20261025-0001',
  orderItemId: 'item-1',
  productName: '遮光布帘',
  quantity: 1,
  unit: 'set',
  status: 'in_stock',
  inboundOrderId: 'RK-20261025-0001',
}

beforeEach(() => {
  vi.clearAllMocks()
  authMock.state.user.permissions = ['*']
  mockList.mockResolvedValue({ data: { data: [orderRow] } })
  mockDetail.mockResolvedValue({ data: { data: orderRow } })
  mockCreate.mockResolvedValue({ data: { data: orderRow } })
  mockFinished.mockResolvedValue({ data: { data: [finishedRow] } })
  mockWarehouses.mockResolvedValue({ data: { data: [{ id: 1, code: 'MAIN', name: '主仓' }] } })
})

describe('出库单列表（WH-004）', () => {
  it('渲染列表：单号 / 类别 / 来源 / 仓库 / 数量合计 / 已过账', async () => {
    render(<OutboundOrdersPage />)

    await waitFor(() => expect(screen.getByText('CK-20261025-0001')).toBeTruthy())
    expect(screen.getAllByText('布料').length).toBeGreaterThan(0)
    expect(screen.getByText('手工出库')).toBeTruthy()
    expect(screen.getByText('主仓')).toBeTruthy()
    expect(screen.getByText('已过账')).toBeTruthy()
  })

  it('读失败 ≠ 空态：显示常驻错误出口，点重试再读一次', async () => {
    mockList.mockRejectedValueOnce(new Error('boom'))
    render(<OutboundOrdersPage />)

    const alert = await screen.findByTestId('outbound-orders-load-error')
    expect(alert.getAttribute('role')).toBe('alert')
    fireEvent.click(screen.getByTestId('outbound-orders-load-error-retry'))
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2))
  })

  it('「新建出库单」受 inbound:create 门控：无该码 ⇒ 不渲染入口', async () => {
    authMock.state.user.permissions = ['inbound:view']
    render(<OutboundOrdersPage />)
    await waitFor(() => expect(mockList).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: /新建出库单/ })).toBeNull()
  })
})

describe('新建出库单 = 建单即过账（WH-004）', () => {
  it('勾选 SKU → 填数量 → 提交：skuId 是字符串原样，成功后提示已出库并刷新', async () => {
    render(<OutboundOrdersPage />)
    await waitFor(() => expect(screen.getByText('CK-20261025-0001')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: /新建出库单/ }))
    fireEvent.click(screen.getByTestId('pick-sku'))
    fireEvent.change(screen.getByPlaceholderText('如 12.5'), { target: { value: '5' } })
    fireEvent.click(screen.getByTestId('outbound-submit'))

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
    const payload = mockCreate.mock.calls[0][0]
    expect(payload.items).toEqual([{ skuId: '2097126615461462018', quantity: 5 }])
    // 雪花号：Number() 会吞末位 ⇒ 提交体里必须是原字符串
    expect(payload.items[0].skuId).not.toBe(String(Number('2097126615461462018')))

    const { toast } = await import('sonner')
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('已出库'))
    // 提交后重新读列表（新单立即可见）
    expect(mockList.mock.calls.length).toBeGreaterThanOrEqual(2)
  })

  it('一行都没有 ⇒ 拒发请求（不给后端发空单）', async () => {
    render(<OutboundOrdersPage />)
    await waitFor(() => expect(screen.getByText('CK-20261025-0001')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: /新建出库单/ }))
    fireEvent.click(screen.getByTestId('outbound-submit'))

    const { toast } = await import('sonner')
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('至少勾选一个 SKU')))
    expect(mockCreate).not.toHaveBeenCalled()
  })

  it('数量超过 1 位小数 ⇒ 前端先拦（与后端同一判据，不静默取整）', async () => {
    render(<OutboundOrdersPage />)
    await waitFor(() => expect(screen.getByText('CK-20261025-0001')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: /新建出库单/ }))
    fireEvent.click(screen.getByTestId('pick-sku'))
    fireEvent.change(screen.getByPlaceholderText('如 12.5'), { target: { value: '1.55' } })
    fireEvent.click(screen.getByTestId('outbound-submit'))

    const { toast } = await import('sonner')
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('1 位小数')),
    )
    expect(mockCreate).not.toHaveBeenCalled()
  })
})

describe('成品库存页签（WH-005）', () => {
  it('显示仓位号 / 品名 / 订单号（打包自动分配的成品仓仓位）', async () => {
    render(<OutboundOrdersPage />)
    await waitFor(() => expect(screen.getByText('CK-20261025-0001')).toBeTruthy())

    fireEvent.click(screen.getByTestId('outbound-tab-finished'))

    await waitFor(() => expect(mockFinished).toHaveBeenCalledTimes(1))
    expect(await screen.findByTestId('finished-bin-code')).toHaveTextContent('A-01')
    expect(screen.getByText('遮光布帘')).toBeTruthy()
    expect(screen.getByText('DD-20261025-0001')).toBeTruthy()
  })

  it('成品仓为空时给空态而不是错误（未打包 ≠ 读取失败）', async () => {
    mockFinished.mockResolvedValue({ data: { data: [] } })
    render(<OutboundOrdersPage />)
    await waitFor(() => expect(screen.getByText('CK-20261025-0001')).toBeTruthy())
    fireEvent.click(screen.getByTestId('outbound-tab-finished'))

    expect(await screen.findByText('成品仓暂时是空的')).toBeTruthy()
  })
})
