// case_ids: UI-057, UI-058, UI-074, OR-001, OR-046, UI-087, UI-089
/**
 * 「读面失败不得伪装成空态」——**实例判据**（issue #6691，#6664 的未收口余项）。
 *
 * ## 为什么单独一个文件
 *
 * 类级元守卫 `tests/unit/read-failure-empty-state-guard.test.ts`（issue #6663）判的是**源码形态**
 * （`catch` 清空读数且不表达失败 ⇒ 必须登记进台账）。它能逼人把台账条目删干净，却**判不了**
 * 「失败态**真的渲染到屏上**、并且给了出口」—— 把 `catch` 改成 `setError('')` 也能绕过扫描。
 * 本文件补的正是那一半：**用 mock 接口失败造**的实例判据，逐页断言
 *
 *   ① 失败态**在屏上**（`findByTestId`，不是只断言 `setX([])` 这类实现细节）；
 *   ② **不冒充空态**（空态话术在失败时**不得**出现 —— 那正是「我的入库单怎么全不见了」的病灶）；
 *   ③ 有**重试出口**：点一下真的**重新发请求**（有的页面还要断言重试后失败态消失）。
 *
 * 🔴 三条反假绿约束（`migao-acceptance`）：
 *   - 失败一律来自 **mock 接口 reject**（不依赖真实服务不可达 —— 那会把「页面坏了」伪装成被测行为）；
 *   - 命中型用例的判别力来自「失败态锚点**只**由本次修复新增」⇒ 改前 `findByTestId` 必红；
 *   - 对照型用例**必须钉正向读数**（当下渲染出来的东西 + 读面真被调用过），不许写成
 *     「`queryByTestId` 为 null」这种改前改后都绿的**空断言**。
 *
 * ## 覆盖的七点（= #6663 台账里那 7 条的全部）
 *
 * | # | 页面 | 读面 | 失败态锚点 |
 * |---|---|---|---|
 * | 1 | `/inbound-orders` | 入库单列表 | `inbound-load-error` + 「重新加载」 |
 * | 2 | `/inbound-orders/new` | 商品搜索 | `inbound-product-search-error` + 「重试」 |
 * | 3 | `/inbound-orders/new` | 选中商品的规格明细 | `inbound-sku-error` + 「重试」 |
 * | 4 | `/orders/[id]` | 发货明细（纸面数量列的实发来源） | `order-shipments-read-error` + 「重试」 |
 * | 5 | `/orders/new` | 加工项目录 | `orders-new-processing-catalog-error` + 「重试」 |
 * | 6 | `/orders/new` | 算料配置 | `craft-calc-config-missing`（既有形态，本次补**实例判据**） |
 * | 7 | `/stock-ledger` | 商品搜索（灰区） | `stock-ledger-search-hint`（`role="alert"`）+ 「重试商品搜索」 |
 *
 * 🔴 每个用例都带 `TEST_TIMEOUT`：失败态等到底时走 RTL 的 5s `asyncUtilTimeout`，
 * 若整例上限还是 5s，「失败态没渲染出来」会以 `Test timed out` 出现（= **没跑到断言**，
 * 读数会骗人）—— 拉长整例预算，让红**显形为断言失败**。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { markErrorToastShown } from '@/lib/api-error'

const TEST_TIMEOUT = 20_000
/** `delay: null`：本文件不测输入时序 ⇒ 省掉逐键排队（判据强度不变） */
const setupUser = () => userEvent.setup({ delay: null })

// ── 登录态（`/inbound-orders` 的建单按钮按 `inbound:create` 显隐，`usePermission` 走 selector）──
const authMock = vi.hoisted(() => ({
  state: {
    user: { id: '1', username: 'admin', name: '管理员', permissions: ['*'] as string[], roles: [] as string[] },
  },
}))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) =>
    typeof selector === 'function' ? selector(authMock.state) : authMock.state,
}))

// ── 每页读面的替身（失败 = reject，**不依赖真实服务不可达**）──
const mockInboundList = vi.fn()
const mockInboundCreate = vi.fn()
const mockInboundDetail = vi.fn()
const mockInboundPost = vi.fn()
const mockInboundCancel = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetOrder = vi.fn()
const mockGetOrderShipments = vi.fn()
const mockProcessings = vi.fn()
const mockCalcConfig = vi.fn()
const mockLedger = vi.fn()
const mockBatches = vi.fn()
const mockCustomers = vi.fn()

