// case_ids: OR-036
// @vitest-environment jsdom
/**
 * 下单页数字框收敛（issue #5210）**接受的差异**的钉住测试。
 *
 * 与 `tests/unit/pages/orders-new-number-parity.test.tsx` 分工：
 * - 那个文件是**等价性**证据（同一套断言在**旧实现**（commit ①）与**新实现**（commit ②）上都绿）；
 * - 本文件钉的是**替换后才有**的形态 —— 本文件本身就是那三处差异的红证。
 *   **实测红证**：把 `frontend/admin-web/src/app/(dashboard)/orders/new/page.tsx` 换回 commit ① 的树
 *   （页面私有 `NumberField`）⇒ 本文件 **5 条差异断言全红**（另 2 条是**负控**：两版都绿 ——
 *   那正是负控的意义：它们钉的是「收敛**不得**顺手改这些」）。
 *
 * 差异清单（与 PR body / `CHANGELOG.md` 的清单一一对应）：
 * ① **负数**：旧实现把 `-` 当非法字符**整键忽略**（框里什么都没发生，值保持不变）；
 *    现在敲得出来 —— 不完整草稿（`-`）落 `null`，完整负数照旧提交给页面，由页面**既有可见校验**拦下。
 * ② **不完整输入 `.`**：旧实现提交 `Number('.') = NaN`（框里显示空白）；现在落 `null` ⇒
 *    `?? 0` 站点（数量 / 单价 / 用料米数）落 `0`，`positiveOrNull` 站点（宽 / 高 / override）落「清空」。
 * ③ **> 3 位小数**：旧实现原样保留任意位数；现在失焦按 `decimals={3}` 归一并上屏。
 *
 * ⚠️ 三条都由**页面既有校验**兜底（不新增护栏）：`数量须大于 0` / `单价须大于 0` /
 * `未填宽（米）` / `未填高（米）`；接高上限另有**就地报错**（`craft-plan-join-error`）。
 * 本文件同时钉住「**不传 `min`/`max`**」= 不做静默夹紧（接高那格页面明确要求不得把 0.15 截成 0.1）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

const mockCreateOrder = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProcessingItems = vi.fn()
const mockGetCustomers = vi.fn()
const mockCraftCalcPreview = vi.fn()
const mockGetCraftCalcConfig = vi.fn()
const mockAutoFeatures = vi.fn()
const mockDoorWidthPlan = vi.fn()
const mockFeePreview = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: { createOrder: (...a: unknown[]) => mockCreateOrder(...a) },
  productApi: {
    getProducts: (...a: unknown[]) => mockGetProducts(...a),
    getProduct: (...a: unknown[]) => mockGetProduct(...a),
  },
  processingItemApi: { getProcessingItems: (...a: unknown[]) => mockGetProcessingItems(...a) },
  customerApi: { getCustomers: (...a: unknown[]) => mockGetCustomers(...a) },
  craftCalcApi: { preview: (...a: unknown[]) => mockCraftCalcPreview(...a) },
  autoFeaturesApi: { preview: (...a: unknown[]) => mockAutoFeatures(...a) },
  doorWidthPlanApi: { preview: (...a: unknown[]) => mockDoorWidthPlan(...a) },
  productionApi: { getCraftCalcConfig: (...a: unknown[]) => mockGetCraftCalcConfig(...a) },
  feePreviewApi: { preview: (...a: unknown[]) => mockFeePreview(...a) },
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }))

import NewOrderPage from '@/app/(dashboard)/orders/new/page'

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
        tiers: { standard: { fullness: 2.0, label: '标准档' } },
        default_formula: 'pleat',
        meters_rounding_step: 0.1,
      },
    },
  },
}

const PRODUCT = {
  id: 'p1',
  name: '遮光窗帘',
  price: 100,
  basePrice: 100,
  skus: [
    { id: 'sku-28', colorId: 'c1', colorName: '米白', doorWidth: '2.8米', price: 100, stock: 10, skuCode: 'A-28' },
    { id: 'sku-32', colorId: 'c1', colorName: '米白', doorWidth: '3.2米', price: 110, stock: 5, skuCode: 'A-32' },
  ],
}

const calcResponse = (params: Record<string, unknown>) => ({
  data: {
    data: {
      fabric_meters: 13.3,
      pleat_count: 52,
      per_fold: 0.25,
      fullness: 2,
      formula_text: '(6.6+0.3)×2.0 → 52折 → 0.25×52+0.3 = 13.3米',
      source: '公式计算',
      craft_tier: 'standard',
      plan: {
        cutting_mode: (params?.cutting_mode as string) ?? '定高买宽',
        door_width: 2.8,
        panels: null,
        splice_times: 0,
        splice_option: null,
        join_height_m: (params?.join_height_m as number) ?? null,
        join_width_m: null,
        meters: 13.3,
        auto: true,
        reason: '测试桩',
        candidates: [],
      },
    },
  },
})

const inputOf = (label: string, idx = 0) =>
  screen
    .getAllByText(label)
    .map((el) => el.closest('div')!.querySelector('input') as HTMLInputElement)[idx]

const craftCalcCalls = () =>
  mockCraftCalcPreview.mock.calls.map((c) => c[0] as Record<string, unknown>)

/** 填满「必填面」（颜色 + 宽 + 高 + 门幅），让各用例只验它自己那条差异 */
async function setupCurtain() {
  render(<NewOrderPage />)
  fireEvent.click(await screen.findByText('点击搜索并选择商品'))
  fireEvent.click(await screen.findByText('遮光窗帘'))
  await screen.findByText('窗宽 (米)')
  fireEvent.click(await screen.findByRole('button', { name: '米白' }))
  fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '6.6' } })
  fireEvent.change(inputOf('窗高 (米)'), { target: { value: '2.6' } })
  fireEvent.click(await screen.findByRole('button', { name: /2\.8米/ }))
  await waitFor(() => expect(inputOf('用料米数').value).toMatch(/^13\.3/))
}

