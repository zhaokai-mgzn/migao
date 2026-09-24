// case_ids: OR-036, UI-055
// @vitest-environment jsdom
/**
 * 下单页数字输入框**两份实现的收敛等价性**（issue #5210）。
 *
 * ## 这一组判据守的是什么
 *
 * 仓里曾有两份「能正确录小数」的数字框：#5202 的页面私有 `page.tsx::NumberField`（8 个调用点）
 * 与 #5198 的共享 `components/ui/NumberInput.tsx`。issue #5210 的收口方式 = **先补等价性测试再替换**
 * ⇒ 本文件是**替换前就写在旧实现上、且必须绿**的那一套（替换后同一套必须仍绿）。
 *
 * ## 逐键序列（#5210 判据 2）
 *
 * 输入序列 `"0"` → `"."` → `"5"` 在两种实现下都必须落到同一个值 `0.5`，且**中间态逐字留在框里**
 * （`"0"` / `"0."` / `"0.5"` —— 旧实现靠 `draft`，新实现靠 `NumberInput` 的字符串草稿）。
 * 每个站点都钉住「DOM 逐键值」+「落到的值」（提交 payload / 试算请求 / 预览请求三选一，取该站点真值出口）。
 *
 * ## 精度（#5210 硬约束 3）
 *
 * ① **只聚焦 + 离开不改值**：`NumberInput` 的失焦归一化会把「只是点进来又点出去」的框按 `decimals`
 *    改小（例：`6.112` ⇒ `6.11`）—— 本文件用 `13.375`（用料米数，算料写回值）与 `2.755`（窗宽，手填值）
 *    钉住「进出该框后仍是原值」；② 同一组判据同时钉住「失焦**不得**触发调用方的副作用」：
 *    `onChangeQty` 会把米数标成「人工指定」（`metersSource=MANUAL`，改宽/高不再跟随重算）
 *    ⇒ 只聚焦 + 离开**不得**出现「恢复按公式计算」入口。
 *
 * ## 形态与样式（判据 3 / UI 回退防线）
 *
 * 8 个站点的 `type="text"` + `inputMode="decimal"` + `className` **逐字**（与旧实现一字不差 ——
 * `check-ui-regression.sh` 比对 neutral token，className 变了就是 UI 回退）。
 *
 * ## 向导两步（本文件的分组依据）
 *
 * 区块 1「尺寸与数量 · 工艺规格」= 窗宽 / 窗高 / 用料米数 / 单价 + **人工加接高**（在「改工艺参数」展开区里）；
 * 区块 2「加工项 · 特殊选项」= **改单价（override）**。两步是**互斥展开**的（`openStep` 单值）
 * ⇒ 站点按所在区块分组渲染，不硬凑一个 render。
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

/** 旧实现的 className 逐字（`inputClass` / 各站点的字面量）—— 替换后必须一字不差 */
const FULL_INPUT_CLASS =
  'w-full h-9 px-3 rounded border border-neutral-300 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15'
const COMPACT_INPUT_CLASS =
  'w-24 h-8 px-2 rounded border border-neutral-300 text-xs focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15'

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

/** 同色两个门幅（与既有 `orders-new-plan` 的桩同源：改门幅 / 选门幅这一步是确定的） */
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

/** 服务端推导方案（回显人工覆盖；`join_height_m` 按请求回显） */
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
  candidates: [],
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
      plan: planFor(params),
      ...over,
    },
  },
})

/** 服务端取价：未定价 + **组合键非空** ⇒ 「改单价」入口渲染（#4874 的两条准入都满足） */
const feeUnpriced = () => ({
  data: {
    data: {
      items: [
        {
          processingFee: 0,
          processingFeeDetail: {
            composition: '韩式褶',
            items: ['韩式褶'],
            unit_price: null,
            meters: 13.3,
            fee_source: 'unpriced',
            amount: 0,
            hint: '该组合未定价',
          },
        },
      ],
      processingFeeTotal: 0,
    },
  },
})

const inputOf = (label: string, idx = 0) =>
  screen
    .getAllByText(label)
    .map((el) => el.closest('div')!.querySelector('input') as HTMLInputElement)[idx]

const craftCalcCalls = () =>
  mockCraftCalcPreview.mock.calls.map((c) => c[0] as Record<string, unknown>)

