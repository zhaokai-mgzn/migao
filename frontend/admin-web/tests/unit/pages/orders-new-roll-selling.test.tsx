// case_ids: OR-046
// @vitest-environment jsdom
/**
 * 下单页**整卷售卖**录入（issue #5846）—— 订单行的两个可录入字段：**卷数 + 每卷实际米数**。
 *
 * 用户 2026-10-01 裁定 A（原话：「订单中售卖整卷布料时，应该有卷数和实际米数两字段」）：
 * 复用既有列 `order_items.roll_count` / `order_items.roll_length_m`（**不加迁移**）；
 * 下单页在**布料行**（整卷售卖就是卖布）给出这两格，`每卷米数` 默认带出商品
 * `products.roll_length_m`，并**实时显示**「整卷合计 = 卷数 × 每卷米数」与行米数的差额。
 *
 * 判据（逐条对应 issue 的验收判据）：
 * ① 填「卷数 2 / 每卷 58.5」⇒ 提交 payload 带 `rollCount=2` `rollLengthM=58.5`；
 * ② **两格都没动** ⇒ 请求**不带这两个键**（由服务端 `ProductRollAllocation` 派生，
 *    与改造前的请求体**逐字节相同**）；
 * ③ 每卷米数**默认带出商品卷长**（商品配了 58.5 ⇒ 框里就是 58.5）；
 * ④ 负差额（整卷合计 > 行米数）⇒ **显式标红提示** + `quantity` **未被自动改写**
 *    （payload 的 quantity 与用户输入逐值相同）；
 * ⑤ 非法值（卷数 < 0 / 卷数非整数 / 每卷米数 ≤ 0）⇒ **阻止提交**并给出可行动文案
 *    （服务端另有一道 422，见 `OrderServiceTest` 的 #5846 段）；
 * ⑤d/⑤e **2026-10-01 二次裁定（取消「成对」契约）**：只给一个也是合法输入 ——
 *    只给每卷米数 ⇒ payload 只带 `rollLengthM`；只给卷数 ⇒ payload 只带 `rollCount`
 *    （缺的那半由服务端**回落**：显式 ?? 货号卷长，回落不到保持 NULL）。
 *
 * 红证（删实现那行 ⇒ 必红）：删 `handleSubmit` 里的两个键 ⇒ 判据 ① 红；
 * 无条件带上两个键 ⇒ 判据 ② 红；删默认带出 ⇒ 判据 ③ 红；删差额块 ⇒ 判据 ④ 红；
 * 删 `validate()` 里那两条边界 ⇒ 判据 ⑤ 红；把 `rollFieldsOf` 写回「成对」形态 ⇒ 判据 ⑤d/⑤e 红。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const mockCreateOrder = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProcessingItems = vi.fn()
const mockGetCustomers = vi.fn()
const mockCraftCalcPreview = vi.fn()
const mockFeePreview = vi.fn()
const mockDoorWidthPlan = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: { createOrder: (...a: unknown[]) => mockCreateOrder(...a) },
  productApi: {
    getProducts: (...a: unknown[]) => mockGetProducts(...a),
    getProduct: (...a: unknown[]) => mockGetProduct(...a),
  },
  processingItemApi: { getProcessingItems: (...a: unknown[]) => mockGetProcessingItems(...a) },
  customerApi: { getCustomers: (...a: unknown[]) => mockGetCustomers(...a) },
  craftCalcApi: { preview: (...a: unknown[]) => mockCraftCalcPreview(...a) },
  autoFeaturesApi: {
    preview: () =>
      Promise.resolve({
        data: { data: { auto_features: [], door_width: null, fullness_used: 2.0, notice: 'missing-door-width' } },
      }),
  },
  feePreviewApi: { preview: (...a: unknown[]) => mockFeePreview(...a) },
  doorWidthPlanApi: { preview: (...a: unknown[]) => mockDoorWidthPlan(...a) },
  productionApi: {
    getCraftCalcConfig: () =>
      Promise.resolve({
        data: {
          data: {
            source: 'default',
            config: {
              per_fold_single: 0.25,
              per_fold_mixed_times: {},
              margin_single: 0.3,
              margin_multi: 0.3,
              min_fullness: 1.5,
              tiers: { standard: { fullness: 2.0, label: '标准档' } },
              default_formula: 'pleat',
              meters_rounding_step: 0.1,
            },
          },
        },
      }),
  },
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import NewOrderPage from '@/app/(dashboard)/orders/new/page'

/** 商品卷长（`products.roll_length_m`）—— 下单页的**默认带出值** */
const PRODUCT_ROLL_LENGTH = 58.5

