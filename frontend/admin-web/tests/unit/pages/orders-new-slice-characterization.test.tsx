// case_ids: MC-243
/**
 * **下单页切片 · 行为冻结判据（characterization test）** —— issue #8725 第一档。
 *
 * ## 它治什么
 *
 * 本档把 6,913 行的 `orders/new/page.tsx` 按现取边界切成若干可独立理解的单元（纯算料层 /
 * 纯展示层 / 表单组件）。这是**搬代码**，不是改逻辑 ⇒ 唯一可接受的差异是 **0**。
 *
 * 「看起来一样」不算证据：本文件把**同一批输入**下的**渲染结果与计算输出**录成 golden，
 * 切片前后逐字节比对 —— 差一个字符就红，且红在**具名的观测点**上（不是一坨 HTML diff）。
 *
 * ## 三层观测（越往下越严）
 *
 * | 层 | 抓什么 | 怎么红 |
 * |---|---|---|
 * | ① `points` | 每个 `data-testid` 节点的可见文本（含金额 / 算料读数 / 费用明细） | 键级 diff：`fee-summary-total[0]` 变了 ⇒ 名字直接指出来 |
 * | ② `fields` | 全页 `input` / `select` / `textarea` 的 `value` / `checked`（DOM 顺序） | 键级 diff：哪个框的读数漂了一目了然 |
 * | ③ `html` | 归一化后的整页 `innerHTML` | 逐字节 `toBe` 断言 —— 这是「行为 diff = 0」的**本体** |
 *
 * 归一化只做一件事：把 `crypto.randomUUID()` 产出的行 id 按**首次出现顺序**替换成
 * `UUID_n`（同一 uuid 恒得同一占位符 ⇒ 恒等/别名关系不被抹掉）。**除此之外一个字符都不动。**
 *
 * ## 记录与复核（🔴 纪律）
 *
 * 1. **golden 录制必须来自「切片前」的代码**：`CHARACTERIZATION_UPDATE=1` 只在**未切片**的
 *    `page.tsx` 上跑过一次（本文件头下面的 `README` 段有当时的读数）；
 * 2. 切片后**不带** `CHARACTERIZATION_UPDATE` 跑 ⇒ 必须绿；
 * 3. 🔴 **失败时不许直接重录 golden 了事** —— 先判断「是切片引入了行为变化（必须修代码）」，
 *    重录等于把判据降成空断言（`migao-acceptance`：「空跑」）。
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 判**渲染与计算输出**，不判网络请求次数 / 时序；服务端面貌一律由本文件的替身给出
 *   （替身是**确定函数**，不吃时间、不吃随机）；
 * - 不判视觉（class 名进 `html` 层，但视觉口径不在这里立项 —— 那由 UI 回归与 Playwright 承担）；
 * - 未覆盖：图片识别弹窗 / 授信审批弹窗（它们是独立组件，各有自己的判据）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within, cleanup } from '@testing-library/react'
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'

// ─────────────────────────────────────────────────────────────────────────────
// 服务端面替身：**全部是确定函数**（不吃 Date / Math.random / 网络）
// ─────────────────────────────────────────────────────────────────────────────

const PRODUCT = {
  id: 'p1',
  name: '测试窗帘',
  price: 100,
  category: '窗帘',
  unit: '米',
  skus: [
    { id: 'sku-28', productId: 'p1', colorId: 'c1', colorName: '米白', doorWidth: '2.8', price: 118, stock: 50, skuCode: 'A-28' },
    { id: 'sku-32', productId: 'p1', colorId: 'c1', colorName: '米白', doorWidth: '3.2', price: 126, stock: 50, skuCode: 'A-32' },
    { id: 'sku-14', productId: 'p1', colorId: 'c2', colorName: '浅灰', doorWidth: '1.4', price: 132, stock: 50, skuCode: 'B-14' },
  ],
}

const PROCESSING_ITEMS = [
  { id: 'pi-han', name: '韩褶', unit: '米', pricingMethod: 'per_meter', craftHint: '韩褶' },
  { id: 'pi-da', name: '打孔', unit: '米', pricingMethod: 'per_meter', craftHint: '打孔' },
  { id: 'pi-dx', name: '定型', unit: '米', pricingMethod: 'per_meter', craftHint: null },
]

/**
 * 加工费组合价目（元/米）—— 键 = 组合键里的**加工项名**。
 * 数值刻意取非整数，让「取整 / 保留位数」这类**行为改动**必然改变渲染读数
 * （若全都取整数，`toFixed(2)` 改成 `toFixed(0)` 也看不出来 —— 那会是一份空判据）。
 */