/** 点提交（收货信息填好）—— 用于读「既有可见校验」是否把非法值拦下 */
async function submitOrder() {
  fireEvent.change(screen.getByPlaceholderText('请输入收货人姓名'), { target: { value: '张三' } })
  fireEvent.change(screen.getByPlaceholderText('请输入 11 位手机号'), {
    target: { value: '13800138000' },
  })
  fireEvent.change(screen.getByPlaceholderText('请输入详细收货地址'), { target: { value: '杭州市' } })
  await waitFor(() => expect(screen.queryByText(/加工费计价中/)).toBeNull())
  fireEvent.click(screen.getByText('提交订单'))
}

beforeEach(() => {
  vi.clearAllMocks()
  mockGetProducts.mockResolvedValue({
    data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
  })
  mockGetProduct.mockResolvedValue({ data: { data: PRODUCT } })
  mockGetProcessingItems.mockResolvedValue({
    data: { data: { items: [{ id: 'pi1', name: '韩式褶', unit: '米' }] } },
  })
  mockGetCraftCalcConfig.mockResolvedValue(CALC_CONFIG_OK)
  mockCraftCalcPreview.mockImplementation((params: Record<string, unknown>) =>
    Promise.resolve(calcResponse(params))
  )
  mockAutoFeatures.mockResolvedValue({
    data: { data: { auto_features: [], door_width: null, notices: [] } },
  })
  mockDoorWidthPlan.mockResolvedValue({
    data: {
      data: {
        state: 'undecidable',
        code: 'missing-cutting-mode',
        effective_cutting_mode: null,
        door_width: null,
        panels: null,
        splice: false,
        verdict: 'unknown',
        candidates: [],
        reason: '测试桩',
      },
    },
  })
  mockFeePreview.mockResolvedValue({
    data: {
      data: {
        items: [{ processingFee: 0, processingFeeDetail: { fee_source: 'unpriced', amount: 0 } }],
        processingFeeTotal: 0,
      },
    },
  })
})

describe('#5210 接受差异 ①：负数不再被整键吞掉，改由**既有可见校验**拦下', { timeout: 20000 }, () => {
  it('用料米数敲 "-5"：框里留得住 → 提交被「数量须大于 0」拦下（不落单）', async () => {
    await setupCurtain()
    const qty = inputOf('用料米数')
    fireEvent.change(qty, { target: { value: '-5' } })
    // 旧实现：`-` 属非法字符 ⇒ **整键忽略**，框里仍是 13.3（本断言在旧实现下必红）
    expect(qty).toHaveValue('-5')
    fireEvent.blur(qty)
    // **不传 `min`** ⇒ 失焦不做静默夹紧（传了 `min={1}` 的实现：这里会变成 `1`）
    expect(qty).toHaveValue('-5')

    await submitOrder()
    expect(await screen.findByText('数量须大于 0')).toBeInTheDocument()
    expect(mockCreateOrder).not.toHaveBeenCalled()
  })

  it('窗宽敲 "-5"：被站点口径拒（`positiveOrNull`）⇒ 框清空 + 提交被「未填宽」拦下（旧实现：整键忽略，框里仍是 6.6）', async () => {
    await setupCurtain()
    const width = inputOf('窗宽 (米)')
    fireEvent.change(width, { target: { value: '-5' } })
    fireEvent.blur(width)
    // 新实现：字符合法 ⇒ 提交 -5 ⇒ 被 `positiveOrNull` 判「非正数」⇒ 落 null ⇒ 框清空
    // （同旧 `draftAlive` 的处置：草稿不再代表当前值时让位，不留「框里有数、校验说没填」的矛盾）。
    // 传了 `min={0}` 的实现：失焦会夹成 0 ⇒ 本断言红。
    expect(width).toHaveValue('')

    await submitOrder()
    expect(await screen.findByText(/未填宽（米）/)).toBeInTheDocument()
    expect(mockCreateOrder).not.toHaveBeenCalled()
  })
})