/** 逐键录入 `"0"` → `"."` → `"5"`，返回**每一步之后**框里逐字的值（#5210 判据 2 的输入序列） */
function typeZeroDotFive(el: HTMLInputElement): string[] {
  return [`0`, `0.`, `0.5`].map((v) => {
    fireEvent.change(el, { target: { value: v } })
    return el.value
  })
}

const pickChip = (label: string, text: string) => {
  fireEvent.click(within(screen.getByRole('radiogroup', { name: label })).getByText(text))
}

/** 三项输入：颜色 + 净窗宽 + 净窗高 + 门幅（与既有测试同一路径；门幅不选 ⇒ 试算不入参） */
async function setupCurtain() {
  render(<NewOrderPage />)
  fireEvent.click(await screen.findByText('点击搜索并选择商品'))
  fireEvent.click(await screen.findByText('遮光窗帘'))
  await screen.findByText('窗宽 (米)')
  fireEvent.click(await screen.findByRole('button', { name: '米白' }))
  fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '6.6' } })
  fireEvent.change(inputOf('窗高 (米)'), { target: { value: '2.6' } })
  fireEvent.click(await screen.findByRole('button', { name: /2\.8米/ }))
  // 算料写回「用料米数」（各用例的桩可能给不同精度 ⇒ 只等它**落下来**，不等某个具体值）
  await waitFor(() => expect(inputOf('用料米数').value).toMatch(/^13\.3/))
}

/** 展开「改工艺参数 / 人工加接高接宽拼接」（默认收起；接高输入在这个展开区里） */
const openCraftParams = () => {
  const btn = screen.getAllByTestId('craft-plan-edit')[0]
  if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
}

/** 展开向导区块 2「加工项 · 特殊选项」（默认收起；**打开它会收起区块 1** ⇒ 两步分区渲染） */
const expandProcessing = () => {
  const btn = screen.getAllByRole('button', { name: /^\d+ 加工项/ })[0]
  if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
}

async function submitOrder() {
  fireEvent.change(screen.getByPlaceholderText('请输入收货人姓名'), { target: { value: '张三' } })
  fireEvent.change(screen.getByPlaceholderText('请输入 11 位手机号'), {
    target: { value: '13800138000' },
  })
  fireEvent.change(screen.getByPlaceholderText('请输入详细收货地址'), { target: { value: '杭州市' } })
  await waitFor(() => expect(screen.queryByText(/加工费计价中/)).toBeNull())
  fireEvent.click(screen.getByText('提交订单'))
}

function stubApis() {
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
        reason: '测试桩：本判据不验门幅规则',
      },
    },
  })
  mockFeePreview.mockResolvedValue(feeUnpriced())
}

// ══════════════════════════════════════════════════════════════════════════
// 判据 2：8 个站点逐格「0 → . → 5」都落到同一个值
// ══════════════════════════════════════════════════════════════════════════

describe('#5210 区块 1：窗宽 / 窗高 / 用料米数 / 单价 (¥/米)', { timeout: 20000 }, () => {
  beforeEach(stubApis)

  it('① 用料米数：逐键 "0"/"0."/"0.5" 留在框里，且**提交 payload 的 quantity = 0.5**', async () => {
    await setupCurtain()
    const qty = inputOf('用料米数')
    expect(typeZeroDotFive(qty)).toEqual(['0', '0.', '0.5'])

    await submitOrder()
    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
    expect(mockCreateOrder.mock.calls[0][0].items[0].quantity).toBe(0.5)
  })

  it('② 窗宽：逐键留在框里，且**试算请求的 width = 0.5**', async () => {
    await setupCurtain()
    const width = inputOf('窗宽 (米)')
    expect(typeZeroDotFive(width)).toEqual(['0', '0.', '0.5'])
    await waitFor(() => expect(craftCalcCalls().at(-1)).toMatchObject({ width: 0.5 }))
  })

  it('③ 窗高：逐键留在框里，且**试算请求的 height = 0.5**', async () => {
    await setupCurtain()
    const height = inputOf('窗高 (米)')
    expect(typeZeroDotFive(height)).toEqual(['0', '0.', '0.5'])
    await waitFor(() => expect(craftCalcCalls().at(-1)).toMatchObject({ height: 0.5 }))
  })

  it('④ 单价 (¥/米)：逐键留在框里，且**提交 payload 的 unitPrice = 0.5**', async () => {
    await setupCurtain()
    const price = inputOf('单价 (¥/米)')
    expect(typeZeroDotFive(price)).toEqual(['0', '0.', '0.5'])

    await submitOrder()
    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
    expect(mockCreateOrder.mock.calls[0][0].items[0].unitPrice).toBe(0.5)
  })

  it('⑤ 人工加接高（区块 1 展开区）：逐键留在框里 ⇒ 读到的值 = 0.5（超上限就地报错，不静默截断）；0.05 原样进试算', async () => {
    await setupCurtain()
    openCraftParams()
    const join = (await screen.findByTestId('craft-plan-join-height-input')) as HTMLInputElement
    expect(typeZeroDotFive(join)).toEqual(['0', '0.', '0.5'])

    // 0.5 > 上限 0.1 ⇒ 页面**就地报错**且按 0.5 判定（不是被静默截成 0.1）
    expect(await screen.findByTestId('craft-plan-join-error')).toHaveTextContent('0.5')
    const before = craftCalcCalls().length
    fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '5' } })
    await waitFor(() => expect(craftCalcCalls().length).toBeGreaterThan(before))
    expect(craftCalcCalls().at(-1)).not.toHaveProperty('join_height_m')

    // 上限内的值 ⇒ 原样发给试算
    fireEvent.change(join, { target: { value: '0.05' } })
    await waitFor(() => expect(craftCalcCalls().at(-1)).toMatchObject({ join_height_m: 0.05 }))
  })
})