vi.mock('@/lib/api', () => ({
  inboundOrderApi: {
    list: (...a: unknown[]) => mockInboundList(...a),
    detail: (...a: unknown[]) => mockInboundDetail(...a),
    create: (...a: unknown[]) => mockInboundCreate(...a),
    post: (...a: unknown[]) => mockInboundPost(...a),
    cancel: (...a: unknown[]) => mockInboundCancel(...a),
  },
  productApi: {
    getProducts: (...a: unknown[]) => mockGetProducts(...a),
    getProduct: (...a: unknown[]) => mockGetProduct(...a),
  },
  orderApi: {
    getOrder: (...a: unknown[]) => mockGetOrder(...a),
    getOrderShipments: (...a: unknown[]) => mockGetOrderShipments(...a),
  },
  processingItemApi: { getProcessingItems: (...a: unknown[]) => mockProcessings(...a) },
  productionApi: { getCraftCalcConfig: (...a: unknown[]) => mockCalcConfig(...a) },
  customerApi: { getCustomers: (...a: unknown[]) => mockCustomers(...a) },
  stockLedgerApi: { ledger: (...a: unknown[]) => mockLedger(...a) },
  batchStockApi: { batches: (...a: unknown[]) => mockBatches(...a) },
  // 与「读失败 ≠ 空态」正交的读面：挂起即可（不 resolve 也不 reject，页面读数不依赖它们）
  craftCalcApi: { preview: () => new Promise(() => {}) },
  autoFeaturesApi: {
    preview: () => Promise.resolve({ data: { data: { auto_features: [], door_width: null, fullness_used: 2.0, notice: 'missing-door-width' } } }),
  },
  doorWidthPlanApi: { preview: () => new Promise(() => {}) },
  feePreviewApi: { preview: () => new Promise(() => {}) },
}))

vi.mock('@/lib/use-route-id', () => ({ useRouteId: () => 'test-order-123' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }))

import InboundOrdersPage from '@/app/(dashboard)/inbound-orders/page'
import NewInboundOrderPage from '@/app/(dashboard)/inbound-orders/new/page'
import OrderDetailPage from '@/app/(dashboard)/orders/[id]/OrderDetail'
import NewOrderPage from '@/app/(dashboard)/orders/new/page'
import StockLedgerPage from '@/app/(dashboard)/stock-ledger/page'

/** 服务端信封 */
const ok = (data: unknown) => ({ data: { data } })
const paged = (items: unknown[], total = items.length) => ok({ items, total, page: 1, size: 20 })

/**
 * 造一个**已被统一拦截器 toast 过**的错误（页面 `catch` 里的 `toastRequestError`
 * 再弹一次会变成「同一次失败弹两条」——那正是拦截器去重要治的形态）。
 */
const apiFail = () => {
  const e = new Error('接口挂了（mock）')
  markErrorToastShown(e)
  return e
}

const inboundRow = {
  id: 'o-1',
  inboundNo: 'RK-20261010-0001',
  inboundDate: '2026-10-10',
  supplier: '柯桥××布行',
  warehouse: '一号仓',
  status: 'posted' as const,
  totalAmount: 375,
  itemCount: 1,
  totalQuantity: 30,
}

