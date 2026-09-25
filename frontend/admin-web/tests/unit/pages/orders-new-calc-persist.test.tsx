// case_ids: OR-032, OR-033, OR-036
// @vitest-environment jsdom
/**
 * 下单页**算料输出落库**（issue #4273，P1）。
 *
 * <h2>病根（本单要治的）</h2>
 * 算料输出**算完就丢**：订单侧只落了 `fabric_meters` + `formulaText`（本页 `buildLineProcessingInfo`
 * 旧形态），其余算料键（`pleat_count` / `per_panel_pleats` / `panels` / `fullness` …）**全仓零处落库**
 * ⇒ 加工单实例化时 `calc_info` 取不到键 ⇒ 「折 / 幅 / 套」类工序的**应做数量恒兜底 1**
 * （`qty_source=fallback`，`backend/ai-agent-service/app/production/routing.py` 的 FOLD_KEYS / PANEL_KEYS）。
 *
 * <h2>链路（真值在哪一侧）</h2>
 * 本页写 `processingInfo` → Java `ProcessingOrderService.buildSnapshot`（`CALC_OUTPUT_SNAPSHOT_KEYS`
 * 逐键透传）→ `calcInfo(entry)`（`CALC_INFO_KEYS` 白名单）→ ai-agent `routing._qty_for` 取数。
 * **键名是 snake_case**，与本页试算响应的键**同名** ⇒ 页面**只透传、零映射**（不自拼、不换算 ——
 * 前端自拼 = 第二份算料逻辑，见 `lib/api.ts` 头注释）。
 *
 * <h2>为什么判据落在这一层（如实登记）</h2>
 * 期望的**最强**判据是「建一张带算料的韩褶单 ⇒ 加工单实例 `韩褶-布` 的 `qty_source === 'pleat_count'`」，
 * 它要跑 Java（生成加工单）+ ai-agent（问数端点）+ 真库，本 `vitest`（jsdom）栈跑不了整链
 * ⇒ 按任务许可**降级为单元级判据**：钉住本页交给服务端的 `processingInfo` 里算料键**逐值等于试算响应**
 * （这是整链上唯一的「写侧」缺口；写侧落对了，后面两段已被既有 Java/ai-agent 判据覆盖：
 * `ProcessingOrderServiceTest` 的 calc_info 透传 + `tests/test_production/test_operation_qty.py` 的取值）。
 *
 * 三条判据：
 * ① **红证（改前必红）**：建单 payload 的 `processingInfo` 逐键带算料输出（折数 / 每片褶数 / 幅数 /
 *    褶倍），且**逐值等于**试算响应 —— 旧形态只落 `fabric_meters` + `formulaText` ⇒ 本判据红；
 * ② **缺值不写、不造值**：倍数法响应 `pleat_count=0`、`plan` 缺省 ⇒ **不落**该键（写 0 会被下游当成
 *    真值：`0` 是「不做」而不是「没算」）；
 * ③ **类级固化**（AGENTS.md 铁律 8）：ai-agent 会读的算料数量键（`routing.py` 的
 *    FOLD_KEYS / METER_KEYS / PANEL_KEYS / SET_KEYS / HOLE_KEYS）**每一个都必须在订单写侧有人落库**，
 *    否则必须显式进「无引擎产出源」台账 ⇒ 未登记即红、台账条目一旦有了落库方也红（**只许缩短**）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const mockCreateOrder = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProcessingItems = vi.fn()
const mockGetCustomers = vi.fn()
const mockCraftCalcPreview = vi.fn()
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
  autoFeaturesApi: {
    preview: () =>
      Promise.resolve({
        data: {
          data: { auto_features: [], door_width: null, fullness_used: 2.0, notice: 'missing-door-width' },
        },
      }),
  },
  feePreviewApi: { preview: (...a: unknown[]) => mockFeePreview(...a) },
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

/** 韩褶（褶数法）试算响应 —— 键名 = 后端 snake_case（`CraftCalcController` 原样搬出） */
const CALC_PLEAT = {
  fabric_meters: 13.3,
  pleat_count: 52,
  per_panel_pleats: 26,
  per_fold: 0.25,
  fullness: 2,
  fullness_actual: 1.86,
  formula_used: 'fixed_height_pleats',
  formula_text: '韩褶公式：(6.6+0.3)×2 → 52折 → 0.25×52+0.3 = 13.3米',
  source: '公式计算',
  craft_tier: 'standard',
  warning: '',
  // 推导方案：**幅数**（`panels`）只在这个子对象里出（引擎 `derive_plan` 产出，issue #5201）
  plan: { cutting_mode: '定宽买高', panels: 2, splice_times: 1, meters: 13.3, auto: true, reason: '推导' },
}