describe('#5210 区块 2：改单价（元/米 override）', { timeout: 20000 }, () => {
  beforeEach(stubApis)

  it('⑥ 改单价（override）：逐键留在框里，且**预览请求带 processingFeeOverride = 0.5**', async () => {
    await setupCurtain()
    expandProcessing()
    // 勾一个 per_meter 加工项 ⇒ 该行进入取价面（#4874：未定价 + 组合键非空才有改价入口）
    fireEvent.click(screen.getByRole('checkbox'))
    const block = await screen.findByTestId('processing-fee-combinations')
    const override = within(block).getByTestId('fee-unit-price-override') as HTMLInputElement

    expect(typeZeroDotFive(override)).toEqual(['0', '0.', '0.5'])
    await waitFor(() => {
      const last = mockFeePreview.mock.calls.at(-1)![0]
      expect(last.items[0].processingInfo.processingFeeOverride).toBe(0.5)
    })
  })
})

describe('#5210 布料行 2 格：数量 / 单价 (¥/米)', { timeout: 20000 }, () => {
  beforeEach(stubApis)

  /** 售卖形态切到「布料」⇒ 该行的两个数字框（标签是「数量」，**不是**「用料米数」） */
  async function setupFabricRow() {
    await setupCurtain()
    pickChip('售卖形态', '布料')
    await screen.findByText('数量')
    await waitFor(() => expect(screen.queryByText('用料米数')).toBeNull())
  }

  it('⑦ 数量：逐键留在框里，且**提交 payload 的 quantity = 0.5**', async () => {
    await setupFabricRow()
    const qty = inputOf('数量')
    expect(typeZeroDotFive(qty)).toEqual(['0', '0.', '0.5'])

    await submitOrder()
    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
    expect(mockCreateOrder.mock.calls[0][0].items[0].quantity).toBe(0.5)
  })

  it('⑧ 单价 (¥/米)：逐键留在框里，且**提交 payload 的 unitPrice = 0.5**', async () => {
    await setupFabricRow()
    const price = inputOf('单价 (¥/米)')
    expect(typeZeroDotFive(price)).toEqual(['0', '0.', '0.5'])

    await submitOrder()
    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
    expect(mockCreateOrder.mock.calls[0][0].items[0].unitPrice).toBe(0.5)
  })
})

// ══════════════════════════════════════════════════════════════════════════
// 精度：只聚焦 + 离开不改值（#5210 硬约束 3）
// ══════════════════════════════════════════════════════════════════════════

