// case_ids: OR-036, OR-035
// @vitest-environment jsdom
/**
 * 新增订单页：**三项输入收敛 + 用料联动自动重算**（issue #5202 —— 母单 #5200 子单 C）。
 *
 * 判据（逐条可红，红证 = 对实现做单点变异后本文件对应条必红；PR body 有表）：
 * 1. 只填「颜色 + 净窗宽 + 净窗高」⇒ 加工类型取**服务端推导**那一档（`data.plan.cutting_mode`），
 *    商家没点过；点过之后 = 人工锁定，不再被推导覆盖（裁定 6）；
 * 2. 改门幅 / 改加工类型 ⇒ **重发试算**且请求带上 `fabric_width` / `cutting_mode`
 *    （根因 1：签名漏项 ⇒ effect 不触发 ⇒ 静默停在旧数）；
 * 3. 商家手改米数后再改宽/高 ⇒ 数量**不被静默覆盖** + 「已人工指定，未跟随」告知 + 一键恢复
 *    （根因 2：单向棘轮 ⇒ 改成「自动跟随 + 显式覆盖」两态）；
 * 4. `拼N次` 推导出来时显示 `拼N次`、款式默认单色、选拼色则**显式冲突告知**（R4）；
 *    `N ≥ 4` ⇒ 显示数字 + 需人工处理，**不显示「拼4次」**（R5）；
 * 5. 接高/接宽人工加受 **≤0.1 米**上限约束：超限**就地报错**且**不发该键**（fail-closed，不静默截断）；
 * 6. 数字框能打出 `0.`（输入 `0` → `0`，`0.` → `0.`，`0.5` ⇒ 落库 0.5）；
 * 7. `data.plan` 缺席 ⇒ **显式降级**（不崩、不猜、界面提示「推导服务未就绪」+ 工艺参数默认展开供人工兜底）；
 * 8. 加工类型**单点取值**：页面 chips / `/auto-features` / `/craft-calc` / 落库 读同一个值
 *    （优先级：商家显式 → `plan.cutting_mode` → `door-width-plan` → 不猜）。
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
  // 加工费计价预览：本文件各用例都没选加工项 ⇒ 服务端替身给「无加工项 ⇒ 0 元」。
  // **必须 resolve**：预览未就绪时页面会拦住提交（落库判据用得上）。
  feePreviewApi: {
    preview: (payload: { items?: unknown[] }) => {
      const items = (payload?.items ?? []).map(() => ({
        processingFee: 0,
        processingFeeDetail: { fee_source: 'unpriced', amount: 0 },
      }))
      return Promise.resolve({ data: { data: { items, processingFeeTotal: 0 } } })
    },
  },
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

/** 算料配置读面桩（档位值域/文案都取自它 —— 页面不写死档位真值） */
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

/** 商品：**同色两个门幅**（改门幅 ⇒ 必须重算） */
const PRODUCT = {
  id: 'p1',
  name: '遮光窗帘',
  price: 100,
  basePrice: 100,
  skus: [
    {
      id: 'sku-28',
      colorId: 'c1',
      colorName: '米白',
      doorWidth: '2.8米',
      price: 100,
      stock: 10,
      skuCode: 'A-28',
    },
    {
      id: 'sku-32',
      colorId: 'c1',
      colorName: '米白',
      doorWidth: '3.2米',
      price: 110,
      stock: 5,
      skuCode: 'A-32',
    },
  ],
}

/**
 * **服务端推导方案**（#5200 §四 响应契约）——候选表逐条含**不可行**的（裁定 3：系统逐个「再算一遍」），
 * 订正 v1.1：候选 5（倒幅+接高）几何上恒不成立 ⇒ 服务端给 `feasible=false` + 理由。
 */
const CANDIDATES = [
  {
    key: 'fixed_height',
    meters: 13.3,
    feasible: true,
    splice_times: 0,
    reason: '成品高 2.6 + 上下卷边 0.3 = 2.9 ≤ 门幅 3.2 ⇒ 单幅可做',
  },
  {
    key: 'fixed_width',
    meters: 17.4,
    feasible: true,
    splice_times: 2,
    reason: '倒幅 3 幅 ⇒ 用料 3 × 2.9',
  },
  {
    key: 'fixed_height_join_height',
    meters: null,
    feasible: false,
    splice_times: 0,
    reason: '缺口 0.25 米 > 上限 0.1 米',
  },
  {
    key: 'fixed_width_join_width',
    meters: null,
    feasible: false,
    splice_times: 1,
    reason: 'T − (P−1)×D = 0.4 米 > 上限 0.1 米',
  },
  {
    key: 'fixed_width_join_height',
    meters: null,
    feasible: false,
    splice_times: 2,
    reason: '倒幅下幅长按米买、无上限 ⇒ 无需接高',
  },
]

