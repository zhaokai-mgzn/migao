// case_ids: OR-036, OR-035, OR-040
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
  // ⚠️ **`auto` 的判据是四个键有没有发**（引擎 `derive_plan(manual=…)`：任一项人工值 ⇒ `auto=false`），
  // **不是**「加工类型发没发」—— `S1` 帧实测（#5262 §13.1）：只发 `join_height_m` ⇒ 引擎 `auto=false`
  // 而 `cutting_mode` 仍是引擎推导的「定高买宽」。这条口径正是本文件判据 2 的判别力来源
  // （替身若写成 `params?.cutting_mode === undefined`，则「只改接高」那一帧会被喂成 `auto=true` ⇒ 假绿）。
  auto:
    params?.cutting_mode === undefined &&
    params?.splice_times === undefined &&
    params?.join_height_m === undefined &&
    params?.join_width_m === undefined,
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
    // **甲**（issue #5287 ①b）：来源标到**每一项** —— 加工类型这一档的归属挂在它**自己**身上
    expect(screen.getByTestId('craft-plan-mode-source')).toHaveTextContent('系统推导')
    // 块级 `craft-plan-source` **退为汇总**（判据 2：块级不得单独承担项级归属）
    expect(screen.getByTestId('craft-plan-source')).toHaveTextContent('来源汇总')
    expect(screen.getByTestId('craft-plan-source')).toHaveTextContent('人工指定 0 项')
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
    // 人工覆盖进请求 ⇒ **加工类型这一项**的来源变「人工指定」（甲：标在项上，不在块上）
    expect(await screen.findByTestId('craft-plan-mode-source')).toHaveTextContent('人工指定')
    // 块级只报**汇总**（其余三项仍是系统推导）
    expect(screen.getByTestId('craft-plan-source')).toHaveTextContent('人工指定 1 项')
    expect(screen.getByTestId('craft-plan-source')).toHaveTextContent('系统推导 3 项')

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

  // 红证留痕（issue #5218 #9 复核，2026-09-23 实测）：删掉 `orders/new/page.tsx` 里的
  // `if (line.metersSource !== METERS_SOURCE_FORMULA) continue`（算料 effect 的过滤守卫）
  // ⇒ **本条红**（`Tests 1 failed | 23 passed`，失败即本条）；同批另一条「自动态下改宽 ⇒ 用料自动跟着变」保持绿。
  // ⇒ 本条的「（红证）」标注**属实**，不需要降级声明。
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
    // ⚠️ 判据 2′（issue #5281）：本条改前是**空判据** —— 只断言「未跟随」⇒ 把推导值 / 差整段删掉
    // **不会有任何东西变红**。现在钉住**三量齐备**（手填 20 米 / 推导 = 面板的 13.3 米 / 差 6.7 米）。
    const staleNotice = await screen.findByTestId('meters-manual-stale')
    expect(staleNotice).toHaveTextContent('未跟随')
    expect(staleNotice).toHaveTextContent('用料已人工指定（20 米')
    expect(staleNotice).toHaveTextContent('系统推导用料 13.3 米')
    expect(staleNotice).toHaveTextContent('差 6.7 米')
    // **同源判据**：告知里**逐字含**面板 `craft-plan-meters` 的文本（同一个数，不是"另算一个"）
    expect(staleNotice).toHaveTextContent(
      (screen.getByTestId('craft-plan-meters').textContent ?? '').trim()
    )
    // 商家手填的数**不得被静默改回**（真值源 §8）——人工态也不因"联动"去发试算把自己的值顶掉
    await new Promise((r) => setTimeout(r, 600))
    expect(craftCalcCalls().length).toBe(before)
    expect(qtyInput()).toHaveValue('20')

    // 一键恢复 ⇒ 按**新参数**重算
    fireEvent.click(screen.getByRole('button', { name: '恢复按公式计算' }))
    await waitFor(() => expect(qtyInput()).toHaveValue('9.8'))
    expect(screen.queryByTestId('meters-manual-stale')).toBeNull()
  })

  // ===== 判据 2′（issue #5281）：告知元素内**三量齐备**（手填 / 推导 / 差）=====
  //
  // owner 2026-09-23 裁定（口径 **A**；`acceptance/2026-09-23/order-auto-derivation/report.md` §12.1 判据 2）：
  // 「手工改 / 未跟随」告知**元素内**（同一 `data-testid`）必须同时含
  // ① 当前生效值（商家手填，带单位）② 系统的推导值（带单位）③ 两者的差（相等 ⇒ 显式写「相同」）；
  // 推导值结构性不存在 / 引擎本次未返回 ⇒ **显式写明不可比**，不得静默缺项。判定只有满足 / 未满足两态。
  //
  // 真值源纪律：推导值 = `plan.meters`（**与面板 `craft-plan-meters` 同源** —— 同一个数）。
  // ⚠️ 本组用例**刻意**让 `plan.meters`(5.8) ≠ `data.fabric_meters`(13.3)：若两个数一样，
  // 「拿 `fabric_meters` 当推导值」这个变异**不会变红**（差值也假不出来）⇒ 红证没有判别力。
  // 场景逐字复刻 §12.1 的 `S4b` 帧（手填 7.7 米 / 系统推导 5.8 米，同屏但在**另一块**）。
  it('判据 2′（红证）：告知元素内**同时**含手填值 / 推导值 / 差，推导值与面板 `craft-plan-meters` 同值', async () => {
    mockCraftCalcPreview.mockImplementation((params: Record<string, unknown>) =>
      Promise.resolve({
        data: {
          data: {
            ...calcResponse(params).data.data,
            fabric_meters: 13.3,
            plan: { ...planFor(params), meters: 5.8 },
          },
        },
      })
    )
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await waitFor(() => expect(qtyInput()).toHaveValue('13.3'))

    fireEvent.change(qtyInput(), { target: { value: '7.7' } }) // 人工指定：手填 7.7 米
    fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '5' } }) // 改参数 ⇒ 签名变 ⇒ 告知出现

    const notice = await screen.findByTestId('meters-manual-stale')
    // **同源判据**（最硬的一条）：告知里**逐字含**面板那一块的文本
    const panelText = (screen.getByTestId('craft-plan-meters').textContent ?? '').trim()
    expect(panelText).toBe('用料 5.8 米') // 先钉住面板自己（防"两边一起错"也判绿）
    expect(notice).toHaveTextContent(panelText)
    // 三量：① 手填值 ② 推导值 ③ 差
    expect(notice).toHaveTextContent('用料已人工指定（7.7 米')
    expect(notice).toHaveTextContent('系统推导用料 5.8 米')
    expect(notice).toHaveTextContent('差 1.9 米')
    // 差**不得**漏出 IEEE-754 长尾（`5.8 - 7.7 = -1.9000000000000004`）
    expect(notice.textContent ?? '').not.toMatch(/\d\.\d{3,}/)
    // 场景自证：本帧 `plan.meters`(5.8) 与 `data.fabric_meters`(13.3) **确实**不同
    // ⇒ 「拿 `fabric_meters` 当推导值」那条变异有判别力（见 PR body 红证 ②）
    expect(screen.getByTestId('craft-plan-meters-mismatch')).toHaveTextContent('5.8')
    // 四条底线（owner 2026-09-23 裁定）一字不动
    expect(notice).toHaveTextContent('未跟随')
    expect(notice).toHaveTextContent('不会静默覆盖你手填的数')
    expect(notice).toHaveTextContent('恢复按公式计算')
  })

  it('判据 2′：手填值 === 推导值 ⇒ 告知里**显式写「相同」**（不得退化成「差 0 米」）', async () => {
    mockCraftCalcPreview.mockImplementation((params: Record<string, unknown>) =>
      Promise.resolve({
        data: {
          data: {
            ...calcResponse(params).data.data,
            fabric_meters: 13.3,
            plan: { ...planFor(params), meters: 7.7 },
          },
        },
      })
    )
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await waitFor(() => expect(qtyInput()).toHaveValue('13.3'))

    fireEvent.change(qtyInput(), { target: { value: '7.7' } }) // = 推导值（`plan.meters`）
    fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '5' } })

    const notice = await screen.findByTestId('meters-manual-stale')
    expect(notice).toHaveTextContent('用料已人工指定（7.7 米')
    expect(notice).toHaveTextContent('系统推导用料 7.7 米')
    expect(notice).toHaveTextContent('相同')
    expect(notice).not.toHaveTextContent('差 0')
  })

  it('判据 2′：`plan` 未返回 ⇒ 告知里**显式写不可比**（不得静默缺项）', async () => {
    mockCraftCalcPreview.mockImplementation((params: Record<string, unknown>) => {
      const data = { ...calcResponse(params).data.data } as Record<string, unknown>
      delete data.plan // 后端未接线 / 降级态：响应里没有 `data.plan`
      return Promise.resolve({ data: { data } })
    })
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await waitFor(() => expect(qtyInput()).toHaveValue('13.3'))
    // 降级提示（既有判据 7）与告知**同帧**并存 ⇒ 告知里的「不可比」是**说出来的**，不是省掉的
    expect(screen.getByTestId('craft-plan-unavailable')).toHaveTextContent('推导服务未就绪')

    fireEvent.change(qtyInput(), { target: { value: '7.7' } })
    fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '5' } })

    const notice = await screen.findByTestId('meters-manual-stale')
    expect(notice).toHaveTextContent('用料已人工指定（7.7 米')
    expect(notice).toHaveTextContent('本次未返回推导值，无法比较')
    // **不得臆造**一个推导值 / 差（缺项必须是"说出来"的）
    expect(notice).not.toHaveTextContent('系统推导用料')
    expect(notice).not.toHaveTextContent('差 ')
    // 四条底线仍在（不可比 ≠ 砍掉告知的其余部分）
    expect(notice).toHaveTextContent('未跟随')
    expect(notice).toHaveTextContent('不会静默覆盖你手填的数')
    expect(notice).toHaveTextContent('恢复按公式计算')
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

