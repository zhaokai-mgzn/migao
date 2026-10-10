// case_ids: UI-057, UI-058, UI-074, OR-001, OR-046, UI-087, UI-089
/**
 * 「**计数行不得从一个可能失败的读派生数字**」——**实例判据**（issue #6703）。
 *
 * ## 病灶（集成侧注入实测）
 *
 * 后端整体不可用（注入 `/api/admin/**` → 500）时，失败**只由瞬时 toast 宣告**（≈4s 消失），
 * 而**持久面**上仍留着事实性断言：「**共 0 条**」/ Pagination 的「**共 0 条记录**」。
 * 商家看一眼 toast 回到屏幕，只看到零 ⇒ 读成「今天没有订单 / 没有客户 / 没有流水」——
 * 与 #6691「读面故障不得画成空态」同族，承载体从**列表**换成了**计数行**：
 * `total` 的初值是 0，读失败时没有人告诉它这个 0 不可信。
 *
 * ## 本文件钉住的三件事（每页三条，逐页各一条用例）
 *
 *   ① **屏上任何位置都不含「共 0 条」**（含 Pagination 的「共 0 条记录」与页尾的「共 0 条」）——
 *      🔴 **不看 toast**：本文件不依赖 toast 的 4s 存活窗口（那是**屏上另一处**的信号），
 *      断言的是**常驻面**（计数行 / 卡片金额位 / 空态话术）在失败后**紧接着**的样子；
 *   ② **存在持久失败锚点**（`<页面>-load-error`，`role="alert"`）—— 只靠 toast 不算「宣告过」；
 *   ③ **点重试 ⇒ 真重发**：调用次数 +1，且计数行恢复**真实 total**；
 *      对照读数：读成功但**真的**没有数据 ⇒ 计数行照旧印「共 0 条」（失败态**没有**把空态吃掉）。
 *
 * ## 反假绿约束（`migao-acceptance`）
 *
 * - 失败一律来自 **mock 接口 reject**（不依赖真实服务不可达）；
 * - ① 的判别力来自「`total` 初值 0 + 读失败」这个**改前必现**的组合
 *   （改前这 6 页在同样注入下渲染的就是「共 0 条」，见 PR body 的红证读数）；
 * - ③ 钉住**调用次数**与**恢复后的真值**（不是「锚点消失了」这类改前改后都绿的断言）。
 *
 * ## 边界（照实登记）
 *
 * - 只覆盖本包文件族（`/orders` `/finance` `/customers` `/after-sales` `/knowledge`
 *   `/stock-ledger` + 共享 `Pagination`）；`/employees` `/notifications` `/products`
 *   `/components/employees/WorkerProfilesPanel` 是**同族存量债**，登记在
 *   `frontend/admin-web/scripts/count-row-derived-scan.mjs` 的 `LEDGER`（归后续包）；
 * - `/production/remnants`（#6702）与工作台金额面（#6701）**不在本文件射程**。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { markErrorToastShown } from '@/lib/api-error'

const TEST_TIMEOUT = 20_000

/** 登录态：`/orders`（`order:create`）/ `/knowledge`（`knowledge:manage`）的写按钮按权限显隐 */
const authMock = vi.hoisted(() => ({
  state: {
    user: { id: '1', username: 'admin', name: '管理员', permissions: ['*'] as string[], roles: [] as string[] },
  },
}))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) =>
    typeof selector === 'function' ? selector(authMock.state) : authMock.state,
}))