/** 倍数法（打孔）试算响应：**没有褶数**（引擎不产出 ⇒ `pleat_count=0`），也没有推导方案 */
const CALC_FULLNESS = {
  fabric_meters: 11,
  pleat_count: 0,
  per_panel_pleats: 0,
  per_fold: 0.25,
  fullness: 2,
  fullness_actual: 1.9,
  formula_used: 'fullness',
  formula_text: '褶倍数公式：(5.5÷2)×2 → 每片 2.75×2=5.5米 ×2片 = 11.0米',
  source: '公式计算',
  craft_tier: 'standard',
  warning: '',
  plan: null,
}

const calcOk = (data: Record<string, unknown>) => ({ data: { data } })

/** 服务端取价（组合已定价 ¥10/米）—— 只为了让提交闸门放行，本文件不判加工费 */
const feeMatched = () => ({
  data: {
    data: {
      items: [
        {
          processingFee: 133,
          processingFeeDetail: {
            composition: '韩式褶',
            unit_price: 10,
            meters: 13.3,
            meters_source: 'processingMeters',
            fee_source: 'matched',
            amount: 133,
            hint: null,
          },
        },
      ],
      processingFeeTotal: 133,
    },
  },
})

const expandProcessing = () => {
  const btn = screen.getAllByRole('button', { name: /^\d+ 加工项/ })[0]
  if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
}

const inputOf = (label: string, idx = 0) =>
  screen
    .getAllByText(label)
    .map((el) => el.closest('div')!.querySelector('input') as HTMLInputElement)[idx]

/** 选商品 → 填宽高（触发算料试算 → 预填「用料米数」）→ 勾一个加工项 */
async function setupLine(meters = '13.3') {
  render(<NewOrderPage />)
  fireEvent.click(await screen.findByText('点击搜索并选择商品'))
  fireEvent.click(await screen.findByText('遮光窗帘'))
  await screen.findByText('窗宽 (米)')
  fireEvent.change(inputOf('窗宽 (米)'), { target: { value: '6.6' } })
  fireEvent.change(inputOf('窗高 (米)'), { target: { value: '2.6' } })
  await waitFor(() => expect(inputOf('用料米数')).toHaveValue(meters))
  expandProcessing()
  fireEvent.click(screen.getByRole('checkbox'))
}

const submit = async () => {
  fireEvent.change(screen.getByPlaceholderText('请输入收货人姓名'), { target: { value: '张三' } })
  fireEvent.change(screen.getByPlaceholderText('请输入 11 位手机号'), { target: { value: '13800138000' } })
  fireEvent.change(screen.getByPlaceholderText('请输入详细收货地址'), { target: { value: '杭州市' } })
  await waitFor(() => expect(screen.queryByText(/加工费计价中/)).toBeNull())
  fireEvent.click(screen.getByText('提交订单'))
}

/** 提交后拿到的 `processingInfo`（建单唯一构造点 `buildLineProcessingInfo` 的产物） */
const submittedInfo = async (): Promise<Record<string, unknown>> => {
  await submit()
  await waitFor(() => expect(mockCreateOrder).toHaveBeenCalled())
  return mockCreateOrder.mock.calls[0][0].items[0].processingInfo
}

const stubApis = () => {
  vi.clearAllMocks()
  mockGetProducts.mockResolvedValue({
    data: { data: { items: [{ id: 'p1', name: '遮光窗帘', price: 100 }], total: 1 } },
  })
  mockGetProduct.mockResolvedValue({
    data: { data: { id: 'p1', name: '遮光窗帘', skus: [], price: 100 } },
  })
  mockGetProcessingItems.mockResolvedValue({
    data: { data: { items: [{ id: 'pi1', name: '韩式褶', unit: '米' }] } },
  })
  mockCraftCalcPreview.mockResolvedValue(calcOk(CALC_PLEAT))
  mockFeePreview.mockResolvedValue(feeMatched())
}