/**
 * 服务端替身：**按请求回显 plan**（R7 人工覆盖 ⇒ `auto=false` 且逐字采用）。
 * 这么写是为了让「人工锁定后不再被推导覆盖」这条判据读的是**同一份契约**，而不是测试自己的假设。
 */
const planFor = (params: Record<string, unknown>, over: Record<string, unknown> = {}) => ({
  cutting_mode: (params?.cutting_mode as string) ?? '定高买宽',
  door_width: (params?.fabric_width as number) ?? 2.8,
  panels: null,
  splice_times: 0,
  splice_option: null,
  join_height_m: (params?.join_height_m as number) ?? null,
  join_width_m: (params?.join_width_m as number) ?? null,
  meters: 13.3,
  auto: params?.cutting_mode === undefined,
  reason: '成品高 2.6 + 上下卷边 0.3 = 2.9 ≤ 门幅 3.2 ⇒ 定高买宽单幅可做（用料最少）',
  candidates: CANDIDATES,
  ...over,
})

const calcResponse = (params: Record<string, unknown>, over: Record<string, unknown> = {}) => ({
  data: {
    data: {
      fabric_meters: 13.3,
      pleat_count: 52,
      per_fold: 0.25,
      fullness: 2,
      formula_text: '(6.6+0.3)×2.0 → 52折 → 0.25×52+0.3 = 13.3米',
      source: '公式计算',
      craft_tier: 'standard',
      plan: planFor(params, over),
      ...over,
    },
  },
})

/** 按 label 文本定位其所在容器里的 input（`Label` 无 htmlFor 关联） */
const inputOf = (label: string, idx = 0) =>
  screen
    .getAllByText(label)
    .map((el) => el.closest('div')!.querySelector('input') as HTMLInputElement)[idx]

const qtyInput = () => inputOf('用料米数')

const checkedChips = (label: string) =>
  within(screen.getByRole('radiogroup', { name: label }))
    .getAllByRole('radio')
    .filter((r) => r.getAttribute('aria-checked') === 'true')
    .map((r) => r.textContent)

const pickChip = (label: string, text: string) => {
  fireEvent.click(within(screen.getByRole('radiogroup', { name: label })).getByText(text))
}

const pickProduct = async () => {
  fireEvent.click(await screen.findByText('点击搜索并选择商品'))
  fireEvent.click(await screen.findByText('遮光窗帘'))
  await screen.findByText('窗宽 (米)')
}

/** 三项输入：颜色 + 净窗宽 + 净窗高（**商家只填这三项**）；门幅由测试显式点选 */
const fillThreeInputs = async (opts: { sku?: string } = {}) => {
  fireEvent.click(await screen.findByRole('button', { name: '米白' }))
  fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '6.6' } })
  fireEvent.change(inputOf('窗高 (米)'), { target: { value: '2.6' } })
  if (opts.sku !== undefined) {
    fireEvent.click(await screen.findByRole('button', { name: new RegExp(opts.sku) }))
  }
}

/** 「改」入口（就地人工改的**唯一**入口；默认收起 —— 推导结果只读展示） */
const craftParamsToggle = () => screen.getAllByTestId('craft-plan-edit')[0]
const openCraftParams = () => {
  const btn = craftParamsToggle()
  if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
}

const craftCalcCalls = () => mockCraftCalcPreview.mock.calls.map((c) => c[0] as Record<string, unknown>)

const submitOrder = async () => {
  fireEvent.change(screen.getByPlaceholderText('请输入收货人姓名'), { target: { value: '张三' } })
  fireEvent.change(screen.getByPlaceholderText('请输入 11 位手机号'), {
    target: { value: '13800138000' },
  })
  fireEvent.change(screen.getByPlaceholderText('请输入详细收货地址'), {
    target: { value: '杭州市' },
  })
  await waitFor(() => expect(screen.queryByText(/加工费计价中/)).toBeNull())
  fireEvent.click(screen.getByText('提交订单'))
}

