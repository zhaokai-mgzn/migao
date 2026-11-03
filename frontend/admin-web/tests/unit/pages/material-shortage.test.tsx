// case_ids: MC-182
/**
 * 缺料风险页 `/production/material-shortage` 的**可执行判据**（issue #6282）。
 *
 * ## 判据（每条都能单独变红，红证写在 PR body 与下方注释里）
 *
 * - **① 真调后端**：页面必须打 `GET /api/admin/materials/shortage`（`materialShortageApi.shortage`，
 *   `limit = 50`），且屏上的数字**逐字等于**桩返回值 —— 页面若自算 / 硬编码 ⇒ 红。
 * - **② 默认只列真正缺的（负控）**：缺口 0 / 有余量 / 单位不可比**不进**常驻列表；
 *   勾选「显示全部」后**必须**能看到它们（缺口 0 照实印 `0 米`、有余量照实印负数）。
 *   🔴 红证（注入式，实测见 PR body）：把页面的 `shortageRows(rows)` 换成 `rows` ⇒ 本条红。
 * - **③ 行序 = 服务端行序**（分层降序 → 缺口降序）：页面**不重排**；桩数据三条缺口 120 / 30 / 5
 *   按服务端契约序给出，断言 DOM 序与缺口逐值降序（前端按名字/升序重排 ⇒ 红）。
 * - **④ 空态是事实陈述**：无缺料时逐字「当前没有缺料」，且**不得**出现「暂无数据」。
 * - **⑤ 未知 ≠ 0**：单位不可比的行（`gapMeters` / `demandQty` / `orderCount` 缺键 —— 服务端
 *   `default-property-inclusion: non_null`）一律渲染「未知」；`daysToDeadline` 缺键 ⇒「紧迫性未知」。
 * - **⑥ 披露与内部标识**：`non_comparable` 与 `history_depth.sufficient == false` 必须看得见；
 *   `productId` **不上屏**（只进 href，§31 P3）。
 * - **⑦ 读失败不印空态**：失败态只说失败，**不得**同时印「当前没有缺料」（读不到 ≠ 没有缺料）。
 *
 * ## 桩数据为什么**故意不自洽**
 *
 * `bandCounts`（全量行算）与列表条数**不相等**，且三条缺料缺口互不相等 ⇒ 页面一旦「顺手」
 * 用 `rows.length` 冒充「共 N 个缺料」或自己求和，断言立刻红。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

const mockShortage = vi.fn()

// 接口面在独立模块里（`src/lib/api.ts` 属 LOC 冻结面，新增接口面下沉）
vi.mock('@/lib/api-material-shortage', () => ({
  materialShortageApi: {
    shortage: (...a: unknown[]) => mockShortage(...a),
  },
}))

// 共享原语是「服务端业务文案优先」的出口：判据只关心失败态**不冒充空态**，故取 fallback
vi.mock('@/lib/api-error', () => ({
  extractApiErrorMessage: (_e: unknown, fallback: string) => fallback,
  toastRequestError: () => undefined,
}))

// 显式列出本页用到的图标（**不要用 Proxy**：实测 vitest 收集阶段会挂死）
vi.mock('lucide-react', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  const Icon = () => null
  return { ...actual, AlertTriangle: Icon, RefreshCw: Icon }
})

import MaterialShortagePage from '@/app/(dashboard)/production/material-shortage/page'
import type { MaterialShortageRow, MaterialShortageView } from '@/types/material-shortage'

const ok = (data: unknown) => ({ data: { data } })

const PRODUCT_ID = '11111111-1111-4111-8111-111111111111'

/** 缺口 120（交期已过）—— 缺料 #1 */
const BLOCKED: MaterialShortageRow = {
  productId: PRODUCT_ID,
  productName: '蓝灰麻布',
  demandQty: 320,
  demandLines: 4,
  orderCount: 3,
  stockMeters: 200,
  gapMeters: 120,
  riskBand: 'blocked',
  daysToDeadline: -2,
  earliestRequiredDeliveryDate: '2026-10-01',
}

/** 缺口 30（交期紧张）—— 缺料 #2 */
const CRITICAL: MaterialShortageRow = {
  productId: '22222222-2222-4222-8222-222222222222',
  productName: '米白纱帘',
  demandQty: 210,
  demandLines: 2,
  orderCount: 2,
  stockMeters: 180,
  gapMeters: 30,
  riskBand: 'critical',
  daysToDeadline: 2,
  earliestRequiredDeliveryDate: '2026-10-05',
}

/** 缺口 5、交期未知（`daysToDeadline` 缺键）—— 缺料 #3 */
const SHORT: MaterialShortageRow = {
  productId: '33333333-3333-4333-8333-333333333333',
  productName: '灰绿棉麻',
  demandQty: 105,
  demandLines: 1,
  orderCount: 1,
  stockMeters: 100,
  gapMeters: 5,
  riskBand: 'short',
}