const FEE_UNIT_PRICE: Record<string, number> = { 韩褶: 12.345, 打孔: 5.678, 定型: 3.21 }

const CALC_CONFIG = {
  source: 'stored',
  config: {
    per_fold_single: 0.25,
    per_fold_mixed_times: {},
    margin_single: 0.3,
    margin_multi: 0.3,
    min_fullness: 1.5,
    tiers: {
      standard: { fullness: 2.0, label: '标准档（2.0 倍）' },
      economy: { fullness: 1.8, label: '经济档（1.8 倍）' },
    },
    default_formula: 'pleat',
    meters_rounding_step: 0.1,
  },
}

const mockCreateOrder = vi.fn()
const mockGetProducts = vi.fn()
const mockGetProduct = vi.fn()
const mockGetProcessingItems = vi.fn()
const mockGetCraftCalcConfig = vi.fn()
const mockCraftCalcPreview = vi.fn()
const mockAutoFeaturesPreview = vi.fn()
const mockDoorWidthPlanPreview = vi.fn()
const mockFeePreview = vi.fn()

vi.mock('@/lib/api', () => ({
  approvalApi: { submit: () => Promise.resolve({ data: { data: { id: 'ap1' } } }) },
  orderApi: { createOrder: (...a: unknown[]) => mockCreateOrder(...a) },
  productApi: {
    getProducts: (...a: unknown[]) => mockGetProducts(...a),
    getProduct: (...a: unknown[]) => mockGetProduct(...a),
  },
  processingItemApi: { getProcessingItems: (...a: unknown[]) => mockGetProcessingItems(...a) },
  customerApi: { getCustomers: () => Promise.resolve({ data: { data: { items: [], total: 0 } } }) },
  craftCalcApi: { preview: (...a: unknown[]) => mockCraftCalcPreview(...a) },
  autoFeaturesApi: { preview: (...a: unknown[]) => mockAutoFeaturesPreview(...a) },
  doorWidthPlanApi: { preview: (...a: unknown[]) => mockDoorWidthPlanPreview(...a) },
  feePreviewApi: { preview: (...a: unknown[]) => mockFeePreview(...a) },
  productionApi: { getCraftCalcConfig: (...a: unknown[]) => mockGetCraftCalcConfig(...a) },
  uploadApi: { uploadImage: () => Promise.resolve({ data: { data: { url: 'https://cdn.test/x.png' } } }) },
  imageRecognizeApi: {
    recognize: () => Promise.resolve({ data: { data: { fields: [] } } }),
    interpret: () => Promise.resolve({ data: { data: { fields: [] } } }),
  },
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

import NewOrderPage from '@/app/(dashboard)/orders/new/page'

// ─────────────────────────────────────────────────────────────────────────────
// 替身实现（确定：同一份入参恒得同一份出参）
// ─────────────────────────────────────────────────────────────────────────────

/**
 * 算料试算：按「(宽+边距) × 褶倍」逐步四舍五入到 0.1 —— 与真实引擎同形但不联网。
 * 入参键**逐字取自** `lib/api.ts::CraftCalcParams`（`width` / `height` / `craft_tier`），
 * 不自己另起一套键名 —— 键名对不上会让替身恒返回 0 米，golden 就变成「0 的世界」的空判据。
 */
function calcPreview(params: unknown) {
  const p = (params ?? {}) as { width?: number; height?: number; craft_tier?: string }
  const w = Number(p.width) || 0
  const h = Number(p.height) || 0
  const fullness = p.craft_tier === 'economy' ? 1.8 : 2
  const raw = (w + 0.3) * fullness
  const meters = Math.round(raw * 10) / 10
  return Promise.resolve({
    data: {
      data: {
        fabric_meters: meters,
        pleat_count: Math.round(w * 8),
        per_panel_pleats: Math.round(w * 8),
        per_fold: 0.25,
        fullness,
        fullness_actual: Math.round((raw / Math.max(h, 1)) * 100) / 100,
        formula_text: `(${w}+0.3)×${fullness} → ${Math.round(w * 8)}折 → 0.25×${Math.round(w * 8)}+0.3 = ${meters}米`,
        source: '公式计算',
        craft_tier: 'standard',
        plan: {
          cutting_mode: '定高买宽',
          door_width: 2.8,
          panels: null,
          splice_option: null,
          splice_times: 0,
          join_height_m: null,
          join_width_m: null,
          meters,
          auto: true,
          reason: `自动推导：定高买宽单幅可做，用料 ${meters} 米`,
          candidates: [
            { key: 'fixed_height', feasible: true, meters, splice_times: 0, reason: null },
            { key: 'reversed', feasible: false, meters: null, splice_times: 3, reason: '倒幅 + 接宽不可行' },
          ],
        },
      },
    },
  })
}

/** 自动特征判定：确定返回「不判」（与「自动特征」正交，避免提交闸门干扰本次冻结的其它读数） */
function autoFeaturesPreview() {
  return Promise.resolve({
    data: { data: { auto_features: [], door_width: null, fullness_used: 2.0, notice: 'missing-door-width' } },
  })
}

/** 门幅规则面：确定返回单幅可做 */
function doorWidthPlanPreview() {
  return Promise.resolve({
    data: {
      data: {
        state: 'single_panel',
        code: '',
        effective_cutting_mode: '定高买宽',
        door_width: 2.8,
        panels: null,
        splice: false,
        verdict: 'optimal',
        suggestion: null,
        reason: '替身：单幅可做',
      },
    },
  })
}

/** 加工费计价预览：组合单价（元/米）× 加工费米数 —— 与真实口径同形 */
function feePreview(payload: unknown) {
  const body = (payload ?? {}) as { items?: Array<Record<string, unknown>> }
  const items = (body.items ?? []).map((it) => {
    const info = (it.processingInfo ?? {}) as Record<string, unknown>
    const meters = Number(info.processingMeters) || 0
    const names = ((info.processingItems ?? []) as Array<{ name?: string }>).map((d) => d?.name ?? '')
    const unit = names.reduce((s, n) => s + (FEE_UNIT_PRICE[n] || 0), 0)
    const fee = Math.round(unit * meters * 100) / 100
    return {
      processingFee: fee,
      processingFeeDetail: {
        composition: names.join('+') || null,
        fee_source: names.length > 0 ? 'matched' : 'unpriced',
        unit_price: unit,
        meters,
        amount: fee,
        hint: null,
      },
    }
  })
  const processingFeeTotal = items.reduce((s, r) => s + r.processingFee, 0)
  return Promise.resolve({ data: { data: { items, processingFeeTotal } } })
}

// ─────────────────────────────────────────────────────────────────────────────
// 采集与归一化
// ─────────────────────────────────────────────────────────────────────────────

const GOLDEN_PATH = resolve(__dirname, 'orders-new-slice-characterization.golden.json')
/** 只有它是写盘档，缺省**只读**（默认档不写盘 = 复核不会顺手把红改绿） */
const UPDATE = process.env.CHARACTERIZATION_UPDATE === '1'

const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g

/**
 * 归一化：只把 UUID 按**首次出现顺序**换成 `UUID_n`。
 * 同一 uuid ⇒ 同一占位符（恒等与别名关系因此仍然可判），其余字符**一个不动**。
 */
function normalize(text: string): string {
  const seen = new Map<string, string>()
  return text.replace(UUID_RE, (hit) => {
    const known = seen.get(hit)
    if (known) return known
    const tag = `UUID_${seen.size + 1}`
    seen.set(hit, tag)
    return tag
  })
}

interface Snapshot {
  /** ① 每个 `data-testid` 节点的可见文本（同名多个 ⇒ `[0]`/`[1]`…，DOM 顺序） */
  points: Record<string, string>
  /** ② 全页表单控件的 value / checked（DOM 顺序，键带标签锚点） */
  fields: Record<string, string>
  /** ③ 归一化后的整页 innerHTML（逐字节判据的本体） */
  html: string
}

function snapshot(container: HTMLElement): Snapshot {
  const points: Record<string, string> = {}
  const counts = new Map<string, number>()
  container.querySelectorAll('[data-testid]').forEach((el) => {
    const id = el.getAttribute('data-testid') ?? ''
    const n = counts.get(id) ?? 0
    counts.set(id, n + 1)
    points[`${id}[${n}]`] = normalize((el.textContent ?? '').trim())
  })

  const fields: Record<string, string> = {}
  container.querySelectorAll('input,select,textarea').forEach((el, i) => {
    const ctl = el as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
    const anchor =
      ctl.getAttribute('data-testid') ||
      ctl.getAttribute('placeholder') ||
      ctl.getAttribute('aria-label') ||
      ctl.getAttribute('name') ||
      ctl.tagName.toLowerCase()
    const type = ctl.getAttribute('type') ?? ''
    const key = `${i}:${ctl.tagName.toLowerCase()}${type ? `[${type}]` : ''}:${anchor}`
    if (ctl instanceof HTMLInputElement && (ctl.type === 'checkbox' || ctl.type === 'radio')) {
      fields[key] = ctl.checked ? 'checked' : 'unchecked'
    } else {
      fields[key] = normalize(ctl.value)
    }
  })

  return { points, fields, html: normalize(container.innerHTML) }
}

const goldens: Record<string, Snapshot> = existsSync(GOLDEN_PATH)
  ? (JSON.parse(readFileSync(GOLDEN_PATH, 'utf8')) as Record<string, Snapshot>)
  : {}
const recorded: Record<string, Snapshot> = {}

/**
 * 冻结一个场景：`UPDATE=1` 时只记账（写完盘再断言一次，防「录错也算绿」）；
 * 缺省档 **只读** —— 与 golden 逐字节比对。
 */
function freeze(scenario: string, container: HTMLElement): Snapshot {
  const actual = snapshot(container)
  if (UPDATE) {
    recorded[scenario] = actual
    return actual
  }
  const expected = goldens[scenario]
  if (!expected) {
    throw new Error(
      `golden 里没有场景「${scenario}」—— 先在**未切片**的代码上用 CHARACTERIZATION_UPDATE=1 录制（${GOLDEN_PATH}）`
    )
  }
  // ① 具名观测点：键级 diff（红了就说清是哪个读数漂了）
  expect(actual.points, `${scenario}: data-testid 观测点`).toEqual(expected.points)
  // ② 表单读数
  expect(actual.fields, `${scenario}: 表单控件读数`).toEqual(expected.fields)
  // ③ 渲染结果逐字节
  expect(actual.html.length, `${scenario}: innerHTML 字节数`).toBe(expected.html.length)
  expect(actual.html, `${scenario}: 渲染结果逐字节`).toBe(expected.html)
  return actual
}

// ─────────────────────────────────────────────────────────────────────────────
// 场景装配
// ─────────────────────────────────────────────────────────────────────────────

const pickInput = (label: string, idx = 0) => {
  const el = screen.getAllByText(label)[idx]
  const input = el.closest('div')?.querySelector('input') as HTMLInputElement | null
  if (!input) throw new Error(`找不到「${label}」所在容器里的 input`)
  return input
}

/**
 * **等计价预览跑完**再冻结（issue #8725 复核实测的 flake 根因）。
 *
 * `feePreviewPending` 为真时页面会印「加工费计价中…」，而那一刻屏幕上还是**上一轮**的读数
 * （实测：同一份代码在负载下会稳定地录到「加工 1 米」、在空载下录到「加工 13.8 米」）。
 * 把这一态录进 golden = 把**时序**当行为 ⇒ 负载一高就红（假红），而且没人看得出为什么。
 * ⇒ 冻结前必须等它消失（那一刻屏幕上的才是**最终**读数）。
 */
const waitFeeSettled = async () => {
  await waitFor(() => {
    expect(screen.queryByText('加工费计价中…')).toBeNull()
  })
}

/**
 * **静默判定**：屏幕上所有具名读数连续 3 次轮询不再变化 ⇒ 认为这一轮异步（算料 / 门幅规则 /
 * 计价预览 / 推荐默认）已经落定，然后把**那一刻**的样子冻进 golden。
 *
 * 为什么需要它：本页有 **4 条互不同步的异步链**（试算 400ms / 计价预览 300ms / 门幅规则 /
 * 推荐默认 effect）。只等其中一条（例如「计价中」消失）挡不住另一条**稍后**再改一次屏幕
 * ⇒ 同一份代码会稳定地录到不同的总额（实测 pristine 代码上就有 ¥1,265.56 / ¥1,424.30 /
 * ¥1,464.66 三种）⇒ golden 变成「时序的照片」，负载一高就假红。
 *
 * ⚠️ 这不是固定 sleep：**一静止立刻返回**（正常毫秒级）；只有真在变的时候才继续等。
 */
const waitQuiescent = async (container: HTMLElement) => {
  const read = () => {
    const snap = snapshot(container)
    return JSON.stringify([snap.points, snap.fields])
  }
  let prev = read()
  let stable = 0
  await waitFor(
    () => {
      const now = read()
      stable = now === prev ? stable + 1 : 0
      prev = now
      // 连续 12 次（≈600ms）相同 ⇒ 落定。**600ms 必须大于本页最长的防抖**（试算 400ms /
      // 计价预览 300ms），否则会在防抖**还没发出去**的那一刻误判「已落定」
      // （实测 3 次 ≈150ms 时仍会偶发假红）。抛错 = waitFor 继续等，不是失败。
      if (stable < 12) throw new Error('读数仍在变化，继续等')
    },
    { timeout: 15000, interval: 50 }
  )
}

const openStep = (title: string, idx = 0) => {
  const btns = screen.getAllByRole('button', { name: new RegExp(`^\\d+\\s*${title}`) })
  const btn = btns[idx]
  if (btn.getAttribute('aria-expanded') === 'false') fireEvent.click(btn)
}

/** 等页面挂载期的三个读面落地（商品目录 / 加工项目录 / 算料配置） */
async function mounted() {
  await waitFor(() => expect(mockGetCraftCalcConfig).toHaveBeenCalled())
  await waitFor(() => expect(mockGetProcessingItems).toHaveBeenCalled())
}

beforeEach(() => {
  vi.clearAllMocks()
  mockGetProducts.mockResolvedValue({ data: { data: { items: [PRODUCT], total: 1 } } })
  mockGetProduct.mockResolvedValue({ data: { data: PRODUCT } })
  mockGetProcessingItems.mockResolvedValue({ data: { data: { items: PROCESSING_ITEMS } } })
  mockGetCraftCalcConfig.mockResolvedValue({ data: { data: CALC_CONFIG } })
  mockCraftCalcPreview.mockImplementation(calcPreview)
  mockAutoFeaturesPreview.mockImplementation(autoFeaturesPreview)
  mockDoorWidthPlanPreview.mockImplementation(doorWidthPlanPreview)
  mockFeePreview.mockImplementation(feePreview)
  mockCreateOrder.mockResolvedValue({ data: { data: { id: 'order-1' } } })
})

/** 选商品 + 填净尺寸（后续所有场景的公共起点） */
async function pickProductAndSize(w = '6.6', h = '2.6') {
  fireEvent.click(await screen.findByText('点击搜索并选择商品'))
  fireEvent.click(await screen.findByText('测试窗帘'))
  await screen.findByText('窗宽 (米)')
  fireEvent.change(pickInput('窗宽 (米)'), { target: { value: w } })
  fireEvent.change(pickInput('窗高 (米)'), { target: { value: h } })
  // 试算 / 自动特征 / 门幅规则都是挂载后的异步面 ⇒ 等它们真的落地再采集。
  // 🔴 自证输入**真的**到了计算面（取最近一次调用的实参）：否则替身键名一错就恒算 0 米，
  //    整份 golden 会变成「0 的世界」而**照样录得出来**（= 空判据，一次都不红）。
  await waitFor(() => {
    expect(mockCraftCalcPreview.mock.calls.at(-1)?.[0]).toMatchObject({ width: Number(w), height: Number(h) })
  })
}

describe('下单页切片 · 行为冻结（characterization，issue #8725 第一档）', () => {
  // ⚠️ 用**固定超时**：本文件要跑完整条推导链（试算 + 自动特征 + 门幅规则 + 计价预览）
  describe('空表单（首屏）', { timeout: 30000 }, () => {
    it('初始态渲染逐字节冻结', async () => {
      const { container } = render(<NewOrderPage />)
      await mounted()
      await screen.findByText('新增订单')
      await waitQuiescent(container)
      freeze('01-empty', container)
    })
  })

  describe('成品帘（选商品 + 净尺寸）', { timeout: 30000 }, () => {
    it('① 用料与规格展开态（算料联动读数）② 勾加工项 + 费用明细展开态（价格预览读数）', async () => {
      const { container } = render(<NewOrderPage />)
      await mounted()
      await pickProductAndSize('6.6', '2.6')

      // ① 用料与规格 = 算料联动的主读数面（用料方案 / 公式 / 档位 / 推导明细）
      // ⚠️ 手风琴：展开一步会收起同级其它 ⇒ 这一处的读数必须**当场**冻结，
      //    否则下一步一展开它就退出 DOM，那些读数等于没被覆盖（空判据）。
      openStep('用料与规格')
      await screen.findByTestId('craft-plan')          // 自证：展开真的生效了（不是空场景）
      await screen.findByTestId('derivation-panel')
      await waitFeeSettled()
      await waitQuiescent(container)
      freeze('02-craft-spec', container)

      // ② 加工项：勾「打孔」（加工费组合键随之变化 ⇒ 计价预览重算）
      openStep('加工项')
      // 🔴 先等「系统推荐组合」**渲染出来**：推荐默认是挂载后由 effect 落的，
      //    在它之前按 `[0]` 抓 checkbox 会让「勾的是哪一项」随机器负载漂
      //    （实测：同一份代码录到 ¥1,464.66 / ¥1,265.56 / ¥1,424.30 三个总额）。
      await screen.findByTestId('processing-recommended')
      // 按**名字**抓，不按位置抓（位置是时序的函数，名字不是）
      fireEvent.click(await screen.findByRole('checkbox', { name: '打孔' }))
      // 勾完等它落定：勾选会改组合键 ⇒ 计价预览重算（防抖 300ms）
      await waitFor(() => {
        expect((screen.getByRole('checkbox', { name: '打孔' }) as HTMLInputElement).checked).toBe(true)
      })
      await waitFeeSettled()

      // ③ 费用明细（默认收起；展开才有逐行读数）
      const toggle = screen.getByTestId('fee-detail-toggle')
      if (toggle.getAttribute('aria-expanded') === 'false') fireEvent.click(toggle)
      await screen.findByText('费用明细')

      await screen.findByTestId('fee-detail-panel')
      // 计价预览是防抖（300ms）后发的 ⇒ 等它**跑完**（不是等它「开始」）
      await waitFeeSettled()
      await waitQuiescent(container)
      freeze('03-processing-fee', container)
    })
  })

  describe('布料行（售卖形态 = 布料 ⇒ FabricRow）', { timeout: 30000 }, () => {
    it('切售卖形态 → 布料行的米数 / 单价 / 卷数读数冻结', async () => {
      const { container } = render(<NewOrderPage />)
      await mounted()
      await pickProductAndSize('6.6', '2.6')
      await waitFeeSettled()

      // 售卖形态是组级 radiogroup（chips）
      const group = screen.getAllByRole('radiogroup', { name: '售卖形态' })[0]
      fireEvent.click(within(group).getByText('布料'))

      // 布料行 = 米数 / 单价（无加工）⇒ 改一次数量，把「按米计价」的读数也覆盖到
      const qty = await screen.findByText('数量')
      const input = qty.closest('div')?.querySelector('input') as HTMLInputElement | null
      if (!input) throw new Error('布料行找不到「数量」输入框')
      fireEvent.change(input, { target: { value: '12.5' } })
      await waitQuiescent(container)

      freeze('04-fabric', container)
    })
  })

  describe('golden 录制自洽（§19.1：录错也算绿）', { timeout: 30000 }, () => {
    it('UPDATE 档写完盘必须能被「只读档」原样读回', async () => {
      if (!UPDATE) {
        // 只读档：golden 必须存在且非空 —— 否则上面的场景会以「缺 golden」抛错，
        // 这里再补一条**具名**判据，让「golden 丢了」不是静默跳过。
        expect(Object.keys(goldens).sort()).toEqual(['01-empty', '02-craft-spec', '03-processing-fee', '04-fabric'])
        // 扫描面非空自证：每个场景都必须采到**具名**读数（0 处观测 = 空判据 ⇒ 红）
        const REQUIRED_ANCHORS: Record<string, string[]> = {
          '01-empty': ['fee-summary-total[0]', 'fee-detail-toggle[0]', 'order-logistics-type[0]'],
          '02-craft-spec': ['craft-plan[0]', 'craft-plan-meters[0]', 'meters-formula-text[0]'],
          '03-processing-fee': ['fee-detail-panel[0]', 'fee-combination-name[0]', 'fee-unit-price[0]'],
          '04-fabric': ['fee-summary-total[0]', 'group-input-row[0]', 'fee-detail-toggle[0]'],
        }
        for (const [key, anchors] of Object.entries(REQUIRED_ANCHORS)) {
          expect(Object.keys(goldens[key].points), `${key} 的具名观测点`).toEqual(
            expect.arrayContaining(anchors)
          )
        }
        // 布料行的两个读数（米数 / 单价）也必须真的采到（FabricRow 无 data-testid ⇒ 看表单层）
        expect(Object.values(goldens['04-fabric'].fields)).toEqual(expect.arrayContaining(['12.5']))
        return
      }
      // 录制档：写完盘后回读，逐字节等于本次采集
      const keys = Object.keys(recorded).sort()
      expect(keys).toEqual(['01-empty', '02-craft-spec', '03-processing-fee', '04-fabric'])
      writeFileSync(GOLDEN_PATH, JSON.stringify(recorded, null, 1) + '\n', 'utf8')
      const readBack = JSON.parse(readFileSync(GOLDEN_PATH, 'utf8')) as Record<string, Snapshot>
      for (const key of keys) {
        expect(readBack[key].html, `回读 ${key} 的 innerHTML`).toBe(recorded[key].html)
        expect(readBack[key].points, `回读 ${key} 的观测点`).toEqual(recorded[key].points)
        expect(readBack[key].fields, `回读 ${key} 的表单读数`).toEqual(recorded[key].fields)
      }
    })
  })
})

// 显式 cleanup：只保证本文件的 golden 采集不跨用例串容器
afterEach(() => {
  cleanup()
})
