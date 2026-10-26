// case_ids: OR-001, OR-002, OR-003, OR-046, OR-055, OR-067, OR-068, OR-070, UI-024, UI-040, UI-053, UI-076, UI-090
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, cleanup, screen, waitFor } from '@testing-library/react'

// issue #7276：订单详情页的**页面码 = order:detail**（判据见 tests/unit/pages/order-detail-permission-gate.test.tsx）
// ⇒ 本文件渲染的是「有权限的商家」形态，必须给登录态一份 `*` 权限；否则页面走拒绝态，
// 本文件的全部断言会凭空变红（那不是被测行为）。
const authMock = vi.hoisted(() => ({
  state: {
    user: { id: '1', username: 'tester', name: '测试账号', permissions: ['*'] as string[], roles: [] as string[] },
  },
}))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) =>
    typeof selector === 'function' ? selector(authMock.state) : authMock.state,
}))
import userEvent from '@testing-library/user-event'
import dayjs from 'dayjs'
import { markErrorToastShown } from '@/lib/api-error'

// Mock API
const mockGetOrder = vi.fn()
// 发货读面（issue #5651 收口）：销售单数量列消费的**实发**来源 —— 详情页加载订单时一并取
const mockGetOrderShipments = vi.fn()
// 工序读面（issue #6901）：**屏幕**加工单块的工序清单来源（既有读面，按订单 id 取）；纸面自 #7274 起不印工序
const mockGetOrderOperations = vi.fn()
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
  productionApi: {
    getOrderOperations: (...args: any[]) => mockGetOrderOperations(...args),
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
// 🔴 用**真实导出兜底 + 逐项替身**：`@/components/orders` 的替身少一个导出 ⇒ 渲染期直接抛
// （issue #5914 实测：漏掉 `PrintDocPreview` ⇒ 本文件整片 5s 超时红）。下面只替身"内容型"组件，
// 其余（如 `PrintDocPreview` / `usePrintDoc` / `PRINT_TARGET_SPECS`）走真货。
vi.mock('@/components/orders', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/orders')>()
  return {
    ...actual,
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
  // 纸质销售单（三联纸 241mm×140mm，issue #5651）：同上 —— 入口按钮在本文件，
  // 纸面内容由 SalesDoc.test.tsx 覆盖。
  // ⚠️ `@/components/orders` 的 mock 少一个导出 ⇒ 渲染期直接抛（同 OrderUrgencyPanel 那条注释）
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
  // 打印层（issue #5914 / #7544）：**走真货**，不替身 —— 本文件要验的正是
  // 「页面唯一入口 → 预览层的单据标签（`docs` / `onSelect` 接线）→ 打印」这条链，
  // 替身成壳会让「选单据」变成空断言（几何自检那半边由 PrintDocPreview.test.tsx 负责）。
  // ⚠️ 仍然显式写出这一条（值 = 真组件直通）：`test_orders_barrel_mock_guard.py` 的 C2 要求
  // 「页面 import 的桶组件在 mock 里都有键」（它不解析 `...actual` 的展开）—— 写在这里既满足
  // 该守卫，又保住「不替身」这一点。
  PrintDocPreview: actual.PrintDocPreview,
  EditOrderContentModal: ({ open }: any) =>
    open ? <div data-testid="edit-order-content-modal">EditOrderContentModal</div> : null,
  }
})

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
    // 工序读面（issue #6901 / #7274）：默认给「无工序实例」—— 工序清单的**屏幕**判据在
    // ProcessingOrderBlock.test.tsx（纸面自 #7274 起不印工序；此处只要形状对得上，不让它抛）
    mockGetOrderOperations.mockResolvedValue({ data: { data: { positions: [] } } })
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
      expect(screen.getByText('销售订单')).toBeInTheDocument()
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

  // ===== 商品信息表：整表统一居中（issue #7590）=====
  // 改前实测（2026-10-24 用户截图）：商品/商品货号/颜色/规格尺寸 左对齐、数量 居中、
  // 单价/金额/商品合计 右对齐 ⇒ **同一张表三种对齐并存**，列与列之间没有稳定参照边。
  // 用户裁定「要不都设计成居中」⇒ 判据 = 表内**每一个** th / td 都带 `text-center`，
  // 且**不带** `text-left` / `text-right`（后者会按 CSS 顺序覆盖居中 ⇒「看着居中、其实逐格漂移」）。
  it('商品信息表：每个表头与数据格都居中（issue #7590）', async () => {
    render(<OrderDetailPage />)
    const header = await screen.findByRole('columnheader', { name: '商品合计' })
    const table = header.closest('table')!
    // 存在性断言要**触业务对象**（弱断言 `not.toBeNull` 会被 QA Growth Gate 判红）：
    // 找不到表时 `tagName` 为 undefined ⇒ 这里同样红，且给出的是「扫的是不是 table」这个事实
    expect(table.tagName, '找不到「商品信息」表 ⇒ 判据在扫空气').toBe('TABLE')
    const cells = Array.from(table.querySelectorAll('th, td'))
    expect(cells.length, '表内单元格不足 8 个 ⇒ 判据在扫空气').toBeGreaterThanOrEqual(8)
    const label = (c: Element) => `${c.tagName}「${(c.textContent || '').trim().slice(0, 10)}」`
    expect(
      cells.filter((c) => !c.className.split(/\s+/).includes('text-center')).map(label),
      '这些单元格没有居中（整表统一居中，见 issue #7590）'
    ).toEqual([])
    expect(
      cells.filter((c) => /\btext-(left|right)\b/.test(c.className)).map(label),
      '这些单元格同时带了 text-left / text-right ⇒ 会覆盖居中'
    ).toEqual([])
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

  it('renders "-" for missing paidAt/shippedAt/receivedAt（存量未采集 ⇒ 占位，不崩不猜）', async () => {
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

  // issue #7078：三个时刻改由**服务端真值**下发（orders.paid_at / shipped_at / received_at）。
  // 这条判据钉住的正是用户真机上那处自相矛盾：状态引导第 1 步「已付款 ✓」+ 基础信息「支付时间 -」
  // （根因 = 屏幕面读后端从不下发的键 ⇒ 恒 "-"，#6882 同类）。
  it('基础信息渲染服务端下发的 支付时间 / 发货时间 / 确认收货时间（不再是恒 -）', async () => {
    const times = {
      paidAt: '2026-06-20T10:30:00Z',
      shippedAt: '2026-06-21T02:00:00Z',
      receivedAt: '2026-06-23T06:00:00Z',
    }
    mockGetOrder.mockResolvedValue({ data: { data: { ...mockOrder, status: 'completed', ...times } } })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('基础信息')).toBeInTheDocument()
    })
    const rows: Array<[string, string]> = [
      ['支付时间：', times.paidAt],
      ['发货时间：', times.shippedAt],
      ['确认收货时间：', times.receivedAt],
    ]
    for (const [label, iso] of rows) {
      const cell = screen.getByText(label).parentElement!
      // 期望值与 DateTimeCell 同一份格式化口径（本地时区 YYYY-MM-DD / HH:mm）⇒ 不写死字符串，
      // 跨时区跑不会假红
      expect(cell.textContent).toContain(dayjs(iso).format('YYYY-MM-DD'))
      expect(cell.textContent).toContain(dayjs(iso).format('HH:mm'))
    }
  })

  it('不再渲染「支付交易号」行（后端无真值源 ⇒ 撤下，issue #7078）', async () => {
    mockGetOrder.mockResolvedValue({ data: { data: { ...mockOrder, status: 'confirmed' } } })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('基础信息')).toBeInTheDocument()
    })
    expect(screen.queryByText('支付交易号：')).not.toBeInTheDocument()
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

  // ===== 打印：页面级**唯一**入口，且不跟订单状态挂钩（issue #7544）=====
  //
  // 改前（#6434）是「订单状态 × 可打单据」矩阵：4 个按钮按状态分支各渲一组，`closed` / `refund`
  // 两个状态**一个按钮都没有**（商家要给客户补一张报价单时是死路）。用户 2026-10-23 的裁定两头都要改：
  // ① **不跟状态挂钩** —— 任何状态都能打；② **收拢成一个入口** —— 点「打印」再选单据、先预览再打出纸。
  //
  // 判据形态 = 表驱动：每个状态断言「**恰好一个**以『打印』开头的按钮」（改前是 4 个），
  // 谁再往状态分支里塞第二个打印入口，这里当场红。

  const ALL_ORDER_STATUSES = [
    'pending_payment',
    'pending_shipment',
    'producing',
    'shipped',
    'completed',
    'closed',
    'refund',
  ]

  it.each(ALL_ORDER_STATUSES)(
    '打印不跟订单状态挂钩（issue #7544）：%s 也有且只有一个「打印」入口',
    async (status) => {
      mockGetOrder.mockResolvedValue({ data: { data: { ...mockOrder, status, refundAmount: 0 } } })
      render(<OrderDetailPage />)

      // 稳态锚点 = 订单号进 DOM（页面已拿到订单）——**不拿打印按钮当锚点**，
      // 否则「按钮本来就该在」这条判据会退化成「等我自己出现」（空断言）。
      await screen.findAllByText(mockOrder.orderNo)

      expect(screen.getByTestId('order-print-entry')).toBeInTheDocument()
      // 🔴 唯一性：以「打印」开头的按钮**只能有一个**（改前是「打印报价单 / 打印加工单 / 打印销售单 …」
      // 并排铺开）—— 这条就是「收拢成统一入口」本体的机器读数。
      expect(screen.getAllByRole('button', { name: /^打印/ })).toHaveLength(1)
    },
  )

  it('点「打印」→ 在预览层里换单据 → 打印：默认销售单，换标签后预览的就是所选那份（issue #7544）', async () => {
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})
    try {
      mockGetOrder.mockResolvedValue({ data: { data: { ...mockOrder, status: 'shipped', refundAmount: 0 } } })
      render(<OrderDetailPage />)
      const user = userEvent.setup()
      await screen.findAllByText(mockOrder.orderNo)

      await user.click(screen.getByTestId('order-print-entry'))

      // 打开预览 ≠ 出纸（纸是耗材，issue #5914）
      expect(printSpy).not.toHaveBeenCalled()
      // **三份**单据在选择器里（加工单自 issue #7870 起搬到「加工单生产明细」页 ——
      // 一份单据只有一个打印入口），文案取 `PRINT_TARGET_SPECS`（不手写第二份字面量）
      for (const [target, title] of [
        ['sales', '销售单'],
        ['quotation', '报价单'],
        ['shipment', '发货单'],
      ] as const) {
        expect(screen.getByTestId(`print-preview-doc-${target}`)).toHaveTextContent(title)
      }
      // 🔴 加工单**不在**订单详情页的打印层里（issue #7870 的迁移判据）
      expect(screen.queryByTestId('print-preview-doc-processing')).toBeNull()
      // 默认选中销售单（三联纸 241×140 ⇒ 纸型读数跟着它走）
      expect(screen.getByTestId('print-preview-doc-sales')).toHaveAttribute('aria-pressed', 'true')
      expect(screen.getByTestId('print-preview-media')).toHaveTextContent('241mm × 140mm')

      // 换成报价单：预览与纸型都换成 A4 的那一份，但**仍然没出纸**
      await user.click(screen.getByTestId('print-preview-doc-quotation'))
      expect(screen.getByTestId('print-preview-doc-quotation')).toHaveAttribute('aria-pressed', 'true')
      expect(screen.getByTestId('print-preview-media')).toHaveTextContent('210mm × 297mm')
      expect(printSpy).not.toHaveBeenCalled()

      await user.click(screen.getByTestId('print-preview-print'))
      expect(printSpy).toHaveBeenCalledTimes(1)
    } finally {
      printSpy.mockRestore()
    }
  })

  it('已关闭订单也能打开打印层（改前这个状态一张单据都打不出来）', async () => {
    mockGetOrder.mockResolvedValue({ data: { data: { ...mockOrder, status: 'closed', refundAmount: 0 } } })
    render(<OrderDetailPage />)

    const user = userEvent.setup()
    await screen.findAllByText(mockOrder.orderNo)
    await user.click(screen.getByTestId('order-print-entry'))

    expect(screen.getByTestId('print-preview')).toBeInTheDocument()
  })

  it('打印用例跑完后 window.print 必须已还原（否则泄漏到后续用例 ⇒「没打印」类断言恒真/恒假）', () => {
    // 反向护栏：删掉上面那条用例的 `finally { printSpy.mockRestore() }` ⇒ 本判据必红。
    expect(vi.isMockFunction(window.print)).toBe(false)
  })

  it('报价单在页面级挂载一份（不进 Modal；每页只挂一份）', async () => {
    mockGetOrder.mockResolvedValue({ data: { data: { ...mockOrder, status: 'shipped', refundAmount: 0 } } })
    render(<OrderDetailPage />)

    await screen.findAllByText(mockOrder.orderNo)
    expect(screen.getAllByTestId('quotation-doc')).toHaveLength(1)
  })

  // ===== 工序清单读面接线（issue #6901）=====
  //
  // 🔴 「加了 prop 不等于接线」：**屏幕**加工单块（含「复制全部」文本）靠本页把
  // `GET /api/admin/production/orders/{id}/operations` 的结果传下去 —— 没有真实调用方时
  // 工序清单在生产里**永远不出现**，而组件单测喂夹具会全绿（本仓反复复发的假绿形态）。
  // 本用例直连**真实调用路径**（页面 → 读面 → state）；`ProcessingOrderBlock` 端子行逐值由
  // ProcessingOrderBlock.test.tsx 的工序用例负责（本文件把该组件替身成空壳）。
  // 🔴 纸面 `ProcessingDoc` 自 issue #7274 起**不再接收** `operations`（工序细节不上纸）。
  // 接线面的机械证据另见 PR body 的 `grep -n "operations={orderOperations}"`（现在只剩加工单块那一处）。
  it('🔴 工序读面接线（issue #6901）：详情页按订单 id 取 `orders/{id}/operations` 并向下传', async () => {
    const operations = [
      {
        order_item_id: 'item1',
        position_name: '布帘',
        operations: [
          { id: 'op-1', operation: '精裁-布', logical_name: '精裁', unit: '米', qty: 20, status: 'pending' },
        ],
      },
    ]
    mockGetOrderOperations.mockResolvedValue({ data: { data: { positions: operations } } })
    // 加工单块只在「订单含加工项」时渲染（`hasProcessing`）—— 夹具与真页面同形
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'producing', processingItems: [{ id: 'pi-1', name: '打孔', quantity: 2 }] } },
    })

    const { container } = render(<OrderDetailPage />)
    // 稳态锚点 = 订单号进 DOM（页面已拿到订单）
    await screen.findAllByText(mockOrder.orderNo)

    // ① 真调了既有读面，且引用的是**本订单** id（缺这行 ⇒ 页面根本不取工序）
    await waitFor(() => expect(mockGetOrderOperations).toHaveBeenCalledWith('test-order-123'))
    // ② 页面到达稳态：加工单块渲染出来、没被工序读面拖垮，也没有失败态文案
    //    （issue #7544 起加工单块不再自带打印按钮 —— 打印统一走页面级入口，故锚点换回页面事实）
    expect(screen.getByTestId('po-block')).toBeInTheDocument()
    expect(container.textContent).not.toContain('加载订单详情失败')
  })

  // 缺值面：读面失败 ⇒ 工序块**不出现**（不印空表），且**不拖垮**订单详情（同页其它读面照常）。
  it('🔴 工序读面失败 ⇒ 页面不出现工序块，订单详情照常渲染（失败隔离，issue #6901）', async () => {
    mockGetOrderOperations.mockRejectedValue(new Error('boom'))

    render(<OrderDetailPage />)
    // 稳态锚点 = 订单号进 DOM（页面已拿到订单）
    await screen.findAllByText(mockOrder.orderNo)
    await waitFor(() => expect(mockGetOrderOperations).toHaveBeenCalledWith('test-order-123'))

    expect(screen.queryAllByTestId('po-item-operation')).toHaveLength(0)
    // 纸面级 testid 也不该出现（工序块整块不出现，不印占位表头）
    expect(screen.queryByText('工序')).not.toBeInTheDocument()
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

  // ===== issue #7850：「收货信息」块补「物流方式」「物流公司」两格读数 =====
  //
  // 病：下单页自 issue #5840 起把「常用物流方式 / 物流公司」当必填（`order-logistics-type` /
  // `order-logistics-company`），服务端落在 `orders.logistics_type` / `logistics_company` 两列，
  // 详情读面也已透出（`Order.logisticsType` / `Order.logisticsCompany`）；但详情页「收货信息」块
  // 只印收货人 / 联系电话 / 收货地址三行 ⇒ 商家在详情页看不到这一单走快递还是物流专线、哪家承运。
  //
  // 谁会红：把 OrderDetail.tsx「收货信息」块里那两格 `InfoRow`（物流方式 / 物流公司）删掉 ⇒
  // 下面两条全红（`findByText('物流方式：')` 直接超时）。
  //
  // 口径（#4419 既有裁定）：缺值印 `-`，**不得**把「未登记」臆造成「快递」——
  // 故「物流方式」复用 `lib/logistics.ts` 的 `logisticsTypeText()`（缺值 ⇒ null），
  // **不**走表单口径的 `logisticsTypeLabel()`（那个缺值回落「快递」，是给下拉框用的）。
  it('#7850: 收货信息块显示服务端下发的物流方式与物流公司（express ⇒ 快递）', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, logisticsType: 'express', logisticsCompany: '顺丰' } },
    })
    render(<OrderDetailPage />)

    // 行 = InfoRow 的 div（标签 span + 取值 span）；整行文本逐字断言 ——
    // 只断言「页面上出现过快递」会是空断言（别的块也可能带同名文案，看不出是本块读数）
    const typeRow = await screen.findByText('物流方式：')
    expect(typeRow.parentElement?.textContent).toBe('物流方式：快递')
    expect(screen.getByText('物流公司：').parentElement?.textContent).toBe('物流公司：顺丰')
  })

  it('#7850: 物流方式 / 物流公司缺值 ⇒ 两格印 `-`，不得臆造「快递」', async () => {
    // 存量单形态：两列都没值（后端 NULL）—— 与默认夹具同形，但**显式**写出来，
    // 免得日后改默认夹具把这条缺值面悄悄测成「有值面」
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, logisticsType: null, logisticsCompany: null } },
    })
    render(<OrderDetailPage />)

    const typeRow = await screen.findByText('物流方式：')
    expect(typeRow.parentElement?.textContent).toBe('物流方式：-')
    expect(screen.getByText('物流公司：').parentElement?.textContent).toBe('物流公司：-')
    // 负控：本夹具没有任何物流真值 ⇒ 整页不得出现被臆造出来的「快递」
    expect(screen.queryByText('快递')).toBeNull()
  })

  // ===== 安装信息（issue #7856）=====
  // 两个字段都是「只存只印」的附注；屏幕上的口径与相邻行一致：
  // 订单级的**安装小区**缺值显示 `-`（信息面要读得全），件级的**安装位置**缺值**不渲染**该行
  // （与「部位备注」同一口径：不占位、不印 `-`）。

  it('#7856: 安装小区有值 ⇒ 收货信息区显示，且**不**与收货地址互相回填', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, installCommunity: '春江花园 3栋2单元 502' } },
    })
    render(<OrderDetailPage />)

    const label = await screen.findByText('安装小区：')
    expect(label.parentElement?.textContent).toBe('安装小区：春江花园 3栋2单元 502')
    // 收货地址仍在原位（两个事实、两个地址，不合并）
    expect(screen.getByText('收货地址：').parentElement?.textContent).toBe(
      '收货地址：北京市朝阳区xx小区'
    )
  })

  it('#7856: 安装小区缺值 ⇒ `-`（与相邻行同口径，不留白、不 undefined）', async () => {
    render(<OrderDetailPage />)
    const label = await screen.findByText('安装小区：')
    expect(label.parentElement?.textContent).toBe('安装小区：-')
  })

  it('#7856: 安装位置（件级）有值 ⇒ 该行渲染「安装位置 主卧」', async () => {
    mockGetOrder.mockResolvedValue({
      data: {
        data: { ...mockOrder, items: [{ ...mockOrder.items[0], installRoom: '主卧' }] },
      },
    })
    render(<OrderDetailPage />)

    const el = await screen.findByTestId('order-item-install-room')
    expect(el.textContent).toBe('安装位置主卧')
  })

  it('#7856: 安装位置缺值 ⇒ 该行**不渲染**（不显示 `-`、不显示空行）', async () => {
    render(<OrderDetailPage />)
    await screen.findByText('测试窗帘布')
    expect(screen.queryByTestId('order-item-install-room')).toBeNull()
  })
})
