// case_ids: PR-079
//
// PR-079（issue #5177）：订单页上的**加急 / 要求到货日**字段（建单写面 + 列表读面）。
//
// 本文件守**判据 2「缺省不变」**，它是本单最容易做错、也最难被发现的一条：
//   不填 / 不勾 ⇒ 请求体里**不得出现这两个键**（或传 null）；
//   页面显示为「不加急 / 未指定」；**不得默认勾上加急**。
//
// 为什么必须断言**请求体**而不是「页面上有个控件」：控件在、键也在（值是 `false`/`null`）
// 是能过「有个开关」那类空断言的 —— 但它把「没填」变成了「显式不加急 / 未指定」，
// 与后端列缺省语义（`NOT NULL DEFAULT FALSE` / `NULL`）产生一个**前端编造的事实**。
// 红证：把提交体改成 `isUrgent: isUrgent`（无条件带键）⇒ 第一条立刻红。
//
// 列表半边断言**用户可见结果**（列表行真的显示加急徽标与到货日），不是「API 被调用过」。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'

const mockCreateOrder = vi.fn()
const mockGetOrders = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProcessingItems = vi.fn()
const mockGetCustomers = vi.fn()
const mockGetCraftCalcConfig = vi.fn()
/** 自动特征判定（issue #4976 包 2b）：挂载即请求，判定缺席会被提交闸门拦住 */
const mockAutoFeaturesPreview = vi.fn((_params?: unknown) =>
  Promise.resolve({
    data: { data: { auto_features: [], door_width: null, fullness_used: 2.0, notice: 'missing-door-width' } },
  }),
)

const CALC_CONFIG_OK = {
  data: {
    data: {
      source: 'stored',
      config: {
        per_fold_single: 0.25,
        per_fold_mixed_times: {},
        margin_single: 0.3,
        margin_multi: 0.3,
        min_fullness: 1.5,
        tiers: { standard: { fullness: 2.0, label: '标准档（2.0倍）' } },
        default_formula: 'pleat',
        meters_rounding_step: 0.1,
      },
    },
  },
}

vi.mock('@/lib/api', () => ({
  orderApi: {
    createOrder: (...a: any[]) => mockCreateOrder(...a),
    getOrders: (...a: any[]) => mockGetOrders(...a),
  },
  productApi: {
    getProducts: (...a: any[]) => mockGetProducts(...a),
    getProduct: (...a: any[]) => mockGetProduct(...a),
  },
  processingItemApi: { getProcessingItems: (...a: any[]) => mockGetProcessingItems(...a) },
  customerApi: { getCustomers: (...a: any[]) => mockGetCustomers(...a) },
  // 算料试算与本单正交 ⇒ 让它停在「进行中」（与 orders-new.test.tsx 同口径）
  craftCalcApi: { preview: () => new Promise(() => {}) },
  autoFeaturesApi: { preview: (p: unknown) => mockAutoFeaturesPreview(p) },
  feePreviewApi: {
    preview: (payload: any) =>
      Promise.resolve({
        data: {
          data: {
            items: (payload?.items ?? []).map(() => ({ processingFee: 0, processingFeeDetail: null })),
            processingFeeTotal: 0,
          },
        },
      }),
  },
  productionApi: { getCraftCalcConfig: (...a: any[]) => mockGetCraftCalcConfig(...a) },
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), loading: vi.fn(), dismiss: vi.fn() },
}))

import NewOrderPage from '@/app/(dashboard)/orders/new/page'
import OrdersPage from '@/app/(dashboard)/orders/page'

const ok = (data: unknown) => ({ data: { data } })