describe('#5202 三项输入收敛 + data.plan 只读展示', { timeout: 20000 }, () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetProducts.mockResolvedValue({
      data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
    })
    mockGetProduct.mockResolvedValue({ data: { data: PRODUCT } })
    mockGetProcessingItems.mockResolvedValue({ data: { data: { items: [] } } })
    mockCraftCalcPreview.mockImplementation((params: Record<string, unknown>) =>
      Promise.resolve(calcResponse(params))
    )
    mockGetCraftCalcConfig.mockResolvedValue(CALC_CONFIG_OK)
    mockAutoFeatures.mockResolvedValue({
      data: { data: { auto_features: [], door_width: null, notices: [] } },
    })
    // 门幅规则面**判不了**（本文件验的是 plan 面；规则面另有既有测试）⇒ 不自动补选门幅，
    // 由测试显式点选 ⇒ 改门幅这一步是**确定的**。
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
          suggestion: null,
          reason: '（替身：规则面由既有测试覆盖）',
        },
      },
    })
  })

  it('判据 1（红证）：只填颜色/宽/高 ⇒ 加工类型 = 服务端推导那一档，且商家没点过', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })

    // 推导结果**只读展示**（改前：页面没有这个块 ⇒ 必红）
    expect(await screen.findByTestId('craft-plan-mode')).toHaveTextContent('定高买宽')
    expect(screen.getByTestId('craft-plan-source')).toHaveTextContent('系统推导')
    // 推导依据可读（商家要能核对判定）：plan.reason + 候选逐条
    expect(screen.getByTestId('craft-plan-reason')).toHaveTextContent('成品高 2.6')
    const candidates = within(await screen.findByTestId('craft-plan-candidates'))
    expect(candidates.getByTestId('craft-plan-candidate-fixed_height')).toHaveTextContent('可行')
    // 订正 v1.1：候选 5 恒不可行 ⇒ **如实显示「已评估但不适用」**（不隐藏、也不是可选方案）
    expect(candidates.getByTestId('craft-plan-candidate-fixed_width_join_height')).toHaveTextContent(
      '不可行'
    )
    expect(candidates.getByTestId('craft-plan-candidate-fixed_width_join_height')).toHaveTextContent(
      '无需接高'
    )
    // 用量单点（契约判据 10）：展示的就是 plan.meters
    expect(screen.getByTestId('craft-plan-meters')).toHaveTextContent('13.3')

    // 工艺参数**默认收起**（三项收敛）⇒ 就地「改」入口打开后，chips 已自动选中那一档
    expect(craftParamsToggle()).toHaveAttribute('aria-expanded', 'false')
    openCraftParams()
    expect(checkedChips('加工类型')).toEqual(['定高买宽'])
    // 服务端已给推导（`auto=true`）⇒ 不是人工覆盖
    expect(craftCalcCalls().at(-1)).not.toHaveProperty('cutting_mode')
  })

  it('判据 1b（裁定 6/7 人工覆盖）：点过加工类型 ⇒ 人工锁定，之后改宽**不再被推导覆盖**', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await waitFor(() => expect(craftCalcCalls().length).toBeGreaterThan(0))

    openCraftParams()
    pickChip('加工类型', '定宽买高')
    await waitFor(() =>
      expect(craftCalcCalls().at(-1)).toMatchObject({ cutting_mode: '定宽买高' })
    )
    // 人工覆盖进请求 ⇒ 服务端 `auto=false` ⇒ 界面显示「人工指定」
    expect(await screen.findByTestId('craft-plan-source')).toHaveTextContent('人工指定')

    const before = craftCalcCalls().length
    fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '5' } })
    await waitFor(() => expect(craftCalcCalls().length).toBeGreaterThan(before))
    // 人工值**逐字**留在请求里（声明式覆盖，不被推导改判）
    expect(craftCalcCalls().at(-1)).toMatchObject({ cutting_mode: '定宽买高' })
    expect(checkedChips('加工类型')).toEqual(['定宽买高'])
  })

  it('判据 7（降级）：服务端未给 `plan` ⇒ 显式提示「推导服务未就绪」+ 工艺参数默认展开（不崩、不猜）', async () => {
    // 后端 `data.plan`（子单 A / #5201）还没上线时的形态：只增键不删键 ⇒ 老响应逐值不变
    mockCraftCalcPreview.mockResolvedValue({
      data: {
        data: {
          fabric_meters: 13.3,
          pleat_count: 52,
          per_fold: 0.25,
          fullness: 2,
          formula_text: '(6.6+0.3)×2.0 → 52折 → 0.25×52+0.3 = 13.3米',
        },
      },
    })
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })

    expect(await screen.findByTestId('craft-plan-unavailable')).toHaveTextContent('推导服务未就绪')
    // 推导没就绪 ⇒ 工艺参数**默认展开**（人工兜底是唯一出路；收起会让人无从下手）
    expect(craftParamsToggle()).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('radiogroup', { name: '加工类型' })).toBeInTheDocument()
    // 数量照旧按算料结果预填（**不猜**一个推导方案出来）
    await waitFor(() => expect(qtyInput()).toHaveValue('13.3'))
  })
})