const stubApis = () => {
  vi.clearAllMocks()
  mockGetProducts.mockResolvedValue({
    data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
  })
  mockGetProduct.mockResolvedValue({
    data: {
      data: {
        id: 'p1',
        name: '遮光窗帘',
        skus: [],
        price: 100,
        rollLengthM: PRODUCT_ROLL_LENGTH,
      },
    },
  })
  mockGetProcessingItems.mockResolvedValue({ data: { data: { items: [] } } })
  mockGetCustomers.mockResolvedValue({ data: { data: { items: [] } } })
  mockCraftCalcPreview.mockResolvedValue({ data: { data: null } })
  mockDoorWidthPlan.mockResolvedValue({ data: { data: null } })
  mockFeePreview.mockResolvedValue({
    data: { data: { items: [{ processingFee: 0, processingFeeDetail: null }], processingFeeTotal: 0 } },
  })
}

/** 选商品 → 切「布料」售卖形态（整卷售卖 = 卖整卷布）⇒ 布料行有 数量 / 单价 / 卷数 / 每卷米数 */
async function setupFabricLine() {
  render(<NewOrderPage />)
  fireEvent.click(await screen.findByText('点击搜索并选择商品'))
  fireEvent.click(await screen.findByText('遮光窗帘'))
  fireEvent.click(await screen.findByRole('radio', { name: '布料' }))
  await screen.findByLabelText('卷数')
}

const inputByLabel = (label: string) => screen.getByLabelText(label) as HTMLInputElement

const setLine = (opts: { qty?: string; price?: string; rolls?: string; rollLength?: string }) => {
  if (opts.qty !== undefined) fireEvent.change(inputByLabel('数量'), { target: { value: opts.qty } })
  if (opts.price !== undefined) fireEvent.change(inputByLabel('单价 (¥/米)'), { target: { value: opts.price } })
  if (opts.rolls !== undefined) fireEvent.change(inputByLabel('卷数'), { target: { value: opts.rolls } })
  if (opts.rollLength !== undefined)
    fireEvent.change(inputByLabel('每卷米数'), { target: { value: opts.rollLength } })
}

const fillCustomer = () => {
  fireEvent.change(screen.getByPlaceholderText('请输入收货人姓名'), { target: { value: '张三' } })
  fireEvent.change(screen.getByPlaceholderText('请输入 11 位手机号'), { target: { value: '13800138000' } })
  fireEvent.change(screen.getByPlaceholderText('请输入详细收货地址'), { target: { value: '杭州市' } })
}

const submit = async () => {
  fillCustomer()
  await waitFor(() => expect(screen.queryByText(/加工费计价中/)).toBeNull())
  fireEvent.click(screen.getByText('提交订单'))
}

const submittedItem = async (): Promise<Record<string, unknown>> => {
  await submit()
  await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
  return mockCreateOrder.mock.calls[0][0].items[0]
}