describe('下单页算料输出落库（#4273）', () => {
  beforeEach(stubApis)

  it('判据 1（红证）：建单 payload 的 processingInfo 逐键落算料输出，且与试算响应逐值相等', async () => {
    await setupLine()
    const info = await submittedInfo()

    // 期望值**取自试算响应**（不是抄一份现值）—— 响应变了而落库没跟 ⇒ 逐值比对本条红
    const expected = {
      fabric_meters: CALC_PLEAT.fabric_meters,
      pleat_count: CALC_PLEAT.pleat_count,
      per_panel_pleats: CALC_PLEAT.per_panel_pleats,
      fullness: CALC_PLEAT.fullness,
      fullness_actual: CALC_PLEAT.fullness_actual,
      // 幅数：引擎产出在 `plan.panels`，订单层键名是扁平的 `panels`（`CALC_INFO_KEYS` 同口径）
      panels: CALC_PLEAT.plan.panels,
    }
    expect(Object.fromEntries(Object.keys(expected).map((k) => [k, info[k]]))).toEqual(expected)
    expect(info.formulaText).toBe(CALC_PLEAT.formula_text)
  })

  it('判据 2：算料没产出的键**不落**（倍数法无褶数 / 无推导方案 ⇒ 不写 0、不写 null）', async () => {
    mockCraftCalcPreview.mockResolvedValue(calcOk(CALC_FULLNESS))
    await setupLine('11')
    const info = await submittedInfo()

    // 正向对照（防「整份 processingInfo 是空的 ⇒ 假绿」）：米数照落
    expect(info.fabric_meters).toBe(CALC_FULLNESS.fabric_meters)
    expect('pleat_count' in info).toBe(false)
    expect('per_panel_pleats' in info).toBe(false)
    expect('panels' in info).toBe(false)
  })

  // ══════════════════════════════════════════════════════════════════════════════════════════
  // 判据 3 = **类级固化**（AGENTS.md 铁律 8）：本单的病根不是「漏了 pleat_count 这一个键」，
  // 而是「ai-agent 会读的算料数量键，订单写侧一个人都没写」这一类。
  // 判据取自**真值源**（不抄现值）：`routing.py` 的五个键集逐字解析 ⇒ 每个键要么在本页
  // `buildLineProcessingInfo` 里有落库方，要么显式进「无引擎产出源」台账；
  // 台账条目一旦有了落库方也红（**只许缩短**），新键加进 routing.py 而不落库 ⇒ 未登记即红。
  // ══════════════════════════════════════════════════════════════════════════════════════════
  it('判据 3（类级固化）：routing.py 会读的算料数量键都必须有人落库，无产出源的键须入台账', () => {
    const routingSrc = readSrc('backend/ai-agent-service/app/production/routing.py')
    const keysOf = (name: string): string[] => {
      const m = new RegExp(`^${name} = \\(([^)]*)\\)`, 'm').exec(routingSrc)
      // 前提自证（G7）：取不到键集说明真值源改名/搬走 ⇒ 本判据失效，必须红而不是静默放行
      if (!m) throw new Error(`routing.py 里找不到 ${name} —— 判据前提失效，请同步本守卫`)
      return [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1])
    }

    const qtyKeys = [
      ...new Set([
        ...keysOf('FOLD_KEYS'),
        ...keysOf('METER_KEYS'),
        ...keysOf('PANEL_KEYS'),
        ...keysOf('SET_KEYS'),
        ...keysOf('HOLE_KEYS'),
      ]),
    ]
    expect(qtyKeys).toContain('pleat_count') // 前提自证：解析出来的键集非空且含本单主键

    const written = writtenCalcKeys()
    /** **无引擎产出源**台账（键 → 理由）：引擎不产出 ⇒ 订单侧无处可落（只许缩短） */
    const NO_ENGINE_SOURCE: Record<string, string> = {
      // `routing.py` 自带登记：「兼容位（同族工具聚合视图口径）」—— 引擎真产出是 `fabric_meters`
      meters: '兼容别名，非引擎产出（引擎真产出 = fabric_meters）',
      // 同上文件 SET_KEYS 注释：「引擎暂未产出 ⇒ 兜底 1（一个部位 = 一樘，语义成立）」
      set_count: '引擎暂未产出（routing.py SET_KEYS 已登记待补）',
      // 同上文件 HOLE_KEYS 注释：「引擎暂未产出，按 HOLE_PER_METER 估算」
      holes: '引擎暂未产出（routing.py HOLE_KEYS 已登记待补，按每米 6 孔估算）',
    }

    expect(qtyKeys.filter((k) => !written.has(k) && !(k in NO_ENGINE_SOURCE))).toEqual([])
    // 台账只许缩短：某键已有落库方却还挂在台账里 ⇒ 红（逼着删条目，防台账腐烂失真）
    expect(Object.keys(NO_ENGINE_SOURCE).filter((k) => written.has(k))).toEqual([])
  })
})

const ROOT = join(process.cwd(), '../..')
const readSrc = (rel: string) => readFileSync(join(ROOT, rel), 'utf8')

/**
 * 本页 `buildLineProcessingInfo` 里**真正落库**的 `info.<key>` 键集（唯一构造点，issue #4450）。
 * 只扫函数体并先剥行注释 —— 本文件与页面正文里的说明文字**不得**算作落库方
 * （否则「写进注释」会被判成「已落库」，本判据退化成空断言）。
 */
function writtenCalcKeys(): Set<string> {
  const src = readSrc('frontend/admin-web/src/app/(dashboard)/orders/new/page.tsx')
  const start = src.indexOf('function buildLineProcessingInfo(')
  if (start < 0) throw new Error('找不到 buildLineProcessingInfo —— 判据前提失效，请同步本守卫')
  const end = src.indexOf('\n}', start)
  if (end < 0) throw new Error('buildLineProcessingInfo 函数体没找到收尾 —— 判据前提失效')
  const body = src.slice(start, end).replace(/\/\/[^\n]*/g, '')
  return new Set([...body.matchAll(/\binfo\.([A-Za-z_]\w*)\s*=/g)].map((m) => m[1]))
}