describe('#5202 用料联动自动重算（两个根因）', { timeout: 20000 }, () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetProducts.mockResolvedValue({
      data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
    })
    mockGetProduct.mockResolvedValue({ data: { data: PRODUCT } })
    mockGetProcessingItems.mockResolvedValue({ data: { data: { items: [] } } })
    mockCraftCalcPreview.mockImplementation((params: Record<string, unknown>) =>
      Promise.resolve(calcResponse(params))
    )
    mockGetCraftCalcConfig.mockResolvedValue(CALC_CONFIG_OK)
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
          suggestion: null,
          reason: '（替身）',
        },
      },
    })
  })

  it('根因 1（红证）：改门幅 ⇒ 重发试算且请求带 `fabric_width`（签名漏项 ⇒ 静默停在旧数）', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await waitFor(() => expect(craftCalcCalls().at(-1)).toMatchObject({ fabric_width: 2.8 }))

    const before = craftCalcCalls().length
    fireEvent.click(screen.getByRole('button', { name: /3\.2米/ }))
    // 红证：`fabric_width` 不进签名 ⇒ 入参没变 ⇒ effect 不触发 ⇒ 本断言红
    await waitFor(() => expect(craftCalcCalls().length).toBeGreaterThan(before))
    expect(craftCalcCalls().at(-1)).toMatchObject({ fabric_width: 3.2 })
    expect(await screen.findByTestId('craft-plan-door-width')).toHaveTextContent('3.2')
  })

  it('根因 1（红证）：改加工类型 ⇒ 重发试算且请求带 `cutting_mode`', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await waitFor(() => expect(craftCalcCalls().length).toBeGreaterThan(0))
    const before = craftCalcCalls().length

    openCraftParams()
    pickChip('加工类型', '定宽买高')
    await waitFor(() => expect(craftCalcCalls().length).toBeGreaterThan(before))
    expect(craftCalcCalls().at(-1)).toMatchObject({ cutting_mode: '定宽买高' })
  })

  it('根因 2（红证）：自动态下改宽 ⇒ 用料自动跟着变', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await waitFor(() => expect(qtyInput()).toHaveValue('13.3'))

    mockCraftCalcPreview.mockImplementation((params: Record<string, unknown>) =>
      Promise.resolve(calcResponse(params, { fabric_meters: 9.8, meters: 9.8 }))
    )
    fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '5' } })
    await waitFor(() => expect(qtyInput()).toHaveValue('9.8'))
  })

  it('根因 2（红证）：人工指定后改宽/高 ⇒ 数量**不被静默覆盖** + 「未跟随」告知 + 一键恢复', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await waitFor(() => expect(qtyInput()).toHaveValue('13.3'))

    fireEvent.change(qtyInput(), { target: { value: '20' } })
    expect(qtyInput()).toHaveValue('20')

    mockCraftCalcPreview.mockImplementation((params: Record<string, unknown>) =>
      Promise.resolve(calcResponse(params, { fabric_meters: 9.8, meters: 9.8 }))
    )
    const before = craftCalcCalls().length
    fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '5' } })

    // **显式告知**（改前：只能靠一个不显眼的「恢复按公式计算」自己发现）
    expect(await screen.findByTestId('meters-manual-stale')).toHaveTextContent('未跟随')
    // 商家手填的数**不得被静默改回**（真值源 §8）——人工态也不因"联动"去发试算把自己的值顶掉
    await new Promise((r) => setTimeout(r, 600))
    expect(craftCalcCalls().length).toBe(before)
    expect(qtyInput()).toHaveValue('20')

    // 一键恢复 ⇒ 按**新参数**重算
    fireEvent.click(screen.getByRole('button', { name: '恢复按公式计算' }))
    await waitFor(() => expect(qtyInput()).toHaveValue('9.8'))
    expect(screen.queryByTestId('meters-manual-stale')).toBeNull()
  })
})