const mockGetOrders = vi.fn()
const mockGetCustomers = vi.fn()
const mockGetCustomerTags = vi.fn()
const mockGetTickets = vi.fn()
const mockGetCards = vi.fn()
const mockGetCandidates = vi.fn()
const mockGetPendingCount = vi.fn()
const mockGetTemplates = vi.fn()
const mockGetSummary = vi.fn()
const mockGetTransactions = vi.fn()
const mockGetReconciliation = vi.fn()
const mockLedger = vi.fn()
const mockGetProducts = vi.fn()
const mockBatches = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: { getOrders: (...a: unknown[]) => mockGetOrders(...a) },
  customerApi: {
    getCustomers: (...a: unknown[]) => mockGetCustomers(...a),
    getCustomerTags: (...a: unknown[]) => mockGetCustomerTags(...a),
  },
  afterSalesApi: { getTickets: (...a: unknown[]) => mockGetTickets(...a) },
  knowledgeApi: {
    getCards: (...a: unknown[]) => mockGetCards(...a),
    getCandidates: (...a: unknown[]) => mockGetCandidates(...a),
    getPendingCount: (...a: unknown[]) => mockGetPendingCount(...a),
    getTemplates: (...a: unknown[]) => mockGetTemplates(...a),
  },
  financeApi: {
    getSummary: (...a: unknown[]) => mockGetSummary(...a),
    getTransactions: (...a: unknown[]) => mockGetTransactions(...a),
    getReconciliation: (...a: unknown[]) => mockGetReconciliation(...a),
  },
  stockLedgerApi: { ledger: (...a: unknown[]) => mockLedger(...a) },
  productApi: { getProducts: (...a: unknown[]) => mockGetProducts(...a) },
  batchStockApi: { batches: (...a: unknown[]) => mockBatches(...a) },
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }))

import OrdersPage from '@/app/(dashboard)/orders/page'
import CustomersPage from '@/app/(dashboard)/customers/page'
import AfterSalesPage from '@/app/(dashboard)/after-sales/page'
import KnowledgePage from '@/app/(dashboard)/knowledge/page'
import FinancePage from '@/app/(dashboard)/finance/page'
import StockLedgerPage from '@/app/(dashboard)/stock-ledger/page'

const ok = (data: unknown) => ({ data: { data } })
const paged = (items: unknown[], total = items.length) => ok({ items, total, page: 1, size: 20 })

/** 造一个**已经被统一拦截器 toast 过**的错误（避免页面再弹第二条） */
const apiFail = () => {
  const e = new Error('接口挂了（mock）')
  markErrorToastShown(e)
  return e
}

/**
 * 🔴 判别力锚：改前这些页面在「读失败」时会渲染出这一行（`total` 停在初值 0）。
 * 断言用**整页容器**（不是某一个 testid）——「任何位置都不含」才是本单要的口径。
 */
const NO_FAKE_ZERO = /共\s*0\s*条/

const ordersRow = {
  id: 'o-1',
  orderNo: 'MG20261010001',
  status: 'pending_shipment',
  customerName: '张三',
  customerPhone: '13800138000',
  customerAddress: '北京市朝阳区xx小区',
  totalAmount: 1999,
  discountAmount: 0,
  actualAmount: 1999,
  createdAt: '2026-10-10T10:00:00Z',
  items: [],
  processingItems: [],
}

const customerRow = {
  id: '1',
  name: '张美丽',
  phone: '138****1234',
  channel: 'wechat_mini',
  vipLevel: 'gold',
  totalOrders: 5,
  totalSpent: 12000,
  createdAt: '2026-04-20T14:30:00Z',
  lastActiveAt: '2026-04-20T14:30:00Z',
}

const ticketRow = {
  id: 't-1',
  ticketNo: 'SH20261010001',
  orderNo: 'MG20261010001',
  customerName: '张三',
  ticketType: 'return',
  status: 'pending',
  priority: 'normal',
  createdAt: '2026-10-10T10:00:00Z',
  updatedAt: '2026-10-10T10:00:00Z',
}

const cardRow = {
  id: 'k-1',
  title: '窗帘多久洗一次',
  category: 'faq',
  question: '窗帘多久洗一次？',
  answer: '建议每 3-6 个月清洗一次。',
  keywords: '清洗',
  status: 'published',
  sourceType: 'manual',
  createdAt: '2026-10-10T10:00:00Z',
  updatedAt: '2026-10-10T10:00:00Z',
}

const txnRow = {
  id: 'tx-1',
  transactionNo: 'LS20261010001',
  type: 'income',
  amount: 1999,
  paymentMethod: 'wechat',
  orderNo: 'MG20261010001',
  status: 'success',
  operator: 'admin',
  occurredAt: '2026-10-10T10:00:00Z',
  createdAt: '2026-10-10T10:00:00Z',
  remark: '',
}

