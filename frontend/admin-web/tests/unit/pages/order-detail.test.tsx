// case_ids: OR-001, OR-002, OR-003, OR-046, OR-055, UI-024, UI-040, UI-053, UI-076
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { markErrorToastShown } from '@/lib/api-error'

// Mock API
const mockGetOrder = vi.fn()
// 发货读面（issue #5651 收口）：销售单数量列消费的**实发**来源 —— 详情页加载订单时一并取
const mockGetOrderShipments = vi.fn()
const mockConfirmPayment = vi.fn()
const mockRefundOrder = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    getOrder: (...args: any[]) => mockGetOrder(...args),
    getOrderShipments: (...args: any[]) => mockGetOrderShipments(...args),
    closeOrder: vi.fn(),
    confirmPayment: (...args: any[]) => mockConfirmPayment(...args),
    updateOrderStatus: vi.fn(),
    updateLogistics: vi.fn(),
    refundOrder: (...args: any[]) => mockRefundOrder(...args),
  },
}))

// Mock useRouteId
vi.mock('@/lib/use-route-id', () => ({
  useRouteId: () => 'test-order-123',
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock sonner
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import { toast } from 'sonner'

// Mock dayjs
vi.mock('dayjs', () => ({
  default: (date?: string) => ({
    format: () => date || '2026-04-25 10:00',
    diff: () => 3600,
  }),
}))

// Mock child components
vi.mock('@/components/orders', () => ({
  OrderProgressSteps: () => <div data-testid="order-progress">OrderProgressSteps</div>,
  ProcessingOrderBlock: () => <div data-testid="po-block">ProcessingOrderBlock</div>,
  // 订单加急 / 到货日改单控件（issue #5177）：本文件验的是详情页既有区块与操作区，
  // 该控件的判据在 tests/unit/components/OrderUrgencyPanel.test.tsx ⇒ 这里替身成空壳
  // （不替身会让 `@/components/orders` 的 mock 缺该导出 ⇒ 渲染期直接抛）。
  OrderUrgencyPanel: () => <div data-testid="order-urgency-panel">OrderUrgencyPanel</div>,
  // 纸质发货单（issue #3768）：本文件只验证入口按钮，单据内容由 ShipmentDoc.test.tsx 覆盖
  ShipmentDoc: () => <div data-testid="shipment-doc">ShipmentDoc</div>,
  // 纸质报价单（issue #4965）：同上 —— 入口按钮在本文件，纸面内容由 QuotationDoc.test.tsx 覆盖
  QuotationDoc: () => <div data-testid="quotation-doc">QuotationDoc</div>,
  // 纸质加工单（A4，issue #5651）/ 纸质销售单（三联纸 241mm×140mm，issue #5651）：同上 ——
  // 入口按钮在本文件，纸面内容由 ProcessingDoc.test.tsx / SalesDoc.test.tsx 覆盖。
  // ⚠️ `@/components/orders` 的 mock 少一个导出 ⇒ 渲染期直接抛（同 OrderUrgencyPanel 那条注释）
  ProcessingDoc: () => <div data-testid="processing-doc">ProcessingDoc</div>,
  SalesDoc: () => <div data-testid="sales-doc">SalesDoc</div>,
  CloseOrderModal: ({ open }: any) => open ? <div data-testid="close-modal">CloseModal</div> : null,
  LogisticsForm: ({ open }: any) => open ? <div data-testid="logistics-form">LogisticsForm</div> : null,
  RefundOrderModal: ({ open, onConfirm }: any) =>
    open ? (
      <div data-testid="refund-modal" role="dialog">
        <button data-testid="confirm-refund-detail" onClick={() => onConfirm({ refundAmount: 500, refundReason: '质量问题' })}>
          确认退款
        </button>
      </div>
    ) : null,
  // 修改订单（issue #5842）：本文件只验**入口**（哪个状态显示按钮、点开是否挂载弹窗）；
  // 弹窗自身的判据（改明细 / 加工项 / 金额服务端重算）在
  // tests/unit/components/EditOrderContentModal.test.tsx。
  EditOrderContentModal: ({ open }: any) =>
    open ? <div data-testid="edit-order-content-modal">EditOrderContentModal</div> : null,
}))

import OrderDetailPage from '@/app/(dashboard)/orders/[id]/OrderDetail'

const mockOrder = {
  id: 'test-order-123',
  orderNo: 'MG202606001',
  status: 'pending_shipment',
  customerName: '张三',
  customerPhone: '13800138000',
  customerAddress: '北京市朝阳区xx小区',
  totalAmount: 1999,
  discountAmount: 0,
  actualAmount: 1999,
  createdAt: '2026-06-20T10:00:00Z',
  paidAt: '2026-06-20T10:30:00Z',
  items: [
    {
      id: 'item1',
      productId: 'prod1',
      productName: '测试窗帘布',
      sku: 'TEST-SKU-001',
      unitPrice: 99.5,
      quantity: 20,
      subtotal: 1990,
      processingInfo: null,
    },
  ],
  processingItems: [],
}

describe('OrderDetailPage', () => {
  // `window.print` 用 `vi.spyOn` 注入，并在**创建它的那个用例里** `printSpy.mockRestore()` 还原。
  //
  // 反例一（#4768 之前）：`window.print = vi.fn() as any` —— **直接赋值** jsdom 的 `window.print`
  // 且从不还原 ⇒ 泄漏到同文件后续用例，让「打印没被调用」这类断言恒真/恒假。
  // 🔴 反例二（#4768 的写法，**本单修的就是它**）：`afterEach(() => vi.restoreAllMocks())` ——
  // 它对**每一个**注册过的 mock 调 `mockRestore()`（= `mockReset()` + `state.restore()`），
  // 而 `mockReset()` 会 `implementation = undefined` ⇒ **本文件的 `vi.fn()` 替身
  // （mockGetOrder / mockConfirmPayment / mockRefundOrder）被清成「返回 undefined」**。
  // 而 RTL 的 `cleanup()` 也在 `afterEach` 且**本文件先跑**（实测：那一刻组件**尚未卸载**）
  // ⇒ 存在「替身已清空、组件仍挂载」的窗口：组件 effect 只要在这个窗口里再跑一次，
  // 页面拿到 `undefined` ⇒ `undefined.then` 同步抛 ⇒ 组件崩 ⇒ **本文件任意用例随机红**、
  // **卡住前端部署**（CI 实测：`ShipOrder.tsx:154`，`deploy-frontend.yml` 的「Unit tests」步）。
  // ⇒ 只还原**自己创建的那个 spy**，不做文件级清场（issue #4773；同根因见 #4496 / #4497）。

  beforeEach(() => {
    vi.clearAllMocks()
    mockGetOrder.mockResolvedValue({
      data: { data: mockOrder },
    })
    // 发货读面：默认给「未发货」（空发货单）—— 本文件验的是页面既有区块；三态纸面判据在
    // tests/unit/components/SalesDoc.test.tsx（此处只要形状对得上，不让它抛）
    mockGetOrderShipments.mockResolvedValue({
      data: { data: { order_id: 'test-order-123', status: 'producing', shipments: [] } },
    })
  })

  it('should show loading state initially', () => {
    render(<OrderDetailPage />)
    // Loading should show before data resolves
    expect(screen.getByText('加载订单详情...')).toBeInTheDocument()
  })

  it('should render page title after loading', async () => {
    render(<OrderDetailPage />)
    // 使用 findByText 内置 waitFor 避免竞态
    const heading = await screen.findAllByText('订单详情')
    expect(heading.length).toBeGreaterThanOrEqual(1)
  })

  it('should render breadcrumb navigation', async () => {
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('首页')).toBeInTheDocument()
      expect(screen.getByText('订单列表')).toBeInTheDocument()
    })
  })

  it('should render basic info section', async () => {
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('基础信息')).toBeInTheDocument()
      expect(screen.getByText('MG202606001')).toBeInTheDocument()
    })
  })

  it('should render customer info section', async () => {
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('收货信息')).toBeInTheDocument()
      expect(screen.getByText('张三')).toBeInTheDocument()
    })
  })

  it('should render product info section', async () => {
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('商品信息')).toBeInTheDocument()
    })
  })

  it('should show empty state when order not found', async () => {
    mockGetOrder.mockResolvedValue({ data: { data: null } })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('订单不存在或已被删除')).toBeInTheDocument()
    })
  })

  it('should render amount summary with discount and actual amount', async () => {
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('实收款')).toBeInTheDocument()
      expect(screen.getByText('优惠金额')).toBeInTheDocument()
    })
  })

  // ===== 退款展示（目标契约：退款不再改变订单状态，refundAmount>0 表示已退款） =====

  it('renders 已退款 badge when refundAmount > 0 (not depending on refund status)', async () => {
    mockGetOrder.mockResolvedValue({
      data: {
        data: {
          ...mockOrder,
          status: 'completed',
          refundAmount: 150,
          refundAt: '2026-06-21T10:00:00Z',
        },
      },
    })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('已退款 ¥150.00')).toBeInTheDocument()
    })
  })

  it('renders 退款时间 in badge when refundAt provided', async () => {
    mockGetOrder.mockResolvedValue({
      data: {
        data: {
          ...mockOrder,
          status: 'completed',
          refundAmount: 150,
          refundAt: '2026-06-21T10:00:00Z',
        },
      },
    })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText(/退款时间：/)).toBeInTheDocument()
    })
  })

  it('amount summary shows 已退款 ¥X row when refundAmount > 0', async () => {
    mockGetOrder.mockResolvedValue({
      data: {
        data: { ...mockOrder, status: 'completed', refundAmount: 150, refundAt: '2026-06-21T10:00:00Z' },
      },
    })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('已退款')).toBeInTheDocument()
      expect(screen.getByText('¥150.00')).toBeInTheDocument()
    })
  })

  it('does NOT render 已退款 when refundAmount is 0 or undefined', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, refundAmount: 0 } },
    })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('商品信息')).toBeInTheDocument()
    })
    expect(screen.queryByText('已退款')).not.toBeInTheDocument()
    expect(screen.queryByText('已退款 ¥0.00')).not.toBeInTheDocument()
  })

  it('renders "-" for missing paidAt/shippedAt/receivedAt (defensive, no crash)', async () => {
    const noTimes = { ...mockOrder, paidAt: undefined, shippedAt: undefined, receivedAt: undefined }
    mockGetOrder.mockResolvedValue({ data: { data: noTimes } })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('基础信息')).toBeInTheDocument()
    })
    // 支付时间 / 发货时间 / 确认收货时间 行均显示占位符 "-"
    for (const label of ['支付时间：', '发货时间：', '确认收货时间：']) {
      const row = screen.getByText(label).parentElement
      expect(row).toBeTruthy()
      expect(row!.textContent).toContain('-')
    }
  })

  // ===== 详情页操作区退款按钮（P1：confirmed/producing/shipped/completed 且未退款） =====

  it('待发货（confirmed）未退款订单操作区显示 退款 按钮', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'confirmed', refundAmount: 0 } },
    })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '退款' })).toBeInTheDocument()
    })
  })

  it('已完成未退款订单操作区显示 退款 按钮', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'completed', refundAmount: 0 } },
    })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '退款' })).toBeInTheDocument()
    })
  })

  // ===== 补打发货单（issue #3768 / UI-040）：发货页有状态守卫进不去，重打只能从详情页 =====

  it('已发货订单操作区显示「打印发货单」且点击真的触发 window.print', async () => {
    // 还原**只针对这一个 spy**（见 describe 头的反例二）：文件级 `restoreAllMocks()` 会连
    // `vi.fn()` 替身的实现一起清掉 ⇒ 页面 effect 命中 `undefined` ⇒ 本文件随机红、卡住部署。
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})
    try {
      mockGetOrder.mockResolvedValue({
        data: { data: { ...mockOrder, status: 'shipped', refundAmount: 0 } },
      })
      render(<OrderDetailPage />)

      const btn = await screen.findByRole('button', { name: /打印发货单/ })
      await userEvent.setup().click(btn)

      expect(printSpy).toHaveBeenCalledTimes(1)
    } finally {
      printSpy.mockRestore()
    }
  })

  it('打印用例跑完后 window.print 必须已还原（否则泄漏到后续用例 ⇒「没打印」类断言恒真/恒假）', () => {
    // 反向护栏：删掉上面那条用例的 `finally { printSpy.mockRestore() }` ⇒ 本判据必红。
    expect(vi.isMockFunction(window.print)).toBe(false)
  })

  it('已完成订单也能补打发货单', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'completed', refundAmount: 0 } },
    })
    render(<OrderDetailPage />)

    expect(await screen.findByRole('button', { name: /打印发货单/ })).toBeInTheDocument()
  })

  it('待付款订单没有发货单入口（未发货谈不上补打）', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'pending_payment', refundAmount: 0 } },
    })
    render(<OrderDetailPage />)

    await waitFor(() => expect(screen.getAllByText('订单详情').length).toBeGreaterThanOrEqual(1))
    expect(screen.queryByRole('button', { name: /打印发货单/ })).not.toBeInTheDocument()
  })

  // ===== 打印报价单（issue #4965 / UI-053）：与「打印发货单」并列，同一权限口径与写法 =====

  it('已发货订单操作区显示「打印报价单」且点击真的触发 window.print（与发货单同一写法）', async () => {
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})
    try {
      mockGetOrder.mockResolvedValue({
        data: { data: { ...mockOrder, status: 'shipped', refundAmount: 0 } },
      })
      render(<OrderDetailPage />)

      const btn = await screen.findByRole('button', { name: /打印报价单/ })
      await userEvent.setup().click(btn)

      expect(printSpy).toHaveBeenCalledTimes(1)
    } finally {
      printSpy.mockRestore()
    }
  })

  it('已完成订单也能打印报价单（与发货单入口同状态口径）', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'completed', refundAmount: 0 } },
    })
    render(<OrderDetailPage />)

    expect(await screen.findByRole('button', { name: /打印报价单/ })).toBeInTheDocument()
  })

  it('报价单在页面级挂载一份（不进 Modal；每页只挂一份）', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'shipped', refundAmount: 0 } },
    })
    render(<OrderDetailPage />)

    await screen.findByRole('button', { name: /打印报价单/ })
    expect(screen.getAllByTestId('quotation-doc')).toHaveLength(1)
  })

  it('编辑物流弹窗回填已落库的发货人（存量为空时也可在此补齐）', async () => {
    mockGetOrder.mockResolvedValue({
      data: {
        data: {
          ...mockOrder,
          status: 'shipped',
          refundAmount: 0,
          logistics: { logisticsCompany: '顺丰速运', trackingNo: 'SF1', shipperName: '王五' },
        },
      },
    })
    render(<OrderDetailPage />)

    await userEvent.setup().click(await screen.findByRole('button', { name: '编辑物流' }))

    // LogisticsForm 在本文件被 mock 成占位 div；此处只锁定「弹窗被打开」这一可见结果，
    // 回填细节由 LogisticsForm/发货人字段的组件测试与后端落库测试覆盖
    expect(await screen.findByTestId('logistics-form')).toBeInTheDocument()
  })

  it('已退款订单（refundAmount > 0）操作区不显示 退款 按钮', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'completed', refundAmount: 500 } },
    })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('已退款 ¥500.00')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: '退款' })).not.toBeInTheDocument()
  })

  it('待付款订单操作区不显示 退款 按钮', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'pending', refundAmount: 0 } },
    })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('待买家付款')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: '退款' })).not.toBeInTheDocument()
  })

  it('点击 退款 弹出退款弹窗，提交调用 refundOrder 并重新加载订单', async () => {
    const user = userEvent.setup()
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'completed', refundAmount: 0 } },
    })
    mockRefundOrder.mockResolvedValue({ data: { success: true } })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '退款' })).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: '退款' }))
    expect(screen.getByTestId('refund-modal')).toBeInTheDocument()

    await user.click(screen.getByTestId('confirm-refund-detail'))
    await waitFor(() => {
      expect(mockRefundOrder).toHaveBeenCalledWith('test-order-123', { refundAmount: 500, refundReason: '质量问题' })
    })
    // 成功后重新加载订单详情
    await waitFor(() => {
      expect(mockGetOrder.mock.calls.length).toBeGreaterThanOrEqual(2)
    })
  })

  // ===== 确认付款失败：错误提示去重（issue #2923，case UI-019） =====

  it('确认付款失败：拦截器已提示具体错误 → 页面不再重复弹通用提示、弹窗保持打开', async () => {
    const user = userEvent.setup()
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'pending', refundAmount: 0 } },
    })
    const stockError = new Error('商品「测试9999」库存不足')
    markErrorToastShown(stockError) // 模拟拦截器已 toast 具体错误并打标记
    mockConfirmPayment.mockRejectedValue(stockError)
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('待买家付款')).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: '确认付款' }))
    await user.click(screen.getByRole('button', { name: '确定' }))
    await waitFor(() => {
      expect(mockConfirmPayment).toHaveBeenCalledWith('test-order-123')
    })
    // 拦截器已提示 → 页面不叠加通用错误
    expect(toast.error).not.toHaveBeenCalledWith('确认付款失败')
    // 失败不关闭确认弹窗
    expect(screen.getByText(/确认已收到付款/)).toBeInTheDocument()
  })

  it('确认付款失败：未经拦截器的错误 → 仍显示通用 fallback 提示', async () => {
    const user = userEvent.setup()
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'pending', refundAmount: 0 } },
    })
    mockConfirmPayment.mockRejectedValue(new Error('client-side error'))
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('待买家付款')).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: '确认付款' }))
    await user.click(screen.getByRole('button', { name: '确定' }))
    await waitFor(() => {
      expect(mockConfirmPayment).toHaveBeenCalled()
    })
    expect(toast.error).toHaveBeenCalledWith('确认付款失败')
  })

  // ===== 修改订单入口（issue #5842：买家未付款 = 待付款，商家可改内容） =====

  it('待付款订单：显示「修改订单」入口，点击后挂载修改弹窗', async () => {
    const user = userEvent.setup()
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'pending', refundAmount: 0 } },
    })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('待买家付款')).toBeInTheDocument()
    })

    const entry = screen.getByTestId('edit-order-content')
    expect(entry).toHaveTextContent('修改订单')
    // 入口挂载 ≠ 弹窗打开（两件事分开判：点击前弹窗不存在）
    expect(screen.queryByTestId('edit-order-content-modal')).not.toBeInTheDocument()

    await user.click(entry)
    await waitFor(() => {
      expect(screen.getByTestId('edit-order-content-modal')).toBeInTheDocument()
    })
  })

  it('非待付款订单（已确认待发货）：**不**显示「修改订单」入口（后端只有 pending 可改，界面不给死路）', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'confirmed', paidAt: '2026-06-20T10:30:00Z' } },
    })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('商品信息')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('edit-order-content')).not.toBeInTheDocument()
  })
  // ===== 费用构成可见（issue #5843）：商品合计 + 加工费 + 其它构成 = 订单金额 =====
  //
  // 用户 2026-10-01 报障读数：某单「商品合计 ¥245.14」与「订单金额 ¥368.74」之间那笔
  // **¥123.60 加工费在页面上任何位置都不出现**（差额 = 10.3 米 × ¥12.00/米）。
  // 本组钉的是**页面读得出来的等式**（不是「接口里有这个字段」）：
  //   ① 含加工费 ⇒ 出现加工费行，其值 = 落库 Σ `items[].processingFee`（**不重算**）；
  //   ② 等式闭合：页面上读到的 商品合计 + 加工费 + 其它构成 = 订单金额；
  //   ③ 布料单（本来就没有加工费）⇒ 不出现加工费行、不出现 `¥0.00` 行；
  //   ④ 未定价行 ⇒ 显式「未定价」+ 点名组合，**不渲染 `¥0.00`**。
  describe('费用构成可见（issue #5843）', () => {
    /** 用户报障那一单：单价 ¥23.80 × 10.3 米 = 245.14；10.3 米 × ¥12.00/米 = 123.60；订单金额 368.74 */
    const reportedItem = {
      id: 'item-1',
      productId: 'prod-1',
      productName: '全遮光雪尼尔',
      sku: 'SKU-1',
      unitPrice: 23.8,
      quantity: 10.3,
      amount: 245.14,
      subtotal: 245.14,
      processingFee: 123.6,
      processingInfo: {
        colorName: '米白',
        processingFeeDetail: {
          composition: '韩褶 + 定型',
          unit_price: 12,
          meters: 10.3,
          fee_source: 'matched',
          amount: 123.6,
        },
      },
    }
    const reportedOrder = {
      ...mockOrder,
      totalAmount: 368.74,
      actualAmount: 368.74,
      items: [reportedItem],
    }

    /** 页面上的金额读数（`¥1,234.56` → `1234.56`）—— 判据读的是**页面**，不是 props */
    const amountOf = (testId: string): number => {
      const text = screen.getByTestId(testId).textContent ?? ''
      const matched = text.replace(/,/g, '').match(/-?\d+(?:\.\d+)?/)
      if (!matched) throw new Error(`「${testId}」里没有金额读数：${JSON.stringify(text)}`)
      return Number(matched[0])
    }

    it('复现读数：这笔 ¥123.60 必须在页面上出现（改前整页金额读数里没有它）', async () => {
      mockGetOrder.mockResolvedValue({ data: { data: reportedOrder } })
      const { container } = render(<OrderDetailPage />)
      await screen.findByTestId('order-fee-breakdown')
      // 改前实测：整页金额读数只有 [¥245.14（金额列）, ¥245.14（商品合计列）, ¥368.74（订单金额）]
      // —— 差额 123.60 **一个渲染点都没有**（这就是「账对不上」）。
      const amounts = (container.textContent ?? '').replace(/,/g, '').match(/¥\d+\.\d{2}/g) ?? []
      expect(amounts, `页面上的金额读数 = ${JSON.stringify(amounts)}`).toContain('¥123.60')
    })

    it('等式闭合：页面上读到的 商品合计 + 加工费 = 订单金额', async () => {
      mockGetOrder.mockResolvedValue({ data: { data: reportedOrder } })
      render(<OrderDetailPage />)
      await screen.findByTestId('order-fee-breakdown')

      const goods = amountOf('fee-breakdown-goods')
      const fee = amountOf('fee-breakdown-processing')
      const orderTotal = amountOf('fee-breakdown-order-total')

      expect(goods).toBeCloseTo(245.14, 2)
      expect(fee).toBeCloseTo(123.6, 2) // = 落库 Σ items[].processingFee
      expect(orderTotal).toBeCloseTo(368.74, 2)
      expect(goods + fee).toBeCloseTo(orderTotal, 2)

      // 「看得见」= 等式本身在页面上有一行（不是只能自己心算）
      const equation = screen.getByTestId('fee-breakdown-equation').textContent ?? ''
      expect(equation).toContain('¥245.14')
      expect(equation).toContain('¥123.60')
      expect(equation).toContain('¥368.74')
    })

    it('行级算式：米数 × 单价/米 = 金额（与 OrderItemList 同一份算式实现）', async () => {
      mockGetOrder.mockResolvedValue({ data: { data: reportedOrder } })
      render(<OrderDetailPage />)
      await screen.findByTestId('fee-breakdown-line')
      expect(screen.getByTestId('fee-breakdown-line')).toHaveTextContent(
        '10.3 米 × ¥12.00/米 = ¥123.60'
      )
    })

    it('只展示落库快照、不重算：单价/米数与行金额不一致时以落库值为准', async () => {
      // 若详情页自己乘（9.99 × 10.3 = 102.90）⇒ 与订单金额对不上；落库值是 123.60 ⇒ 必须显示 123.60
      mockGetOrder.mockResolvedValue({
        data: {
          data: {
            ...reportedOrder,
            items: [
              {
                ...reportedItem,
                processingInfo: {
                  processingFeeDetail: {
                    composition: '韩褶 + 定型',
                    unit_price: 9.99,
                    meters: 10.3,
                    fee_source: 'manual',
                    amount: 123.6,
                  },
                },
              },
            ],
          },
        },
      })
      render(<OrderDetailPage />)
      await screen.findByTestId('fee-breakdown-processing')
      expect(amountOf('fee-breakdown-processing')).toBeCloseTo(123.6, 2)
      expect(screen.queryByText('¥102.90')).toBeNull()
      // 人工改价必须显式可见（与 OrderItemList 同一标记）
      expect(screen.getByTestId('order-fee-breakdown')).toHaveTextContent('人工改价')
    })

    it('布料单（无加工费）：不出现加工费行、不出现 ¥0.00 行', async () => {
      mockGetOrder.mockResolvedValue({
        data: {
          data: {
            ...mockOrder,
            totalAmount: 1990,
            actualAmount: 1990,
            items: [{ ...mockOrder.items[0], subtotal: 1990, amount: 1990, processingInfo: null }],
          },
        },
      })
      render(<OrderDetailPage />)
      await screen.findByText('订单金额') // 页面已加载（不是「还没渲染完」的假绿）
      expect(screen.queryByTestId('order-fee-breakdown')).toBeNull()
      expect(screen.queryByTestId('fee-breakdown-processing')).toBeNull()
    })

    it('未定价行：显式「未定价」+ 点名组合，不渲染 ¥0.00', async () => {
      mockGetOrder.mockResolvedValue({
        data: {
          data: {
            ...reportedOrder,
            totalAmount: 245.14,
            actualAmount: 245.14,
            items: [
              {
                ...reportedItem,
                processingFee: 0,
                processingInfo: {
                  processingFeeDetail: {
                    composition: '韩褶 + 定型',
                    items: ['韩褶', '定型'],
                    fee_source: 'unpriced',
                    amount: 0,
                  },
                },
              },
            ],
          },
        },
      })
      render(<OrderDetailPage />)
      const note = await screen.findByTestId('fee-breakdown-unpriced')
      expect(note).toHaveTextContent('未定价')
      expect(note).toHaveTextContent('韩褶 + 定型') // 点名组合（口径 = 新增订单页 unpricedCombinationLabel）
      expect(note).not.toHaveTextContent('¥0.00')
      // 未定价那半按 0 计 ⇒ 不出现「加工费 ¥0.00」（与「本来就不收」长得一样）
      expect(screen.queryByTestId('fee-breakdown-processing')).toBeNull()
    })

    it('差额非 0：显式「其它构成」解释行，等式仍然在页面上闭合', async () => {
      mockGetOrder.mockResolvedValue({
        data: {
          // 商品 245.14 + 加工 123.60 = 368.74，而订单金额是 373.74 ⇒ 差额 5.00 必须有解释行
          data: { ...reportedOrder, totalAmount: 373.74, actualAmount: 373.74 },
        },
      })
      render(<OrderDetailPage />)
      await screen.findByTestId('fee-breakdown-other')
      const goods = amountOf('fee-breakdown-goods')
      const fee = amountOf('fee-breakdown-processing')
      const other = amountOf('fee-breakdown-other')
      const orderTotal = amountOf('fee-breakdown-order-total')
      expect(other).toBeCloseTo(5, 2)
      expect(goods + fee + other).toBeCloseTo(orderTotal, 2)
    })
  })

  // ===== #5846：整卷售卖 —— 订单行**看得见**「整卷 N + 散剪 M 米」 =====
  //
  // 用户 2026-10-01 报的缺口：渲染分配文案的 `rollAllocationText` 只存在于 `OrderItemList`，
  // 而**没有任何页面渲染它**（导出 + 单测都有，就是没接线）⇒ 商家在订单详情看不到卷数。
  // 本单把它接到详情页的商品明细行上（与明细组件**同一份** `RollAllocationNote`）。
  it('#5846: 订单行带 rollCount / rollLengthM ⇒ 详情页渲染「整卷 1 + 散剪 40 米」', async () => {
    mockGetOrder.mockResolvedValue({
      data: {
        data: {
          ...mockOrder,
          items: [{ ...mockOrder.items[0], quantity: 100, rollCount: 1, rollLengthM: 60 }],
        },
      },
    })
    render(<OrderDetailPage />)

    const el = await screen.findByTestId('roll-allocation')
    expect(el.textContent).toContain('整卷 1 + 散剪 40 米')
  })

  it('#5846 改判: 卷数有值、每卷米数没记 ⇒ 详情页渲染「整卷 2 卷（未记每卷米数）」（意图可见、不编米数）', async () => {
    mockGetOrder.mockResolvedValue({
      data: {
        data: {
          ...mockOrder,
          items: [{ ...mockOrder.items[0], quantity: 100, rollCount: 2, rollLengthM: null }],
        },
      },
    })
    render(<OrderDetailPage />)

    const el = await screen.findByTestId('roll-allocation')
    expect(el.textContent).toContain('整卷 2 卷（未记每卷米数）')
    expect(el.textContent).not.toMatch(/散剪/)
    expect(el.textContent).not.toMatch(/\d+\s*米/)
  })

  it('#5846: **两列都为空** ⇒ 详情页不渲染（既有「缺值不渲染」口径不变；只有长度没有卷数同样不渲染）', async () => {
    mockGetOrder.mockResolvedValue({
      data: {
        data: {
          ...mockOrder,
          items: [{ ...mockOrder.items[0], quantity: 100, rollCount: null, rollLengthM: null }],
        },
      },
    })
    render(<OrderDetailPage />)

    await screen.findByText('测试窗帘布')
    expect(screen.queryByTestId('roll-allocation')).toBeNull()
  })

})