describe('#5210 精度：进出数字框不得改值（尤其用料米数 / 尺寸）', { timeout: 20000 }, () => {
  beforeEach(stubApis)

  it('用料米数：算料写回 **3 位小数**（13.375）⇒ 只聚焦 + 离开仍是 13.375，且**不落「人工指定」**', async () => {
    // 服务端写回值取 3 位：本页对米数**没有本地精度校验**（`validate()` 只校验 > 0），
    // 旧实现原样承载；归一化若按 2 位截，就会在「点进来又点出去」时**静默改钱**（加工费 = 单价 × 米数）。
    mockCraftCalcPreview.mockImplementation((params: Record<string, unknown>) =>
      Promise.resolve(calcResponse(params, { fabric_meters: 13.375, meters: 13.375 }))
    )
    await setupCurtain()
    const qty = inputOf('用料米数')
    await waitFor(() => expect(qty).toHaveValue('13.375'))

    fireEvent.focus(qty)
    fireEvent.blur(qty)
    expect(qty).toHaveValue('13.375')
    // 只聚焦 + 离开**不得**触发 `onChangeQty` 的副作用：米数未被标成「人工指定」
    // （否则改宽/高不再跟随重算 = #5202 判据 3 的语义被静默推翻）
    expect(screen.queryByRole('button', { name: '恢复按公式计算' })).toBeNull()

    await submitOrder()
    await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
    expect(mockCreateOrder.mock.calls[0][0].items[0].quantity).toBe(13.375)
  })

  it('窗宽：手填 **3 位小数**（2.755）⇒ 失焦后仍是 2.755，试算请求也带 2.755（不退化成 2.76）', async () => {
    await setupCurtain()
    const width = inputOf('窗宽 (米)')
    fireEvent.change(width, { target: { value: '2.755' } })
    fireEvent.blur(width)
    expect(width).toHaveValue('2.755')
    await waitFor(() => expect(craftCalcCalls().at(-1)).toMatchObject({ width: 2.755 }))
  })
})

// ══════════════════════════════════════════════════════════════════════════
// 形态与样式：type / inputMode / className 逐字（判据 3 + UI 回退防线）
// ══════════════════════════════════════════════════════════════════════════

describe('#5210 形态：8 格都是 text + decimal，className 与旧实现逐字一致', { timeout: 20000 }, () => {
  beforeEach(stubApis)

  /** 一次断言把「控件形态 + 类名」钉死（两条实现都必须满足） */
  function expectNumberBox(el: HTMLInputElement, className: string) {
    expect(el.getAttribute('type')).toBe('text')
    expect(el.getAttribute('inputmode')).toBe('decimal')
    expect(el.className).toBe(className)
  }

  it('区块 1 的 5 格（窗宽 / 窗高 / 用料米数 / 单价 / 人工加接高）', async () => {
    await setupCurtain()
    openCraftParams()
    expectNumberBox(inputOf('窗宽 (米)'), FULL_INPUT_CLASS)
    expectNumberBox(inputOf('窗高 (米)'), FULL_INPUT_CLASS)
    expectNumberBox(inputOf('用料米数'), FULL_INPUT_CLASS)
    expectNumberBox(inputOf('单价 (¥/米)'), FULL_INPUT_CLASS)
    expectNumberBox(
      (await screen.findByTestId('craft-plan-join-height-input')) as HTMLInputElement,
      COMPACT_INPUT_CLASS
    )
  })

  it('区块 2 的 1 格（改单价 override）', async () => {
    await setupCurtain()
    expandProcessing()
    fireEvent.click(screen.getByRole('checkbox'))
    const block = await screen.findByTestId('processing-fee-combinations')
    expectNumberBox(
      within(block).getByTestId('fee-unit-price-override') as HTMLInputElement,
      COMPACT_INPUT_CLASS
    )
  })

  it('布料行 2 格（数量 / 单价）', async () => {
    await setupCurtain()
    pickChip('售卖形态', '布料')
    await screen.findByText('数量')
    expectNumberBox(inputOf('数量'), FULL_INPUT_CLASS)
    expectNumberBox(inputOf('单价 (¥/米)'), FULL_INPUT_CLASS)
  })

  it('`aria-label` / `placeholder` / `data-testid` 三个透传面逐字（替换后不得丢）', async () => {
    await setupCurtain()
    openCraftParams()
    const width = inputOf('窗宽 (米)')
    expect(width.getAttribute('aria-label')).toBe('窗宽 (米)')
    expect(width.getAttribute('placeholder')).toBe('如 6.6')
    const qty = inputOf('用料米数')
    expect(qty.getAttribute('aria-label')).toBe('用料米数')
    expect(qty.getAttribute('placeholder')).toBe('米')
    const join = await screen.findByTestId('craft-plan-join-height-input')
    expect(join.getAttribute('aria-label')).toBe('人工加接高（米）')
    expect(join.getAttribute('data-testid')).toBe('craft-plan-join-height-input')
  })
})