describe('#5202 工艺推导展示（拼接 / 接高接宽 / 款式 R4）+ 人工加', { timeout: 20000 }, () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetProducts.mockResolvedValue({
      data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
    })
    mockGetProduct.mockResolvedValue({ data: { data: PRODUCT } })
    mockGetProcessingItems.mockResolvedValue({ data: { data: { items: [] } } })
    mockGetCraftCalcConfig.mockResolvedValue(CALC_CONFIG_OK)
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
          suggestion: null,
          reason: '（替身）',
        },
      },
    })
    mockCraftCalcPreview.mockImplementation((params: Record<string, unknown>) =>
      Promise.resolve(
        calcResponse(params, {
          cutting_mode: '定宽买高',
          panels: 3,
          splice_times: 2,
          splice_option: '拼2次',
          meters: 17.4,
          fabric_meters: 17.4,
        })
      )
    )
  })

  it('判据 4（红证）：推导出拼2次 ⇒ 显示 `拼2次`、款式默认单色；选拼色 ⇒ 显式冲突告知（不静默改款式）', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })

    expect(await screen.findByTestId('craft-plan-splice')).toHaveTextContent('拼2次')
    openCraftParams()
    expect(checkedChips('款式')).toEqual(['单色'])

    pickChip('款式', '拼色')
    // R4：`style=拼色` 且拼接 ⇒ **显式冲突告知**（改前：静默并存 ⇒ 必红）
    expect(await screen.findByTestId('craft-plan-style-conflict')).toHaveTextContent('单色')
    expect(checkedChips('款式')).toEqual(['拼色'])
  })

  it('判据 4b（R5 红证）：`N ≥ 4` ⇒ 显示数字 + 需人工处理，**不显示「拼4次」**', async () => {
    mockCraftCalcPreview.mockImplementation((params: Record<string, unknown>) =>
      Promise.resolve(
        calcResponse(params, {
          cutting_mode: '定宽买高',
          panels: 5,
          splice_times: 4,
          splice_option: null,
          meters: 20,
          fabric_meters: 20,
        })
      )
    )
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })

    const splice = await screen.findByTestId('craft-plan-splice')
    expect(splice).toHaveTextContent('4')
    expect(splice).toHaveTextContent('人工处理')
    // **不得发明「拼4次」这个选项名**（R5）
    expect(screen.queryByText('拼4次')).toBeNull()
  })

  it('判据 5（红证）：接高超 0.1 米 ⇒ 就地报错且**不发该键**；0.1 米 ⇒ 才可加', async () => {
    // 契约订正 v1.1 ③：**接高只出现在「定高买宽」**（倒幅下幅长按米买、无上限）⇒ 本条用定高买宽。
    mockCraftCalcPreview.mockImplementation((params: Record<string, unknown>) =>
      Promise.resolve(
        calcResponse(params, {
          cutting_mode: '定高买宽',
          panels: null,
          splice_times: 0,
          splice_option: null,
        })
      )
    )
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await waitFor(() => expect(craftCalcCalls().length).toBeGreaterThan(0))
    openCraftParams()

    // 定高买宽 ⇒ 给的是**接高**入口（接宽只在倒幅下成立 ⇒ 不出现在这里）
    expect(screen.getByTestId('craft-plan-join-height-input')).toBeInTheDocument()
    expect(screen.queryByTestId('craft-plan-join-width-input')).toBeNull()

    fireEvent.change(screen.getByTestId('craft-plan-join-height-input'), {
      target: { value: '0.15' },
    })
    // 就地报错（fail-closed，**不静默截断成 0.1**）
    expect(await screen.findByTestId('craft-plan-join-error')).toHaveTextContent('0.1')
    const before = craftCalcCalls().length
    fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '5' } })
    await waitFor(() => expect(craftCalcCalls().length).toBeGreaterThan(before))
    // 红证：把上限判断去掉 ⇒ 0.15 会被发出去 ⇒ 本断言红
    expect(craftCalcCalls().at(-1)).not.toHaveProperty('join_height_m')

    fireEvent.change(screen.getByTestId('craft-plan-join-height-input'), { target: { value: '0.1' } })
    await waitFor(() => expect(craftCalcCalls().at(-1)).toMatchObject({ join_height_m: 0.1 }))
    expect(screen.queryByTestId('craft-plan-join-error')).toBeNull()
  })

  it('判据 5b：拼次人工加（裁定 4）⇒ 请求带 `splice_times`（0~3 档）', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await waitFor(() => expect(craftCalcCalls().length).toBeGreaterThan(0))
    openCraftParams()

    pickChip('拼接（人工加）', '拼1次')
    await waitFor(() => expect(craftCalcCalls().at(-1)).toMatchObject({ splice_times: 1 }))
  })

  it('判据 10（单点口径）：`plan.meters ≠ data.fabric_meters` ⇒ 显式告知（不静默显示两个数）', async () => {
    mockCraftCalcPreview.mockImplementation((params: Record<string, unknown>) =>
      Promise.resolve({
        data: {
          data: {
            ...calcResponse(params).data.data,
            fabric_meters: 13.3,
            plan: { ...planFor(params), meters: 12.0 },
          },
        },
      })
    )
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })

    expect(await screen.findByTestId('craft-plan-meters-mismatch')).toHaveTextContent('12')
    // 数量仍按 `fabric_meters`（落库单点），不按 plan 的另一个数
    expect(qtyInput()).toHaveValue('13.3')
  })
})