const ledgerRow = {
  id: 2,
  productId: 'prod-1',
  skuId: 12,
  skuCode: 'HZ-001-米白',
  delta: '50.0',
  beforeQty: '0.0',
  afterQty: '50.0',
  reason: 'inbound',
  refNo: 'RK-20261001-0001',
  note: null,
  unitCost: '24.80',
  costAmount: '1240.00',
  avgCostBefore: null,
  avgCostAfter: '24.80',
  operator: 'zhangsan',
  createdAt: '2026-10-01T10:00:00Z',
}

beforeEach(() => {
  vi.clearAllMocks()
  mockGetOrders.mockResolvedValue(paged([ordersRow], 1))
  mockGetCustomers.mockResolvedValue(paged([customerRow], 1))
  mockGetCustomerTags.mockResolvedValue(ok([]))
  mockGetTickets.mockResolvedValue(paged([ticketRow], 1))
  mockGetCards.mockResolvedValue(paged([cardRow], 1))
  mockGetCandidates.mockResolvedValue(paged([], 0))
  mockGetPendingCount.mockResolvedValue(ok({ pending: 0 }))
  mockGetTemplates.mockResolvedValue(ok([]))
  mockGetSummary.mockResolvedValue(ok({
    totalIncome: 1999,
    totalRefund: 0,
    netIncome: 1999,
    pendingReceivable: 0,
    incomeCount: 1,
    refundCount: 0,
  }))
  mockGetTransactions.mockResolvedValue(paged([txnRow], 1))
  mockGetReconciliation.mockResolvedValue(paged([], 0))
  mockLedger.mockResolvedValue(paged([ledgerRow], 1))
  mockGetProducts.mockResolvedValue(paged([{ id: 'prod-1', name: '遮光窗帘布料' }], 1))
  mockBatches.mockResolvedValue(ok([]))
})

describe('#6703 ① /orders：读失败 ⇒ 计数行印「—」+ 常驻失败锚点 + 真重发', () => {
  it('失败：屏上零「共 0 条」、有 orders-load-error；重试后计数行恢复真实 total', async () => {
    const user = userEvent.setup({ delay: null })
    mockGetOrders.mockRejectedValueOnce(apiFail())
    const { container } = render(<OrdersPage />)

    const alert = await screen.findByTestId('orders-load-error')
    expect(alert).toHaveTextContent('订单加载失败')
    // ① 常驻面上没有任何地方印着「共 0 条」（改前这里就是病灶）
    expect(container.textContent).not.toMatch(NO_FAKE_ZERO)
    // ② 计数行确实在，且印的是「不可信」而不是 0
    expect(container.textContent).toContain('共 — 条')

    // ③ 出口：点「重新加载」真的重发（调用次数 +1）⇒ 恢复真实 total
    const callsBefore = mockGetOrders.mock.calls.length
    mockGetOrders.mockResolvedValue(paged([ordersRow], 7))
    await user.click(screen.getByTestId('orders-load-error-retry'))
    await waitFor(() => expect(container.textContent).toContain('共 7 条'))
    expect(mockGetOrders.mock.calls.length).toBeGreaterThan(callsBefore)
    expect(mockGetOrders.mock.calls.at(-1)?.[0]).toMatchObject({ page: 1, size: 20 })
    expect(screen.queryByTestId('orders-load-error')).toBeNull()
  }, TEST_TIMEOUT)

  it('对照读数：读成功且真的没有订单 ⇒ 计数行照旧印「共 0 条」（失败态没把空态吃掉）', async () => {
    mockGetOrders.mockResolvedValue(paged([], 0))
    const { container } = render(<OrdersPage />)
    await waitFor(() => expect(container.textContent).toContain('共 0 条'))
    expect(screen.queryByTestId('orders-load-error')).toBeNull()
  }, TEST_TIMEOUT)
})