describe('#5210 接受差异 ②：不完整输入 "." 落 null（不再出现 NaN）', { timeout: 20000 }, () => {
  it('用料米数敲 "."：框里落到 "0"（`?? 0` 站点），提交被「数量须大于 0」拦下', async () => {
    await setupCurtain()
    const qty = inputOf('用料米数')
    fireEvent.change(qty, { target: { value: '.' } })
    // 旧实现：`Number('.') = NaN` ⇒ 框里显示空白（`NaN` 不是有限数）；新实现：null ⇒ `?? 0` ⇒ 0
    expect(qty).toHaveValue('0')

    await submitOrder()
    expect(await screen.findByText('数量须大于 0')).toBeInTheDocument()
    expect(mockCreateOrder).not.toHaveBeenCalled()
  })
})

describe('#5210 接受差异 ③：> 3 位小数失焦归一到 3 位', { timeout: 20000 }, () => {
  it('窗宽敲 "2.1234" ⇒ 失焦后上屏 "2.123"，试算请求也带 2.123（旧实现原样保留 2.1234）', async () => {
    await setupCurtain()
    const width = inputOf('窗宽 (米)')
    fireEvent.change(width, { target: { value: '2.1234' } })
    expect(width).toHaveValue('2.1234')
    fireEvent.blur(width)
    expect(width).toHaveValue('2.123')
    await waitFor(() => expect(craftCalcCalls().at(-1)).toMatchObject({ width: 2.123 }))
  })

  it('接高那格：敲 "0.15"（超上限）⇒ 既**不夹紧**也不截断，由就地报错 + `joinGapOf` 拒发', async () => {
    await setupCurtain()
    const toggle = screen.getAllByTestId('craft-plan-edit')[0]
    if (toggle.getAttribute('aria-expanded') === 'false') fireEvent.click(toggle)
    const join = (await screen.findByTestId('craft-plan-join-height-input')) as HTMLInputElement
    fireEvent.change(join, { target: { value: '0.15' } })
    fireEvent.blur(join)
    // 传了 max={0.1} 的实现：失焦会静默截成 0.1 ⇒ 本断言红（页面明确要求不得截断）
    expect(join).toHaveValue('0.15')
    expect(await screen.findByTestId('craft-plan-join-error')).toHaveTextContent('0.15')

    const before = craftCalcCalls().length
    fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '5' } })
    await waitFor(() => expect(craftCalcCalls().length).toBeGreaterThan(before))
    expect(craftCalcCalls().at(-1)).not.toHaveProperty('join_height_m')
  })
})

describe('#5210 差异面之外的**同口径**（负控：收敛不得顺手改这些 —— 两版都绿）', { timeout: 20000 }, () => {
  it('清空 + 失焦：米数落 0（框里回落显示 `0`）、宽高落 null（框里空）—— 与旧实现逐字同口径', async () => {
    await setupCurtain()
    const qty = inputOf('用料米数')
    fireEvent.change(qty, { target: { value: '' } })
    fireEvent.blur(qty)
    // 旧实现：`onBlur` 只 `setDraft(null)` ⇒ 渲染回落 `String(value)`；调用方把 `null` 映射成 `0`
    // ⇒ 上屏 `0`。本组件失焦同样回落「调用方当前持有的值」⇒ 也是 `0`（**不是**空串）。
    expect(qty).toHaveValue('0')

    const width = inputOf('窗宽 (米)')
    fireEvent.change(width, { target: { value: '' } })
    fireEvent.blur(width)
    expect(width).toHaveValue('')
    // 清空是合法输入态 ⇒ 由提交校验兜底（与旧实现同一出口）
    await submitOrder()
    expect(await screen.findByText('数量须大于 0')).toBeInTheDocument()
    expect(screen.getByText(/未填宽（米）/)).toBeInTheDocument()
    expect(mockCreateOrder).not.toHaveBeenCalled()
  })

  it('只聚焦 + 离开：米数**不得**被标成「人工指定」（失焦不回调 ⇒ 不唤醒调用方副作用）', async () => {
    await setupCurtain()
    const qty = inputOf('用料米数')
    fireEvent.focus(qty)
    fireEvent.blur(qty)
    expect(qty).toHaveValue('13.3')
    expect(screen.queryByRole('button', { name: '恢复按公式计算' })).toBeNull()
    // 反证：真的手改一下 ⇒ 「人工指定」入口就出现（证明上一条不是因为该入口根本不存在）
    fireEvent.change(qty, { target: { value: '12' } })
    expect(await screen.findByRole('button', { name: '恢复按公式计算' })).toBeInTheDocument()
  })
})