const orderStub = {
  id: 'test-order-123',
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

beforeEach(() => {
  vi.clearAllMocks()
  mockInboundList.mockResolvedValue(ok([inboundRow]))
  mockGetProducts.mockResolvedValue(paged([{ id: 'prod-1', name: '遮光窗帘布料' }]))
  mockGetProduct.mockResolvedValue(ok({
    id: 'prod-1',
    name: '遮光窗帘布料',
    skus: [{ id: 'sku-1', colorName: '米白', doorWidth: '2.8', stock: 30 }],
  }))
  mockGetOrder.mockResolvedValue(ok(orderStub))
  mockGetOrderShipments.mockResolvedValue(ok({ order_id: 'test-order-123', status: 'producing', shipments: [] }))
  mockProcessings.mockResolvedValue(paged([]))
  mockCalcConfig.mockResolvedValue(ok({
    source: 'stored',
    config: { tiers: { standard: { fullness: 2.0, label: '标准档' } }, default_formula: 'pleat' },
  }))
  mockLedger.mockResolvedValue(paged([]))
  mockBatches.mockResolvedValue(ok([]))
  mockCustomers.mockResolvedValue(paged([]))
})

describe('#6691 ① 入库单列表：读失败 ⇒「加载失败 + 重新加载」，不画成「暂无入库单」', () => {
  it('失败态在屏上 + 有出口（点「重新加载」真的重发请求，成功后失败态消失）', async () => {
    const user = setupUser()
    mockInboundList.mockRejectedValueOnce(apiFail())
    render(<InboundOrdersPage />)

    const alert = await screen.findByTestId('inbound-load-error')
    expect(alert).toHaveTextContent('入库单加载失败')
    // 🔴 不冒充空态：失败时**不得**出现「暂无入库单」
    expect(screen.queryByText('暂无入库单')).toBeNull()

    // 出口：点「重新加载」真的重发请求；成功后失败态消失、数据上屏
    mockInboundList.mockResolvedValue(ok([inboundRow]))
    await user.click(screen.getByTestId('inbound-load-retry'))
    await waitFor(() => expect(screen.getByText('RK-20261010-0001')).toBeInTheDocument())
    expect(screen.queryByTestId('inbound-load-error')).toBeNull()
  }, TEST_TIMEOUT)

  it('对照读数：读成功且真的没有数据 ⇒ 仍然是「暂无入库单」（失败态**没有**把空态吃掉）', async () => {
    mockInboundList.mockResolvedValue(ok([]))
    render(<InboundOrdersPage />)
    expect(await screen.findByText('暂无入库单')).toBeInTheDocument()
    expect(screen.queryByTestId('inbound-load-error')).toBeNull()
  }, TEST_TIMEOUT)
})

describe('#6691 ② 新建入库单：商品搜索失败 ⇒ 说「搜索失败 + 重试」，不画成「搜不到」', () => {
  it('失败态在屏上 + 不冒充「输入关键词搜索商品」空态 + 重试后能选到商品', async () => {
    const user = setupUser()
    mockGetProducts.mockRejectedValueOnce(apiFail())
    render(<NewInboundOrderPage />)

    const alert = await screen.findByTestId('inbound-product-search-error')
    expect(alert).toHaveTextContent('商品搜索失败')
    // 🔴 不冒充空态：那格写着「输入关键词搜索商品」= 把故障说成「你还没搜」
    expect(screen.queryByText('输入关键词搜索商品')).toBeNull()

    mockGetProducts.mockResolvedValue(paged([{ id: 'prod-1', name: '遮光窗帘布料' }]))
    await user.click(screen.getByTestId('inbound-product-search-retry'))
    expect(await screen.findByText('遮光窗帘布料')).toBeInTheDocument()
    expect(screen.queryByTestId('inbound-product-search-error')).toBeNull()
  }, TEST_TIMEOUT)

  it('对照读数：搜索成功但 0 条 ⇒ 仍是「输入关键词搜索商品」引导（不是失败话术，也没有重试出口）', async () => {
    mockGetProducts.mockResolvedValue(paged([]))
    render(<NewInboundOrderPage />)
    expect(await screen.findByText('输入关键词搜索商品')).toBeInTheDocument()
    expect(screen.queryByTestId('inbound-product-search-error')).toBeNull()
    expect(screen.queryByTestId('inbound-product-search-retry')).toBeNull()
  }, TEST_TIMEOUT)
})

describe('#6691 ③ 新建入库单：选中商品的规格明细读失败 ⇒ 说「读取失败 + 重试」，不画成「这个商品没有规格」', () => {
  it('失败态在屏上 + 不冒充「该商品还没有 SKU」+ 重试后规格出现、失败态消失', async () => {
    const user = setupUser()
    mockGetProduct.mockRejectedValueOnce(apiFail())
    render(<NewInboundOrderPage />)

    await user.click(await screen.findByText('遮光窗帘布料'))
    const alert = await screen.findByTestId('inbound-sku-error')
    expect(alert).toHaveTextContent('规格读取失败')
    // 🔴 不冒充空态：那是**数据事实**（该商品真的没维护 SKU），读失败时不得出现
    expect(screen.queryByText(/该商品还没有 SKU/)).toBeNull()

    mockGetProduct.mockResolvedValue(ok({
      id: 'prod-1',
      name: '遮光窗帘布料',
      skus: [{ id: 'sku-1', colorName: '米白', doorWidth: '2.8', stock: 30 }],
    }))
    await user.click(screen.getByTestId('inbound-sku-retry'))
    expect(await screen.findByText(/米白/)).toBeInTheDocument()
    expect(screen.queryByTestId('inbound-sku-error')).toBeNull()
  }, TEST_TIMEOUT)

  it('对照读数：详情读成功且该商品真的没有 SKU ⇒ 仍是「该商品还没有 SKU」空态（无重试出口）', async () => {
    const user = setupUser()
    mockGetProduct.mockResolvedValue(ok({ id: 'prod-1', name: '遮光窗帘布料', skus: [] }))
    render(<NewInboundOrderPage />)
    await user.click(await screen.findByText('遮光窗帘布料'))
    expect(await screen.findByText(/该商品还没有 SKU/)).toBeInTheDocument()
    expect(screen.queryByTestId('inbound-sku-error')).toBeNull()
    expect(screen.queryByTestId('inbound-sku-retry')).toBeNull()
  }, TEST_TIMEOUT)
})

describe('#6691 ④ 订单详情：发货明细读失败 ⇒ 失败态可见 + 有重试出口', () => {
  it('失败态在屏上（说清是哪一块读不到）+ 点「重试」真的重发读请求并让失败态消失', async () => {
    const user = setupUser()
    mockGetOrderShipments.mockRejectedValueOnce(apiFail())
    render(<OrderDetailPage />)

    const alert = await screen.findByTestId('order-shipments-read-error')
    expect(alert).toHaveTextContent('发货明细读取失败')
    expect(alert).toHaveTextContent('重试')

    const before = mockGetOrderShipments.mock.calls.length
    await user.click(screen.getByTestId('order-shipments-retry'))
    await waitFor(() => expect(mockGetOrderShipments.mock.calls.length).toBeGreaterThan(before))
    await waitFor(() => expect(screen.queryByTestId('order-shipments-read-error')).toBeNull())
  }, TEST_TIMEOUT)

  it('对照读数：发货明细读成功 ⇒ 订单内容照常上屏 + **没有**失败态（不误报）', async () => {
    render(<OrderDetailPage />)
    // 「订单详情」在面包屑与页标题各一处 ⇒ 用 findAllByText（`findByText` 会因多处命中而红）
    expect((await screen.findAllByText('订单详情')).length).toBeGreaterThanOrEqual(1)
    await waitFor(() => expect(mockGetOrderShipments).toHaveBeenCalled())
    expect(screen.queryByTestId('order-shipments-read-error')).toBeNull()
  }, TEST_TIMEOUT)
})

describe('#6691 ⑤ 新建订单：加工项目录读失败 ⇒ 说「目录加载失败 + 重试」，不画成「这个商品没有加工项」', () => {
  it('失败态在屏上 + 有出口（点「重试」重读目录，成功后失败态消失）', async () => {
    const user = setupUser()
    mockProcessings.mockRejectedValueOnce(apiFail())
    render(<NewOrderPage />)

    const alert = await screen.findByTestId('orders-new-processing-catalog-error')
    expect(alert).toHaveTextContent('加工项目录加载失败')
    expect(alert).toHaveTextContent('重试')

    mockProcessings.mockResolvedValue(paged([]))
    await user.click(screen.getByTestId('orders-new-processing-catalog-retry'))
    await waitFor(() => expect(mockProcessings.mock.calls.length).toBeGreaterThan(1))
    await waitFor(() => expect(screen.queryByTestId('orders-new-processing-catalog-error')).toBeNull())
  }, TEST_TIMEOUT)

  it('对照读数：目录读成功 ⇒ 页头在、**没有**失败态（不误报）', async () => {
    render(<NewOrderPage />)
    expect(await screen.findByText('新增订单')).toBeInTheDocument()
    expect(screen.queryByTestId('orders-new-processing-catalog-error')).toBeNull()
  }, TEST_TIMEOUT)
})

describe('#6691 ⑥ 新建订单：算料配置读失败 ⇒ 显式「配置未加载」，不静默按缺省口径算', () => {
  /**
   * 「配置未加载」提示挂在**行项的工艺规格**里（`OrderCraftFields` 消费 `calcConfig === null`）
   * ⇒ 得先把页面驱动到那一块渲染出来（选商品 + 填净尺寸；配置读失败时推导方案未就绪，
   * 「改工艺参数」默认展开 ⇒ 提示可见）。驱动三步与 `orders-new.test.tsx` 的 `setupCurtain` 同形。
   */
  const driveToCraftFields = async () => {
    fireEvent.click(await screen.findByText('点击搜索并选择商品'))
    fireEvent.click(await screen.findByText('遮光窗帘布料'))
    await screen.findByText('窗宽 (米)')
    const pick = (label: string) =>
      screen.getAllByText(label).map((el) => el.closest('div')!.querySelector('input') as HTMLInputElement)
    fireEvent.change(pick('窗宽 (米)')[0], { target: { value: '6.6' } })
    fireEvent.change(pick('窗高 (米)')[0], { target: { value: '2.6' } })
  }

  it('失败态在屏上（指名是算料配置读取失败 + 本次按什么口径走）', async () => {
    mockCalcConfig.mockRejectedValueOnce(apiFail())
    render(<NewOrderPage />)
    await driveToCraftFields()

    const hint = await screen.findByTestId('craft-calc-config-missing')
    // 判别力自证：提示所在的「工艺规格」区块**确实渲染出来了**（不是空页面里的孤儿节点）
    expect(screen.getByTestId('craft-plan-edit')).toBeInTheDocument()
    expect(hint).toHaveTextContent('算料配置未加载')
    expect(hint).toHaveTextContent('读取失败')
    expect(hint).toHaveTextContent('缺省口径')
  }, TEST_TIMEOUT)

  it('对照读数：配置读成功 ⇒ 同一块工艺规格渲染出来 + **没有**「配置未加载」（不误报）', async () => {
    render(<NewOrderPage />)
    await driveToCraftFields()
    await waitFor(() => expect(mockCalcConfig).toHaveBeenCalled())
    expect(await screen.findByTestId('craft-plan-edit')).toBeInTheDocument()
    expect(screen.queryByTestId('craft-calc-config-missing')).toBeNull()
  }, TEST_TIMEOUT)
})

describe('#6691 ⑦ 库存明细：商品搜索失败 ⇒ 失败话术与空态话术**两句分立**（灰区裁定：补 alert 语义 + 重试出口）', () => {
  it('失败 ⇒「商品搜索失败」+ 可重试；搜到 0 条 ⇒「没有匹配的商品」（两句不得混用）', async () => {
    const user = setupUser()
    mockLedger.mockResolvedValue(paged([{
      id: 1, productId: 'prod-1', skuId: 9, skuCode: 'HZ-002-浅灰', delta: '-3.0', beforeQty: '50.0',
      afterQty: '47.0', reason: 'aftersales', refNo: null, note: null, unitCost: null, costAmount: null,
      avgCostBefore: null, avgCostAfter: null, operator: 'system', createdAt: '2026-10-01T10:00:00+08:00',
    }]))
    render(<StockLedgerPage />)
    await screen.findByTestId('stock-ledger-page')
    await screen.findAllByTestId('stock-ledger-row')

    // 失败：话术 = 失败 + 出口（alert 语义 + 重试按钮）
    mockGetProducts.mockRejectedValueOnce(apiFail())
    await user.type(screen.getByLabelText('搜索商品'), '遮光')
    await user.click(screen.getByRole('button', { name: '搜索商品' }))

    const alert = await screen.findByTestId('stock-ledger-search-hint')
    expect(alert).toHaveTextContent('商品搜索失败')
    expect(alert).toHaveAttribute('role', 'alert')
    expect(screen.queryByText(/没有匹配的商品/)).toBeNull()

    // 出口：点「重试商品搜索」重发一次搜索
    mockGetProducts.mockResolvedValue(paged([{ id: 'prod-1', name: '遮光窗帘布料' }]))
    await user.click(screen.getByRole('button', { name: '重试商品搜索' }))
    expect(await screen.findByTestId('product-option')).toBeInTheDocument()

    // 对照读数：搜到 0 条 = 数据事实 ⇒ 另一句（失败话术消失）
    mockGetProducts.mockResolvedValue(paged([]))
    await user.click(screen.getByRole('button', { name: '搜索商品' }))
    await waitFor(() => expect(screen.getByTestId('stock-ledger-search-hint')).toHaveTextContent('没有匹配的商品'))
  }, TEST_TIMEOUT)
})