describe('新建订单页 · 加急 / 到货日（PR-079 判据 2：缺省不变）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockCreateOrder.mockResolvedValue(ok({ id: 'o-new' }))
    mockGetProducts.mockResolvedValue(ok({ items: [{ id: 'p9', name: '测试9999', price: 9 }], total: 1 }))
    mockGetProduct.mockResolvedValue(ok({ id: 'p9', name: '测试9999', skus: [], price: 9 }))
    mockGetProcessingItems.mockResolvedValue(ok({ items: [] }))
    mockGetCustomers.mockResolvedValue(ok({ items: [], total: 0 }))
    mockGetCraftCalcConfig.mockResolvedValue(CALC_CONFIG_OK)
  })

  /** 加一行商品（含必填的窗宽/窗高与用料米数）—— 否则提交被逐行校验拦住 */
  const addOneProduct = async () => {
    fireEvent.click(await screen.findByText('点击搜索并选择商品'))
    fireEvent.click(await screen.findByText('测试9999'))
    await screen.findByText('窗宽 (米)')
    const withLabel = (label: string) =>
      screen.getAllByText(label).map((el) => el.closest('div')!.querySelector('input') as HTMLInputElement)
    fireEvent.change(withLabel('窗宽 (米)')[0], { target: { value: '6.6' } })
    fireEvent.change(withLabel('窗高 (米)')[0], { target: { value: '2.6' } })
    const meters = (await screen.findByText('用料米数')).closest('div')!.querySelector('input') as HTMLInputElement
    fireEvent.change(meters, { target: { value: '20' } })
  }

  const fillCustomerAndSubmit = async () => {
    fireEvent.change(screen.getByPlaceholderText('请输入收货人姓名'), { target: { value: '张三' } })
    fireEvent.change(screen.getByPlaceholderText('请输入 11 位手机号'), { target: { value: '13800138000' } })
    fireEvent.change(screen.getByPlaceholderText('请输入详细收货地址'), { target: { value: '杭州市' } })
    // 计价 / 自动识别两道提交闸门：等它们落地（真实商家也是看到金额才提交）
    await waitFor(() => expect(screen.queryByText(/加工费计价中/)).toBeNull())
    try {
      await waitFor(() => expect(mockAutoFeaturesPreview).toHaveBeenCalled(), { timeout: 3000 })
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0))
      })
    } catch {
      // 本用例没有可判定的行 ⇒ 本就没有判定请求
    }
    fireEvent.click(screen.getByText('提交订单'))
  }

  it('🔴 不勾不填 ⇒ 请求体里**没有** `isUrgent` / `requiredDeliveryDate` 两个键', async () => {
    render(<NewOrderPage />)
    await screen.findByText('新增订单')

    // 页面显示 = 不加急 / 未指定（不默认勾上）—— 非空断言的前提
    // 加急开关 = `role="switch"` 的按钮 ⇒ 状态读 `aria-checked`
    expect(screen.getByLabelText('加急')).toHaveAttribute('aria-checked', 'false')
    expect((screen.getByLabelText('要求到货日') as HTMLInputElement).value).toBe('')

    await addOneProduct()
    await fillCustomerAndSubmit()

    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
    const body = mockCreateOrder.mock.calls[0][0]
    // 🔴 键**不存在**（不是 `false` / `null`）—— 「没填」与「显式不加急」必须能区分
    expect(Object.prototype.hasOwnProperty.call(body, 'isUrgent')).toBe(false)
    expect(Object.prototype.hasOwnProperty.call(body, 'requiredDeliveryDate')).toBe(false)
    // 反向断言：这一单确实提交成功了（否则上面两条会因「压根没提交」而空跑通过）
    expect(body.customerName).toBe('张三')
    expect(body.items).toHaveLength(1)
  })

  it('勾上加急 + 填到货日 ⇒ 请求体带 `isUrgent: true` 与 `YYYY-MM-DD`（与售后 priority 无关）', async () => {
    render(<NewOrderPage />)
    await screen.findByText('新增订单')

    fireEvent.click(screen.getByLabelText('加急'))
    fireEvent.change(screen.getByLabelText('要求到货日'), { target: { value: '2026-10-01' } })

    await addOneProduct()
    await fillCustomerAndSubmit()

    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
    const body = mockCreateOrder.mock.calls[0][0]
    expect(body.isUrgent).toBe(true)
    expect(body.requiredDeliveryDate).toBe('2026-10-01')
    // 零联动：请求体里不得出现任何售后字段名
    expect(Object.prototype.hasOwnProperty.call(body, 'priority')).toBe(false)
    expect(Object.prototype.hasOwnProperty.call(body, 'priorityLevel')).toBe(false)
  })
})

describe('订单列表页 · 加急徽标 / 到货日（PR-079 读面）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetOrders.mockResolvedValue(
      ok({
        items: [
          {
            id: 'o-urgent',
            orderNo: 'MG-URG-1',
            status: 'pending_shipment',
            totalAmount: 100,
            actualAmount: 100,
            customerName: '王五',
            customerPhone: '13900139000',
            hasProcessing: false,
            createdAt: '2026-09-20T10:00:00Z',
            items: [],
            // 服务端读面新增的两个键
            isUrgent: true,
            requiredDeliveryDate: '2026-09-30',
          },
          {
            id: 'o-normal',
            orderNo: 'MG-NRM-1',
            status: 'pending_shipment',
            totalAmount: 200,
            actualAmount: 200,
            customerName: '李六',
            customerPhone: '13700137000',
            hasProcessing: false,
            createdAt: '2026-09-21T10:00:00Z',
            items: [],
            isUrgent: false,
            requiredDeliveryDate: null,
          },
        ],
        total: 2,
      }),
    )
  })

  it('列表行显示服务端下发的加急徽标与到货日；非加急单显示「不加急 / 未指定」', async () => {
    render(<OrdersPage />)

    // 真实 OrderTable 渲染（本文件**不**替身 @/components/orders）
    await waitFor(() => expect(screen.getByTestId('order-urgent-o-urgent')).toBeInTheDocument())

    expect(screen.getByTestId('order-urgent-o-urgent').textContent).toBe('加急')
    expect(screen.getByTestId('order-delivery-o-urgent')).toHaveTextContent('2026-09-30')
    // 反向：另一单不是加急（同一份响应的逐单取值，不是整表一个值）
    expect(screen.getByTestId('order-urgent-o-normal').textContent).toBe('不加急')
    expect(screen.getByTestId('order-delivery-o-normal')).toHaveTextContent('未指定')
  })
})