// ══════════════════════════════════════════════════════════════════════════
// issue #5211（母单 #5200 集成复核发现的 P1 缺口）：推导出的「拼N次」**必须落到订单**。
//
// 只显示不落地的三条后果（都是**静默少东西**）：① 加工单没有拼接工序 ⇒ 工人不报工、计件不含它；
// ② 加工费组合键少 `拼2次` ⇒ 商家为「韩折+超宽+拼2次」配的价**永远匹配不到**；
// ③ 面板说拼2次、订单里却没有 —— 同一件事两处不一致。
//
// 口径与既有自动识别特征（超高/超宽/倒幅）**同族**：进组合键 ⇒ 判定即钱 ⇒ 必须可采纳 / 不采纳。
// ══════════════════════════════════════════════════════════════════════════
describe('#5211 推导出的拼N次并入生效特殊选项（工序 / 计件 / 组合键）', { timeout: 20000 }, () => {
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
    // 服务端替身：**按请求回显拼次**（R7 人工覆盖 ⇒ 逐字采用；R5 ⇒ 1/2/3 才有选项名，≥4 ⇒ null）。
    // 刻意让「人工加拼1次」时 `splice_option` 跟着变 —— 否则「面板拼1次、组合键拼2次」这类
    // 不同源缺陷在测试里看不出来（真实服务端就是这么回显的）。
    mockCraftCalcPreview.mockImplementation((params: Record<string, unknown>) => {
      const times = params.splice_times === undefined ? 2 : Number(params.splice_times)
      const option = times >= 1 && times <= 3 ? `拼${times}次` : null
      return Promise.resolve(
        calcResponse(params, {
          cutting_mode: '定宽买高',
          panels: times + 1,
          splice_times: times,
          splice_option: option,
          meters: 17.4,
          fabric_meters: 17.4,
        })
      )
    })
  })

  /** 等计价就绪 → 提交 → 取该行落库的 `specialOptions`（工序/计件/组合键的**唯一**输入） */
  const submitAndGetSpecialOptions = async () => {
    await waitFor(() => expect(screen.queryByText(/加工费计价中/)).toBeNull())
    await submitOrder()
    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
    const info = mockCreateOrder.mock.calls[0][0].items[0].processingInfo
    return (info.specialOptions ?? []) as string[]
  }

  /**
   * 同一次提交的 **`processingItems[].name`**（顾客侧加工费组合键的真值源，
   * `ProcessingFeeQueryService.featureNames()` 只读这个数组）——
   * issue #5230 判据 2/3/4/5/8 的观测点。
   */
  const submitAndGetProcessingItemNames = async () => {
    await waitFor(() => expect(screen.queryByText(/加工费计价中/)).toBeNull())
    await submitOrder()
    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
    const info = mockCreateOrder.mock.calls[0][0].items[0].processingInfo
    return ((info.processingItems ?? []) as Array<{ name: string }>).map((i) => i.name)
  }

  it('判据 1（红证）：推导出 `拼2次` ⇒ 提交 payload 的 `specialOptions` **含 `拼2次`**', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })

    // 面板先看到推导（改前：**只有这一行字**，订单里什么都没有 ⇒ 下面必红）
    expect(await screen.findByTestId('craft-plan-splice')).toHaveTextContent('拼2次')

    const options = await submitAndGetSpecialOptions()
    expect(options).toContain('拼2次')
  })

  it('判据 2（红证）：点「不采纳」⇒ payload **不含** `拼2次`，且界面留痕（谁剔除的看得见）', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await screen.findByTestId('craft-plan-splice')

    fireEvent.click(await screen.findByTestId('craft-plan-derived-reject-拼2次'))
    expect(await screen.findByTestId('craft-plan-derived-option-拼2次')).toHaveTextContent('拼2次')

    const options = await submitAndGetSpecialOptions()
    expect(options).not.toContain('拼2次')
  })

  it('判据 3（红证）：人工加拼 1 次 ⇒ payload 含 `拼1次` **且不含** `拼2次`（面板与落库同源）', async () => {
    // 🔴 这条刻意用**只按 plan 回显**的替身（`splice_option` 恒 = 拼2次）：
    // 真实世界里响应有防抖延迟、也可能还没跟着请求变 ⇒ 「人工加」必须**本地优先**，
    // 否则就会「商家点了拼1次、订单里还是拼2次」（= 两处各写一份的形态）。
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
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await screen.findByTestId('craft-plan-splice')

    openCraftParams()
    pickChip('拼接（人工加）', '拼1次')
    // 面板显示也要跟着变成 `拼1次`（不得停在推导的 `拼2次`）
    await waitFor(() => expect(screen.getByTestId('craft-plan-splice')).toHaveTextContent('拼1次'))
    // 请求面同步（人工加随试算请求下发：R7 人工覆盖）
    await waitFor(() => expect(craftCalcCalls().at(-1)).toMatchObject({ splice_times: 1 }))

    const options = await submitAndGetSpecialOptions()
    // 红证：实现若「只看 plan 回显」（人工加不优先）⇒ 这里是 `拼2次` ⇒ 必红
    expect(options).toContain('拼1次')
    expect(options).not.toContain('拼2次')
  })

  it('判据 4：`splice_times = 4`（无对应选项名）⇒ payload 不含任何 `拼N次`，但有「需人工处理」告知', async () => {
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

    // 不发明「拼4次」：只告知需人工处理
    expect(await screen.findByTestId('craft-plan-splice-manual')).toHaveTextContent('人工处理')

    const options = await submitAndGetSpecialOptions()
    expect(options.filter((o) => /^拼\d次$/.test(o))).toEqual([])
  })

  it('判据 5（单点口径）：面板显示的拼接名 === payload 里的 `拼N次`（采纳态与不采纳态都逐值一致）', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })

    const splicePanel = await screen.findByTestId('craft-plan-splice')
    const panelBefore = splicePanel.textContent ?? ''
    let options = await submitAndGetSpecialOptions()
    // 面板说 `拼2次` ⇒ 落库就得是 `拼2次`（**逐值**，不是"包含关系"）
    expect(options.filter((o) => /^拼\d次$/.test(o))).toEqual(['拼2次'])
    expect(panelBefore).toContain('拼2次')

    // 不采纳后重来一次：面板改成「已忽略」，payload 也随之消失（同一函数，两处不可能不一致）
    mockCreateOrder.mockClear()
    fireEvent.click(await screen.findByTestId('craft-plan-derived-reject-拼2次'))
    const rejectedNote = await screen.findByTestId('craft-plan-derived-option-拼2次')
    expect(rejectedNote).toHaveTextContent('拼2次')
    expect(rejectedNote).toHaveTextContent('已忽略')
    options = await submitAndGetSpecialOptions()
    expect(options.filter((o) => /^拼\d次$/.test(o))).toEqual([])
  })

  it('R4 冲突（本单裁定）：款式=拼色 且推导出拼接 ⇒ **仍并入**（几何事实必须进工序/计件/组合键），但**不替商家改款式**', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await screen.findByTestId('craft-plan-splice')

    openCraftParams()
    pickChip('款式', '拼色')
    // 只告知（不静默改款式）
    expect(await screen.findByTestId('craft-plan-style-conflict')).toHaveTextContent('单色')
    expect(checkedChips('款式')).toEqual(['拼色'])

    const options = await submitAndGetSpecialOptions()
    // 拼接是**几何事实**（布真的拼了）⇒ 工序/计件一处都不能少；冲突由告知 + 一键不采纳兜底
    expect(options).toContain('拼2次')
    expect(mockCreateOrder.mock.calls[0][0].items[0].processingInfo.style).toBe('拼色')
  })

  // ── 追加范围（issue #5211 第二次扩范围）：**接高**与拼N次**同构**，同样只显示没落单 ──────
  // `接高` 在册：`routing.SPECIAL_OPTION_ROUTINGS["接高"] = {operation: '接高-布'}`、计件 1.0 元/幅
  // ⇒ 推导出的接高到不了工序与计件（工人不报工、少发工钱），与拼N次完全相同。

  /** 定高买宽 + 缺口 0.08 米（≤0.1 上限）⇒ 服务端给 `join_height_m`（也是人工加的那一档） */
  const withJoinHeight = () =>
    mockCraftCalcPreview.mockImplementation((params: Record<string, unknown>) =>
      Promise.resolve(
        calcResponse(params, {
          cutting_mode: '定高买宽',
          panels: null,
          splice_times: 0,
          splice_option: null,
          join_height_m: params.join_height_m === undefined ? 0.08 : Number(params.join_height_m),
          meters: 13.3,
          fabric_meters: 13.3,
        })
      )
    )

  it('判据 6（红证）：`plan.join_height_m` 非空 ⇒ payload 的 `specialOptions` **含 `接高`**', async () => {
    withJoinHeight()
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })

    expect(await screen.findByTestId('craft-plan-join-height')).toHaveTextContent('0.08')
    // 面板看得到「已并入」（改前：只有一行「接高 0.08 米」的展示，订单里什么都没有 ⇒ 下面必红）
    expect(await screen.findByTestId('craft-plan-derived-option-接高')).toHaveTextContent('已并入')

    const options = await submitAndGetSpecialOptions()
    expect(options).toContain('接高')
    // 串味检查：没拼接就不能凭空多一个拼次项
    expect(options.filter((o) => /^拼\d次$/.test(o))).toEqual([])
  })

  it('判据 7（红证）：不采纳「接高」⇒ payload **不含 `接高`**，界面留痕 + 可采纳回来', async () => {
    withJoinHeight()
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await screen.findByTestId('craft-plan-join-height')

    fireEvent.click(await screen.findByTestId('craft-plan-derived-reject-接高'))
    const note = await screen.findByTestId('craft-plan-derived-option-接高')
    expect(note).toHaveTextContent('已忽略')
    expect(note).toHaveTextContent('接高')

    const options = await submitAndGetSpecialOptions()
    expect(options).not.toContain('接高')

    // 恢复采纳 ⇒ 又回进 payload（不是单向棘轮）
    fireEvent.click(screen.getByTestId('craft-plan-derived-adopt-接高'))
    await waitFor(() =>
      expect(screen.getByTestId('craft-plan-derived-option-接高')).toHaveTextContent('已并入')
    )
  })

  it('判据 8（红证）：`join_height_m` / `join_width_m` 都为 `null` ⇒ **不得**并入 `接高` / `接宽`（防「为过判据 6 而恒加」）', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    // 本 describe 的默认 fixture = 拼2次、两个 join 都为 null
    await screen.findByTestId('craft-plan-splice')
    expect(screen.queryByTestId('craft-plan-derived-option-接高')).toBeNull()
    expect(screen.queryByTestId('craft-plan-derived-option-接宽')).toBeNull()

    const options = await submitAndGetSpecialOptions()
    expect(options).not.toContain('接高')
    expect(options).not.toContain('接宽')
    // 拼N次**不**派生拼接（issue #5230 口径 4：裁定不含「拼N次也算」那一档）——
    // 把 `derivedJoinSpliceItemOf` 改成「只看 splice_times ≥ 1」⇒ 本行必红
    expect(await submitAndGetProcessingItemNames()).not.toContain('拼接')
  })

  // ── issue #5230（用户裁定 2026-09-23 v2，逐字：「**移除接宽逻辑，接高在特殊选项中选择，
  //    但是仍然得自动推导**」+「会派生出拼接加工项」）──────────────────────────────────────
  // 三条通路各司其职、不得互串：
  //   ① `接高` → `processingInfo.specialOptions`（**插工序 + 计件**，issue #5211 现状即正确）；
  //   ② `接宽` → **只进算料与面板提示**（无选项 / 工序 / 计件出口）；
  //   ③ `接高` 或 `接宽` **发生** ⇒ 派生 `拼接` → `processingInfo.processingItems[]`
  //      （**顾客侧加工费组合键**）；`拼N次` **不**派生（裁定边界，见判据 8）。
  // ⚠️ 判据 1 是**口径反转**：本文件原「判据 8」曾断言「接宽有值也不并入」（issue #5214 ——
  //    当时全仓无接宽的选项 / 工序出口）。#5230 v1 曾为该缺口补出口，**v2 又按用户指示撤回**
  //    （「移除接宽逻辑」）⇒ 判据 1 的**形态**回到「不并入」，但**判据不放宽**：
  //    新增了拼接派生（判据 3/4/5/6/8）这一整组断言。

  /** 倒幅 + 接宽缺口 0.05 米（≤0.1 上限）⇒ 服务端给 `join_width_m`（也是人工加的那一档） */
  const withJoinWidth = () =>
    mockCraftCalcPreview.mockImplementation((params: Record<string, unknown>) =>
      Promise.resolve(
        calcResponse(params, {
          cutting_mode: '定宽买高',
          panels: 3,
          splice_times: 0,
          splice_option: null,
          join_width_m: params.join_width_m === undefined ? 0.05 : Number(params.join_width_m),
          meters: 17.4,
          fabric_meters: 17.4,
        })
      )
    )

  it('判据 1（红证）：`plan.join_width_m` 非空 ⇒ **不并入** `specialOptions`（接宽无选项出口，v2 裁定）', async () => {
    withJoinWidth()
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })

    // 面板照旧只有**只读**那一行（算料结果），没有「已并入特殊选项」的派生行
    expect(await screen.findByTestId('craft-plan-join-width')).toHaveTextContent('0.05')
    expect(screen.queryByTestId('craft-plan-derived-option-接宽')).toBeNull()

    const options = await submitAndGetSpecialOptions()
    // 接宽**不进** `specialOptions`：选项名是 join key，清单里没有它 ⇒ 后端会按「缺工序」422
    // （不是静默少一道）；红证：给它造一个名字并入 ⇒ 本行必红
    expect(options).not.toContain('接宽')
    expect(options.filter((o) => /^拼\d次$/.test(o))).toEqual([])
    expect(options).not.toContain('接高')
  })

  it('判据 2（红证）：`接宽` / `接高` **都不得**进 `processingItems[]`（工序通路 ≠ 顾客侧组合键通路）', async () => {
    withJoinWidth()
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await screen.findByTestId('craft-plan-join-width')

    const items = await submitAndGetProcessingItemNames()
    expect(items).not.toContain('接宽')
    expect(items).not.toContain('接高')
    // 但派生项**要**在（否则本用例会给「什么都不加」放行 —— 空断言）
    expect(items).toContain('拼接')
  })

  it('判据 4（红证）：`plan.join_width_m` 非空 ⇒ `processingItems[]` **含 `拼接`**（可采纳 / 不采纳）', async () => {
    withJoinWidth()
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await screen.findByTestId('craft-plan-join-width')
    openCraftParams()

    const row = await screen.findByTestId('auto-feature-拼接')
    expect(row).toHaveTextContent('拼接')
    expect(row).toHaveTextContent('接宽')
    expect(await submitAndGetProcessingItemNames()).toContain('拼接')
  })

  it('判据 3（红证）：`plan.join_height_m` 非空 ⇒ `processingItems[]` **含 `拼接`**', async () => {
    withJoinHeight()
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    // 「系统识别」块挂在「改工艺参数」展开态里（默认收起；`craft-plan-*` 只读面板证明推导已就绪）
    await screen.findByTestId('craft-plan-join-height')
    openCraftParams()

    const row = await screen.findByTestId('auto-feature-拼接')
    expect(row).toHaveTextContent('接高')
    expect(await submitAndGetProcessingItemNames()).toContain('拼接')
  })

  it('判据 6（红证·接高被不采纳）：`join_height_m` 非空 **且** 商家不采纳 `接高` ⇒ **不派生** `拼接`', async () => {
    withJoinHeight()
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await screen.findByTestId('craft-plan-derived-option-接高')

    // 先证明「不采纳之前**确实**派生了拼接」（否则下面那条「不含」是空断言）
    openCraftParams()
    expect(await screen.findByTestId('auto-feature-拼接')).toHaveTextContent('接高')

    fireEvent.click(await screen.findByTestId('craft-plan-derived-reject-接高'))
    expect(await screen.findByTestId('craft-plan-derived-option-接高')).toHaveTextContent('已忽略')

    const options = await submitAndGetSpecialOptions()
    expect(options).not.toContain('接高')
    // 接缝不存在 ⇒ 拼接也不该收钱（红证：把「不采纳」判据从拼接派生里去掉 ⇒ 本行必红）
    expect(await submitAndGetProcessingItemNames()).not.toContain('拼接')
    // 面板上那条派生行也要消失（不是只在 payload 里消失）
    expect(screen.queryByTestId('auto-feature-拼接')).toBeNull()
  })

  it('判据 6（红证·拼接侧）：不采纳「拼接」⇒ `processingItems[]` 不含 `拼接`，且可采纳回来（不留暗箱）', async () => {
    withJoinHeight()
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await screen.findByTestId('craft-plan-join-height')
    openCraftParams()
    await screen.findByTestId('auto-feature-拼接')

    fireEvent.click(await screen.findByTestId('auto-feature-reject-拼接'))
    expect(await screen.findByTestId('auto-feature-rejected-拼接')).toHaveTextContent('已忽略')

    const items = await submitAndGetProcessingItemNames()
    expect(items).not.toContain('拼接')
    // 接高那条通路**不受牵连**（两条账分开：不采纳拼接 ≠ 不插接高工序）
    expect(await submitAndGetSpecialOptions()).toContain('接高')

    fireEvent.click(screen.getByTestId('auto-feature-adopt-拼接'))
    await waitFor(() => expect(screen.queryByTestId('auto-feature-rejected-拼接')).toBeNull())
  })

  it('判据 5（红证）：两个 join 都为 `null` ⇒ `processingItems[]` **不含 `拼接`**（不得恒加）', async () => {
    // 本 describe 默认 fixture = 拼2次、无接高、无接宽
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await screen.findByTestId('craft-plan-splice')

    // 面板上**没有**拼接那一行派生行（只有真正发生时才有）—— 先证明「展开后能看见这块」
    openCraftParams()
    expect(await screen.findByTestId('auto-detected-features')).toBeInTheDocument()
    expect(screen.queryByTestId('auto-feature-拼接')).toBeNull()
    const items = await submitAndGetProcessingItemNames()
    expect(items).not.toContain('拼接')
  })

  // ── 判据 9 / 10 / 11（用户 2026-09-23 逐字：「**超高不用派生出拼接加工项**」）──────────────
  // 为什么必须钉死（不是抠字眼）：超高 / 超宽 / 倒幅 都**会进顾客侧加工费组合键**
  // （组合键 = `processingItems[].name` 的集合）—— 若它们也派生拼接，**每一个**判了超高的订单
  // 组合键都会多一项 ⇒ 匹配不到商家配的组合价（或落到别的档）⇒ **静默改钱**，界面还看不出原因。
  // 本仓已有同类事故先例：`正幅` 被推导进组合键 ⇒ 默认订单加工费恒 ¥0.00（issue #4592）。
  // ⇒ 拼接的**唯一触发** = `join_height_m` 非空 **或** `join_width_m` 非空（接高 / 接宽生效）。

  /** 只让服务端判出某一个自动特征（两个 join 都留 `null`） */
  const onlyAutoFeature = (name: string, reason: string) =>
    mockAutoFeatures.mockResolvedValue({
      data: { data: { auto_features: [{ name, reason }], door_width: null, notices: [] } },
    })

  it('判据 9（红证）：只判了 `超高` ⇒ `processingItems[]` **含 `超高`、不含 `拼接`**', async () => {
    onlyAutoFeature('超高', '净窗高 4.5 米 > 超高阈值 4 米')
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await screen.findByTestId('craft-plan-splice')

    const items = await submitAndGetProcessingItemNames()
    // 必须同时断言「含超高」：否则把整个自动特征都关掉也能让下面那条绿（假红证）
    expect(items).toContain('超高')
    expect(items).not.toContain('拼接')
  })

  it('判据 10（红证）：只判了 `超宽` ⇒ `processingItems[]` **含 `超宽`、不含 `拼接`**', async () => {
    onlyAutoFeature('超宽', '净窗宽 7.2 米 > 超宽阈值 6 米')
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await screen.findByTestId('craft-plan-splice')

    const items = await submitAndGetProcessingItemNames()
    expect(items).toContain('超宽')
    expect(items).not.toContain('拼接')
  })

  it('判据 11（红证）：只判了 `倒幅` ⇒ `processingItems[]` **含 `倒幅`、不含 `拼接`**', async () => {
    onlyAutoFeature('倒幅', '加工类型 = 定宽买高 ⇒ 倒幅')
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await screen.findByTestId('craft-plan-splice')

    const items = await submitAndGetProcessingItemNames()
    expect(items).toContain('倒幅')
    expect(items).not.toContain('拼接')
  })
})