describe('#6703 ② /customers：读失败 ⇒ 分页计数行不印「共 0 条记录」', () => {
  it('失败：屏上零「共 0 条」、有 customers-load-error；重试后恢复真实 total', async () => {
    const user = userEvent.setup({ delay: null })
    mockGetCustomers.mockRejectedValueOnce(apiFail())
    const { container } = render(<CustomersPage />)

    const alert = await screen.findByTestId('customers-load-error')
    expect(alert).toHaveTextContent('客户列表加载失败')
    expect(container.textContent).not.toMatch(NO_FAKE_ZERO)
    // 🔴 共享 Pagination：失败时印 `—`（改前它印「共 0 条记录」——所有用它的页面都受影响）
    expect(container.textContent).toContain('共 — 条记录')

    const callsBefore = mockGetCustomers.mock.calls.length
    mockGetCustomers.mockResolvedValue(paged([customerRow], 3))
    await user.click(screen.getByTestId('customers-load-error-retry'))
    await waitFor(() => expect(container.textContent).toContain('共 3 条记录'))
    expect(mockGetCustomers.mock.calls.length).toBeGreaterThan(callsBefore)
  }, TEST_TIMEOUT)

  it('对照读数：读成功但确实没有客户 ⇒ 分页照旧印「共 0 条记录」', async () => {
    mockGetCustomers.mockResolvedValue(paged([], 0))
    const { container } = render(<CustomersPage />)
    await waitFor(() => expect(container.textContent).toContain('共 0 条记录'))
    expect(screen.queryByTestId('customers-load-error')).toBeNull()
  }, TEST_TIMEOUT)
})

describe('#6703 ③ /after-sales：读失败 ⇒ 计数行不可信 + 不冒充「暂无售后工单」', () => {
  it('失败：零「共 0 条」、有 after-sales-load-error、且不出现空态话术；重试后恢复', async () => {
    const user = userEvent.setup({ delay: null })
    mockGetTickets.mockRejectedValueOnce(apiFail())
    const { container } = render(<AfterSalesPage />)

    const alert = await screen.findByTestId('after-sales-load-error')
    expect(alert).toHaveTextContent('售后工单加载失败')
    expect(container.textContent).not.toMatch(NO_FAKE_ZERO)
    expect(container.textContent).toContain('共 — 条记录')
    // 不冒充空态（#6691 同族）：读不到时不说「暂无售后工单」
    expect(screen.queryByText('暂无售后工单')).toBeNull()

    const callsBefore = mockGetTickets.mock.calls.length
    mockGetTickets.mockResolvedValue(paged([ticketRow], 2))
    await user.click(screen.getByTestId('after-sales-load-error-retry'))
    await waitFor(() => expect(container.textContent).toContain('共 2 条记录'))
    expect(mockGetTickets.mock.calls.length).toBeGreaterThan(callsBefore)
  }, TEST_TIMEOUT)

  it('对照读数：读成功但没有工单 ⇒ 空态话术照旧', async () => {
    mockGetTickets.mockResolvedValue(paged([], 0))
    render(<AfterSalesPage />)
    expect(await screen.findByText('暂无售后工单')).toBeInTheDocument()
    expect(screen.queryByTestId('after-sales-load-error')).toBeNull()
  }, TEST_TIMEOUT)
})

describe('#6703 ④ /knowledge：卡片列表读失败 ⇒ 计数行不可信 + 不冒充空态', () => {
  it('失败：零「共 0 条」、有 knowledge-load-error、且不出现空态话术；重试后恢复', async () => {
    const user = userEvent.setup({ delay: null })
    mockGetCards.mockRejectedValueOnce(apiFail())
    const { container } = render(<KnowledgePage />)

    const alert = await screen.findByTestId('knowledge-load-error')
    expect(alert).toHaveTextContent('知识卡片加载失败')
    expect(container.textContent).not.toMatch(NO_FAKE_ZERO)
    expect(container.textContent).toContain('共 — 条记录')
    expect(container.textContent).not.toContain('暂无知识卡片')

    const callsBefore = mockGetCards.mock.calls.length
    mockGetCards.mockResolvedValue(paged([cardRow], 5))
    await user.click(screen.getByTestId('knowledge-load-error-retry'))
    await waitFor(() => expect(container.textContent).toContain('共 5 条记录'))
    expect(mockGetCards.mock.calls.length).toBeGreaterThan(callsBefore)
  }, TEST_TIMEOUT)
})