describe('下单页整卷售卖录入（#5846）', () => {
  beforeEach(stubApis)

  it('判据 3：每卷米数**默认带出商品卷长**（products.roll_length_m）', async () => {
    await setupFabricLine()
    expect(inputByLabel('每卷米数')).toHaveValue(String(PRODUCT_ROLL_LENGTH))
  })

  it('判据 1：填「卷数 2 / 每卷 58.5」⇒ 提交 payload 带 rollCount=2 与 rollLengthM=58.5', async () => {
    await setupFabricLine()
    setLine({ qty: '120', price: '100', rolls: '2', rollLength: '58.5' })

    const item = await submittedItem()

    expect(item.rollCount).toBe(2)
    expect(item.rollLengthM).toBe(58.5)
  })

  it('判据 2：卷数**留空** ⇒ 请求**不带**这两个键（服务端派生，与改造前逐字节相同）', async () => {
    await setupFabricLine()
    // 前提自证：商品卷长确实带出到框里了（否则「不带键」可能只是因为整个字段没接线）
    expect(inputByLabel('每卷米数')).toHaveValue(String(PRODUCT_ROLL_LENGTH))
    setLine({ qty: '120', price: '100' })

    const item = await submittedItem()

    expect('rollCount' in item).toBe(false)
    expect('rollLengthM' in item).toBe(false)
  })

  it('判据 4：负差额（2 × 58.5 = 117 > 行米数 100）⇒ 显式提示，且**不改写**行米数', async () => {
    await setupFabricLine()
    setLine({ qty: '100', price: '100', rolls: '2', rollLength: '58.5' })

    // ① 页面上看得见差额（整卷合计 117 米 vs 行米数 100 米）
    const warn = await screen.findByTestId('roll-diff-warning')
    expect(warn.textContent).toContain('117')
    expect(warn.textContent).toContain('100')
    expect(warn.textContent).not.toContain('NaN')
    // ② 输入框里的米数**一点没动**（人决定改哪个，系统不改）
    expect(inputByLabel('数量')).toHaveValue('100')

    // ③ 提交的 payload 里 quantity 与用户输入逐值相同
    const item = await submittedItem()
    expect(item.quantity).toBe(100)
    expect(item.rollCount).toBe(2)
    expect(item.rollLengthM).toBe(58.5)
  })

  it('判据 4b：正差额（2 × 58.5 = 117 ≤ 120）⇒ 只显示合计与差额，不报异常', async () => {
    await setupFabricLine()
    setLine({ qty: '120', price: '100', rolls: '2', rollLength: '58.5' })

    expect((await screen.findByTestId('roll-diff')).textContent).toContain('117')
    expect(screen.queryByTestId('roll-diff-warning')).toBeNull()
  })

  it('判据 5：非法值（卷数 -1）⇒ 阻止提交并给出可行动文案', async () => {
    await setupFabricLine()
    setLine({ qty: '100', price: '100', rolls: '-1', rollLength: '58.5' })

    await submit()

    expect(await screen.findByText(/卷数不能为负数|卷数必须/)).toBeInTheDocument()
    expect(mockCreateOrder).not.toHaveBeenCalled()
  })

  it('判据 5b：卷数非整数（2.5）⇒ 阻止提交（**不静默取整成 2 卷**）', async () => {
    await setupFabricLine()
    setLine({ qty: '100', price: '100', rolls: '2.5', rollLength: '58.5' })

    await submit()

    expect(await screen.findByText(/卷数必须是整数/)).toBeInTheDocument()
    expect(mockCreateOrder).not.toHaveBeenCalled()
  })

  it('判据 5c：每卷米数 ≤ 0 ⇒ 阻止提交', async () => {
    await setupFabricLine()
    setLine({ qty: '100', price: '100', rolls: '2', rollLength: '0' })

    await submit()

    expect(await screen.findByText(/每卷米数必须大于 0/)).toBeInTheDocument()
    expect(mockCreateOrder).not.toHaveBeenCalled()
  })

  it('判据 5c′：卷数留空、每卷米数 0 ⇒ 同样拦住（列不合法就拦，与填没填卷数无关）', async () => {
    await setupFabricLine()
    setLine({ qty: '100', price: '100', rollLength: '0' })
    fireEvent.change(inputByLabel('卷数'), { target: { value: '' } })

    await submit()

    expect(await screen.findByText(/每卷米数必须大于 0/)).toBeInTheDocument()
    expect(mockCreateOrder).not.toHaveBeenCalled()
  })

  // ===== 2026-10-01 用户**二次裁定：取消「成对」契约** ⇒ 下面两条是**改判**（不是删除） =====
  it('判据 5d（改判）：卷数留空但**改过**每卷米数 ⇒ **允许提交**，payload 只带 rollLengthM（服务端据此派生卷数）', async () => {
    await setupFabricLine()
    setLine({ qty: '100', price: '100', rollLength: '30' }) // 改过：商品卷长是 58.5
    // 前提自证：改的确实是**框里的值**（否则下面的 payload 断言是空断言）
    expect(inputByLabel('每卷米数')).toHaveValue('30')
    expect(inputByLabel('卷数')).toHaveValue('')

    const item = await submittedItem()

    expect(item.rollLengthM).toBe(30)
    expect('rollCount' in item).toBe(false) // 缺的那半由服务端派生（floor(数量 / 30)）
  })

  it('判据 5e（改判新增）：卷数填了、每卷米数**留空** ⇒ payload 只带 rollCount（卷长回落货号值）', async () => {
    await setupFabricLine()
    setLine({ qty: '100', price: '100', rolls: '2' })
    fireEvent.change(inputByLabel('每卷米数'), { target: { value: '' } })
    expect(inputByLabel('每卷米数')).toHaveValue('')

    const item = await submittedItem()

    expect(item.rollCount).toBe(2)
    expect('rollLengthM' in item).toBe(false) // 缺的那半由服务端回落货号卷长
  })
})