// ── issue #5287：①b（甲 · 项级来源）/ ②（引擎拒绝 ⇒ 不得「已并入」）/ ③（用料标失效）──────────
describe('#5287 项级来源 + 引擎拒绝态（判据 2/3/4/5）', { timeout: 20000 }, () => {
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
          reason: '（替身：规则面由既有测试覆盖）',
        },
      },
    })
  })

  it('判据 2（红证）：**只**人工加接高 ⇒ 加工类型仍是「系统推导」，只有接高是「人工指定」', async () => {
    // 复现 #5262 §13.1 的 `S1` 帧：`req.cutting_mode` **缺席**（商家从没点过加工类型），
    // `req.join_height_m = 0.05`。改前：面板把**加工类型**标成「人工指定（不再被自动改判）」。
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await waitFor(() => expect(craftCalcCalls().length).toBeGreaterThan(0))
    openCraftParams()

    fireEvent.change(screen.getByTestId('craft-plan-join-height-input'), {
      target: { value: '0.05' },
    })
    await waitFor(() => expect(craftCalcCalls().at(-1)).toMatchObject({ join_height_m: 0.05 }))
    // 请求面自证：加工类型那个键**根本没发**（引擎收到的 `cutting_mode_sent == false`）
    expect(craftCalcCalls().at(-1)).not.toHaveProperty('cutting_mode')

    // 逐项归属（甲）：接高 = 人工指定；加工类型 / 拼次 / 接宽 = 系统推导
    expect(screen.getByTestId('craft-plan-join-height-source')).toHaveTextContent('人工指定')
    expect(screen.getByTestId('craft-plan-mode-source')).toHaveTextContent('系统推导')
    expect(screen.getByTestId('craft-plan-splice-source')).toHaveTextContent('系统推导')
    expect(screen.getByTestId('craft-plan-join-width-source')).toHaveTextContent('系统推导')
    // 红证：把项级标注去掉、只留块级（改前的形态）⇒ 上面四条必红
    expect(screen.getByTestId('craft-plan-mode-source')).not.toHaveTextContent('人工指定')
    // 块级汇总（不是项级归属的载体）
    expect(screen.getByTestId('craft-plan-source')).toHaveTextContent('人工指定 1 项')
  })

  it('判据 3（红证）：引擎拒绝该组合 ⇒ 同帧**两处**都不得再写「已并入」，改用「未生效」', async () => {
    // 复现 #5262 §13.2 的 `S2` 帧：人工接高 + 拼 2 次 ⇒ 引擎 400/422 拒绝
    // （引擎逐字：「加工类型「定高买宽」是买宽订单、零拼接 ⇒ 拼次只能是 0（收到 2）」）。
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await waitFor(() => expect(craftCalcCalls().length).toBeGreaterThan(0))
    openCraftParams()

    mockCraftCalcPreview.mockRejectedValue({
      response: {
        data: {
          error: {
            code: 'CRAFT_CALC_INVALID_INPUT',
            message:
              '算料参数不合法，本次试算已中止（不给 0 米）：加工类型「定高买宽」是买宽订单、' +
              '零拼接 ⇒ 拼次只能是 0（收到 2）',
          },
        },
      },
    })
    pickChip('拼接（人工加）', '拼2次')
    fireEvent.change(screen.getByTestId('craft-plan-join-height-input'), {
      target: { value: '0.05' },
    })
    await waitFor(() => expect(screen.getByText(/算料试算失败.*拼次只能是 0/)).toBeInTheDocument())

    // 两处（`craft-plan-splice` 与 `craft-plan-derived-options`）都**不得**再宣称「已并入」
    const spliceLine = screen.getByTestId('craft-plan-splice')
    expect(spliceLine).not.toHaveTextContent('已并入')
    expect(spliceLine).toHaveTextContent('未生效')
    const derived = screen.getByTestId('craft-plan-derived-options')
    expect(derived).not.toHaveTextContent('已并入')
    expect(derived).toHaveTextContent('未生效')
    // 同帧的错误态仍在（不是静默）
    expect(screen.getByText(/算料试算失败.*拼次只能是 0/)).toBeInTheDocument()
  })

  it('判据 4（红证）：同一组合下引擎**同意** ⇒ 「已并入」回来（判据来自引擎响应，不是前端自判）', async () => {
    // 与上一条**同参数**、只换引擎的答复：这是「同源」的判别性对照 ——
    // 前端若自己写了一份「拼次是否合法」的判断，这一条就会红（它会在引擎同意时也说未生效）。
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await waitFor(() => expect(craftCalcCalls().length).toBeGreaterThan(0))
    openCraftParams()

    mockCraftCalcPreview.mockImplementation((params: Record<string, unknown>) =>
      Promise.resolve(
        calcResponse(params, { cutting_mode: '定宽买高', panels: 3, splice_times: 2, splice_option: '拼2次' })
      )
    )
    pickChip('拼接（人工加）', '拼2次')
    await waitFor(() =>
      expect(screen.getByTestId('craft-plan-splice')).toHaveTextContent('已并入')
    )
    expect(screen.getByTestId('craft-plan-derived-options')).toHaveTextContent('已并入')
  })

  it('判据 5（红证）：引擎拒绝 ⇒ `用料` 必须标「已失效」（不得继续显示上一次的旧值而无标记）', async () => {
    render(<NewOrderPage />)
    await pickProduct()
    await fillThreeInputs({ sku: '2\\.8米' })
    await waitFor(() => expect(screen.getByTestId('craft-plan-meters')).toHaveTextContent('13.3'))
    // 成功帧：**没有**失效标记（否则本条的判别力就没了）
    expect(screen.getByTestId('craft-plan-meters')).not.toHaveTextContent('已失效')

    mockCraftCalcPreview.mockRejectedValue({
      response: { data: { error: { message: '加工类型「定高买宽」是买宽订单、零拼接' } } },
    })
    fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '5' } })
    await waitFor(() =>
      expect(screen.getByTestId('craft-plan-meters')).toHaveTextContent('已失效')
    )
    // 旧值仍在（不装成 0 米），但**标明已失效**——改前形态：只显示 `用料 13.3 米`，无任何标记
    expect(screen.getByTestId('craft-plan-meters')).toHaveTextContent('13.3')
  })
})