describe('#6703 ⑤ /finance：资金流水 / 对账 / 汇总三段读失败，各自的计数位都不可信', () => {
  it('流水读失败：零「共 0 条记录」、有 finance-load-error；重试后恢复真实 total', async () => {
    const user = userEvent.setup({ delay: null })
    mockGetTransactions.mockRejectedValueOnce(apiFail())
    const { container } = render(<FinancePage />)

    // 资金流水是默认 tab
    const alert = await screen.findByTestId('finance-load-error')
    expect(alert).toHaveTextContent('资金流水加载失败')
    expect(container.textContent).not.toMatch(NO_FAKE_ZERO)
    expect(container.textContent).toContain('共 — 条记录')

    const callsBefore = mockGetTransactions.mock.calls.length
    mockGetTransactions.mockResolvedValue(paged([txnRow], 4))
    await user.click(screen.getByTestId('finance-load-error-retry'))
    await waitFor(() => expect(container.textContent).toContain('共 4 条记录'))
    expect(mockGetTransactions.mock.calls.length).toBeGreaterThan(callsBefore)
  }, TEST_TIMEOUT)

  it('汇总读失败：金额位印「—」（不是 ¥0.00）+ finance-summary-load-error', async () => {
    mockGetSummary.mockRejectedValueOnce(apiFail())
    const { container } = render(<FinancePage />)

    const alert = await screen.findByTestId('finance-summary-load-error')
    expect(alert).toHaveTextContent('收支汇总加载失败')
    // 🔴 改前这四张卡片的金额位会印 ¥0.00 ⇒ 会被读成「本期没进账」
    expect(container.textContent).not.toContain('¥0.00')
    expect(container.textContent).toContain('—')
  }, TEST_TIMEOUT)

  it('对账读失败：零「共 0 条记录」+ finance-reconciliation-load-error（切到对账 tab）', async () => {
    const user = userEvent.setup({ delay: null })
    mockGetReconciliation.mockRejectedValue(apiFail())
    const { container } = render(<FinancePage />)

    await user.click(screen.getByRole('button', { name: '应收对账' }))
    expect(await screen.findByTestId('finance-reconciliation-load-error')).toBeInTheDocument()
    expect(container.textContent).not.toMatch(NO_FAKE_ZERO)
  }, TEST_TIMEOUT)
})

describe('#6703 ⑥ /stock-ledger：流水读失败 ⇒ 「共 — 条」+ 真重发出口', () => {
  it('失败：零「共 0 条」、零「暂无库存流水」、有 stock-ledger-error；重试后恢复真实 total', async () => {
    const user = userEvent.setup({ delay: null })
    mockLedger.mockRejectedValueOnce(apiFail())
    const { container } = render(<StockLedgerPage />)

    const alert = await screen.findByTestId('stock-ledger-error')
    expect(alert).toHaveTextContent('库存明细读取失败')
    expect(container.textContent).not.toMatch(NO_FAKE_ZERO)
    expect(screen.queryByText('暂无库存流水')).toBeNull()

    const callsBefore = mockLedger.mock.calls.length
    mockLedger.mockResolvedValue(paged([ledgerRow], 9))
    await user.click(screen.getByTestId('stock-ledger-error-retry'))
    await waitFor(() => expect(container.textContent).toContain('共 9 条'))
    expect(mockLedger.mock.calls.length).toBeGreaterThan(callsBefore)
  }, TEST_TIMEOUT)

  it('对照读数：读成功但没有流水 ⇒ 空态话术照旧 + 计数行印「共 0 条」', async () => {
    mockLedger.mockResolvedValue(paged([], 0))
    render(<StockLedgerPage />)
    expect(await screen.findByText('暂无库存流水')).toBeInTheDocument()
    expect(screen.getByTestId('ledger-total')).toHaveTextContent('共 0 条')
    expect(screen.queryByTestId('stock-ledger-error')).toBeNull()
  }, TEST_TIMEOUT)
})