/** 缺口 0（刚好够）—— 默认面**不得**出现 */
const JUST_ENOUGH: MaterialShortageRow = {
  productId: '44444444-4444-4444-8444-444444444444',
  productName: '素色衬布',
  demandQty: 60,
  demandLines: 1,
  orderCount: 1,
  stockMeters: 60,
  gapMeters: 0,
  riskBand: 'safe',
  daysToDeadline: 5,
  earliestRequiredDeliveryDate: '2026-10-08',
}

/** 有余量（缺口 -40，照实显示）—— 默认面**不得**出现 */
const SURPLUS: MaterialShortageRow = {
  productId: '55555555-5555-4555-8555-555555555555',
  productName: '驼色绒布',
  demandQty: 20,
  demandLines: 1,
  orderCount: 1,
  stockMeters: 60,
  gapMeters: -40,
  riskBand: 'safe',
  daysToDeadline: 9,
  earliestRequiredDeliveryDate: '2026-10-12',
}

/** 单位不可比（`demandQty` / `gapMeters` / `orderCount` 缺键 = 读不出，**不是 0**） */
const NON_COMPARABLE: MaterialShortageRow = {
  productId: '66666666-6666-4666-8666-666666666666',
  productName: '亚麻混纺',
  stockMeters: 12,
  riskBand: 'unknown',
  unwired: ['demand_qty', 'demand_lines', 'order_count', 'gap_meters', 'risk_band'],
}

const VIEW: MaterialShortageView = {
  view: 'material_shortage',
  tenantId: 1,
  asOf: '2026-10-04',
  rows: [BLOCKED, CRITICAL, SHORT, JUST_ENOUGH, SURPLUS, NON_COMPARABLE],
  count: 6,
  rowsTotal: 6,
  truncated: false,
  // 全量行算的六档（≠ 本页 rows.length 的语义点：缺料 = 四档之和 = 3）
  bandCounts: { blocked: 1, critical: 1, soon: 0, short: 1, safe: 2, unknown: 1 },
  nonComparable: { lines: 2, products: 1 },
  nonComparableLines: 2,
  nonComparableProducts: 1,
  historyDepth: { weeks: 3, activeWeeks: 2, requiredWeeks: 8, sufficient: false },
}

const names = (): (string | null)[] =>
  screen.getAllByTestId('shortage-row').map((r) => within(r).getByTestId('shortage-name').textContent)

const cells = (testid: string): (string | null)[] =>
  screen.getAllByTestId('shortage-row').map((r) => within(r).getByTestId(testid).textContent)

const renderPage = async () => {
  render(<MaterialShortagePage />)
  await waitFor(() => expect(mockShortage).toHaveBeenCalledTimes(1))
  return screen.findByTestId('shortage-summary')
}

beforeEach(() => {
  mockShortage.mockReset()
  mockShortage.mockResolvedValue(ok(VIEW))
})