describe('#5202 加工类型单点取值 + 数字输入框', { timeout: 20000 }, () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetProducts.mockResolvedValue({
      data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
    })
    mockGetProduct.mockResolvedValue({ data: { data: PRODUCT } })
    mockGetProcessingItems.mockResolvedValue({ data: { data: { items: [] } } })
    mockCraftCalcPreview.mockImplementation((params: Record<string, unknown>) =>
      Promise.resolve(calcResponse(params, { cutting_mode: '定宽买高' }))
    )
    mockGetCraftCalcConfig.mockResolvedValue(CALC_CONFIG_OK)
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
          suggestion: null,
          reason: '（替身）',
        },
      },
    })
  })

  it('判据 8（红证）：`plan.cutting_mode` 是**唯一**生效值 —— chips / auto-features / 落库 三处同值', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })

    // ① 判定面（`/auto-features` 的「倒幅」按它推导）
    await waitFor(() =>
      expect(mockAutoFeatures.mock.calls.at(-1)![0]).toMatchObject({ cutting_mode: '定宽买高' })
    )
    // ② 页面 chips（就地「改」入口里显示的选中档）
    openCraftParams()
    expect(checkedChips('加工类型')).toEqual(['定宽买高'])
    // ③ 落库
    await waitFor(() => expect(screen.queryByText(/加工费计价中/)).toBeNull())
    await submitOrder()
    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
    expect(mockCreateOrder.mock.calls[0][0].items[0].processingInfo.cuttingMode).toBe('定宽买高')
  })

  it('判据 6（红证）：数字框打得出来 `0.` —— 输入 0 → 0、"." ⇒ 0.、0.5 ⇒ 落库 0.5', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await waitFor(() => expect(qtyInput()).toHaveValue('13.3'))

    const q = qtyInput()
    // 改前：`value={line.quantity || ''}` + `Number(raw)` ⇒ 0 渲染成空串 ⇒ 输入 "0" 当场清空
    fireEvent.change(q, { target: { value: '0' } })
    expect(q).toHaveValue('0')
    fireEvent.change(q, { target: { value: '0.' } })
    expect(q).toHaveValue('0.')
    fireEvent.change(q, { target: { value: '0.5' } })
    expect(q).toHaveValue('0.5')

    await submitOrder()
    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
    expect(mockCreateOrder.mock.calls[0][0].items[0].quantity).toBe(0.5)
  })

  it('判据 6b：净窗宽同样打得出来 `0.`（0.5 米窄窗是真实窗型）', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    const w = inputOf('窗宽 (米)')
    fireEvent.change(w, { target: { value: '0' } })
    expect(w).toHaveValue('0')
    fireEvent.change(w, { target: { value: '0.' } })
    expect(w).toHaveValue('0.')
    fireEvent.change(w, { target: { value: '0.5' } })
    expect(w).toHaveValue('0.5')
    await waitFor(() => expect(craftCalcCalls().at(-1)).toMatchObject({ width: 0.5 }))
  })
})