describe('缺料风险页（issue #6282）', () => {
  it('① 真调后端：一条读面 + 数字逐字来自服务端', async () => {
    await renderPage()

    expect(mockShortage).toHaveBeenCalledWith({ limit: 50 })
    // 三个数并列（需求 / 库存 / 缺口）且全部来自桩返回值 —— 页面若自算 ⇒ 红
    expect(cells('shortage-demand')).toEqual(['320 米', '210 米', '105 米'])
    expect(cells('shortage-stock')).toEqual(['200 米', '180 米', '100 米'])
    expect(cells('shortage-gap')).toEqual(['120 米', '30 米', '5 米'])
    expect(cells('shortage-orders')).toEqual(['3 个订单', '2 个订单', '1 个订单'])
    // 缺料条数取服务端 bandCounts（四档之和 = 3），不是本页 rows.length
    expect(screen.getByTestId('shortage-summary').textContent).toBe(
      '共 3 个成品缺料 交期已过 1 · 交期紧张 1 · 有缺口 1 · 有余量 2 · 单位不可比 1'
    )
  })

  it('② 默认只列缺口 > 0；缺口 0 / 有余量 / 单位不可比靠「显示全部」才看得到（负控）', async () => {
    await renderPage()

    expect(names()).toEqual(['蓝灰麻布', '米白纱帘', '灰绿棉麻'])
    expect(names().includes('素色衬布')).toBe(false)
    expect(names().includes('驼色绒布')).toBe(false)
    expect(names().includes('亚麻混纺')).toBe(false)

    // 负控出口：勾选后三行都在，且缺口照实显示（0 / 负数**不夹到 0**）
    fireEvent.click(screen.getByTestId('shortage-show-all'))
    expect(names()).toEqual(['蓝灰麻布', '米白纱帘', '灰绿棉麻', '素色衬布', '驼色绒布', '亚麻混纺'])
    expect(cells('shortage-gap')).toEqual(['120 米', '30 米', '5 米', '0 米', '-40 米', '未知'])
  })

  it('③ 行序 = 服务端行序（分层降序 → 缺口降序），前端不重排', async () => {
    await renderPage()

    expect(names()).toEqual(['蓝灰麻布', '米白纱帘', '灰绿棉麻'])
    // 缺口逐值递减（造三条**不同**缺口的数据 ⇒ 顺序可判）
    expect(cells('shortage-gap')).toEqual(['120 米', '30 米', '5 米'])
    expect(cells('shortage-band').map((t) => t?.split('紧迫性')[0].split('2026')[0])).toEqual([
      '交期已过',
      '交期紧张',
      '有缺口',
    ])
  })

  it('④ 空态是事实陈述：逐字「当前没有缺料」，且不出现「暂无数据」', async () => {
    mockShortage.mockResolvedValue(
      ok({ ...VIEW, rows: [JUST_ENOUGH], count: 1, rowsTotal: 1, bandCounts: { blocked: 0, critical: 0, soon: 0, short: 0, safe: 1, unknown: 0 } })
    )
    render(<MaterialShortagePage />)
    const empty = await screen.findByTestId('shortage-empty')

    expect(empty.textContent).toBe('当前没有缺料')
    expect(screen.queryByText('暂无数据')).toBeNull()
    expect(screen.queryByTestId('shortage-table')).toBeNull()
    // 摘要位同样是事实陈述（不是「共 0 个成品缺料」这种伪读数）
    expect(screen.getByTestId('shortage-summary').textContent).toBe('当前没有缺料')
  })

  it('⑤ 未知 ≠ 0：单位不可比的行渲染「未知」，交期缺键渲染「紧迫性未知」', async () => {
    await renderPage()
    fireEvent.click(screen.getByTestId('shortage-show-all'))

    const unknownRow = screen.getAllByTestId('shortage-row')[5]
    expect(within(unknownRow).getByTestId('shortage-gap').textContent).toBe('未知')
    expect(within(unknownRow).getByTestId('shortage-demand').textContent).toBe('未知')
    expect(within(unknownRow).getByTestId('shortage-orders').textContent).toBe('未知')
    expect(within(unknownRow).getByTestId('shortage-band').textContent).toContain('单位不可比')

    // 交期缺键 ⇒ 「紧迫性未知」（**不得**显示「0 天」）
    expect(cells('shortage-deadline')).toEqual([
      '2026-10-01（已过 2 天）',
      '2026-10-05（2 天后）',
      '紧迫性未知',
      '2026-10-08（5 天后）',
      '2026-10-12（9 天后）',
      '紧迫性未知',
    ])
    expect(screen.queryByText('0 天')).toBeNull()
  })

  it('⑥ 披露看得见（单位不可比 / 预测层未启用），内部标识不上屏（§31 P3）', async () => {
    await renderPage()

    expect(screen.getByTestId('shortage-non-comparable').textContent).toBe(
      '另有 1 个成品（2 行订单）单位不是「米」⇒ 需求与缺口读不出，未计入上面的数字'
    )
    expect(screen.getByTestId('shortage-history-depth').textContent).toBe(
      '预测层未启用：真实历史深度 3 周 < 要求 8 周 ⇒ 周消耗速率与预计耗尽日为未知'
    )

    // P3：商品主键（UUID）与字段名都不得出现在可见文本里
    expect(screen.queryByText(PRODUCT_ID)).toBeNull()
    expect(document.body.textContent?.includes('product_id')).toBe(false)
    expect(document.body.textContent?.includes('gap_meters')).toBe(false)

    // 处置入口是仓内真实路由（不是死链）；productId 只进 href
    expect(screen.getAllByTestId('shortage-product-link')[0].getAttribute('href')).toBe(`/products/${PRODUCT_ID}`)
    expect(screen.getAllByTestId('shortage-ledger-link')[0].getAttribute('href')).toBe('/stock-ledger')
    expect(screen.getAllByTestId('shortage-inbound-link')[0].getAttribute('href')).toBe('/inbound-orders/new')
  })

  it('⑦ 读失败不印空态：只说失败，不冒充「当前没有缺料」', async () => {
    mockShortage.mockRejectedValue(new Error('boom'))
    render(<MaterialShortagePage />)

    expect(await screen.findByTestId('shortage-error')).toBeTruthy()
    expect(screen.getByTestId('shortage-error').textContent).toBe('加载失败：加载缺料风险失败')
    expect(screen.queryByText('当前没有缺料')).toBeNull()
    expect(screen.queryByTestId('shortage-summary')).toBeNull()
  })
})
