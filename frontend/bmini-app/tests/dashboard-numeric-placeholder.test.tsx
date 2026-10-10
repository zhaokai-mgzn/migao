// case_ids: BM-040
/**
 * 「数据」页数字卡：**空 / 缺值 / 坏值不许印成 `NaN元`**（issue #6685，涉钱面）
 *
 * ## 治的形态（两臂截图可见，2026-10-10）
 *
 * 服务端 **200 + 空 data**（`{}` / 缺键）时，`getDashboardStats()` 仍返回
 * `{status:'ok', data:{}}` ⇒ `stats` 是**真值但一个字段都没有**，页面把 `undefined`
 * 送进算钱/格式化路径：`formatYuan(undefined)` = `(undefined/100).toLocaleString(...)`
 * ⇒ 商家屏上「今日销售额」「本月营收」印出 **`NaN元`**（旁边「今日订单」「活跃会话」
 * 走 `?? '--'`，形态是对的 —— 同页两套口径）。
 *
 * 为什么算缺陷：`NaN` 在**涉钱面**读起来是「系统坏了」，比 `--` 坏得多；
 * 而 `--` = 「没有这个数」、`0.00` = 「数是 0」—— **两者不许混成一个样子**。
 *
 * ## 判据
 *
 * | # | 判据 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | `200 + data:{}` ⇒ 两张钱卡读数是 `--`，**全页文本不含** `NaN` / `undefined` / `Infinity` | `undefined` 进算钱路径 ⇒ 红 |
 * | 2 | 占位后面**不挂单位**（不出 `--元`） | 单位无条件渲染 ⇒ 红 |
 * | 3 | 真给 `0` ⇒ 印 `0.00`（不是 `--`）：「没有这个数」≠「数是 0」 | 把 0 也说成「没有」⇒ 红 |
 * | 4 | 真给数 ⇒ 正常渲染（`123400` 分 ⇒ `1,234.00`），正常路径没被改坏 | 误伤正常路径 ⇒ 红 |
 * | 5 | `undefined` 涨跌幅 ⇒ `--`，**不得**被 `?? 0` 说成「持平」（`+0.0%`） | 缺值当成 0 ⇒ 红 |
 * | 6 | 反向对照：整页文本含 `NaN` 时扫描器**抓得到**（否则上面几条是空断言） | 扫描器退化成恒绿 ⇒ 红 |
 */
import React from 'react'
import '@testing-library/jest-dom'
import { render, waitFor } from '@testing-library/react'

// —— 数据面：只桩网络（`src/utils/request` 的 `get`，与同页三态用例同款桩法），页面与 service 走真实现 ——
jest.mock('../src/utils/request', () => ({
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  patch: jest.fn(),
  del: jest.fn(),
}))

jest.mock('../src/store/authStore', () => ({
  useAuthStore: jest.fn(() => ({ user: { id: 'u1', nickname: '王老板', tenantId: 1 } })),
}))

jest.mock('../src/components/admin/useMobileMenu', () => ({
  useMobileMenu: () => ({ state: 'ok', surfaces: [], tabs: [] }),
}))

jest.mock('../src/utils/roleGuard', () => ({
  useMerchantSurfaceGuard: jest.fn(),
}))

import { get } from '../src/utils/request'
import DashboardPage from '../src/pages/dashboard/index/index'
import { formatYuan, formatPercent, DASHBOARD_EMPTY_VALUE } from '../src/services/dashboardService'

const mockGet = get as jest.MockedFunction<typeof get>

/** 会印在商家屏上的「坏值」记号（`NaN`/`undefined`/`Infinity` 一族） */
const FORBIDDEN_TEXT = ['NaN', 'undefined', 'Infinity', '[object Object]']

/**
 * 整页文本扫描：命中 `FORBIDDEN_TEXT` 的**可见文本节点**逐条报出（含所在元素）。
 *
 * ⚠️ `innerText` 读的是**渲染后**的文字 ⇒ 正是商家屏上能看到的东西。
 */
function forbiddenHits(root: HTMLElement): string[] {
  const text = root.textContent ?? ''
  return FORBIDDEN_TEXT.filter((s) => text.includes(s)).map((s) => {
    const el = [...root.querySelectorAll('*')].find((e) => (e.textContent ?? '').includes(s))
    return `${s} @ <${el?.tagName.toLowerCase() ?? '?'} class="${String((el as HTMLElement)?.className ?? '')}">`
  })
}

// ── 端点桩（`get()` 是 service 唯一出口；URL 按 `includes` 匹配，不吃 baseURL 形态）──
type Mode = 'json' | 'error' | 'forbidden'

const TODO_OK = {
  generated_at: '2026-10-10T09:00:00+08:00',
  todo_total: 0,
  todos: [],
  stats: {
    todo_total: 0,
    by_type: { to_schedule: 0, stuck: 0, to_ship: 0 },
    operations: { not_started: 0, in_progress: 0, completed: 0 },
    stuck_threshold_hours: 4,
    threshold_source: 'default',
    scan: { order_scan_limit: 50, truncated: false },
  },
}

function stub(opts: { stats?: Mode; statsData?: unknown } = {}) {
  const { stats = 'json', statsData = {} } = opts
  mockGet.mockImplementation(async (url: string) => {
    if (url.includes('/api/admin/dashboard/stats')) {
      if (stats === 'forbidden') throw Object.assign(new Error('403'), { statusCode: 403 })
      if (stats === 'error') throw new Error('network down')
      // 🔴 形态：HTTP 200 + `success:true` + **空 data**（本单的触发形态）
      return { success: true, code: 200, message: 'ok', data: statsData } as any
    }
    if (url.includes('/pending-tasks')) return { success: true, code: 200, message: 'ok', data: [] } as any
    if (url.includes('/production/todo-overview')) return { success: true, code: 200, message: 'ok', data: TODO_OK } as any
    return { success: true, code: 200, message: 'ok', data: null } as any
  })
}

/** 数字卡「读数本身」的文本（去掉首尾空白）—— 判据读值，不读整张卡的文字 */
function metricValue(testId: string): string {
  const el = document.querySelector(`[data-testid="${testId}"]`)
  if (!el) throw new Error(`找不到 ${testId}`)
  return (el.textContent ?? '').trim()
}

beforeEach(() => {
  jest.clearAllMocks()
})

describe('「数据」页数字卡：空 / 坏值落 `--`（issue #6685）', () => {
  it('🔴 200 + data:{} ⇒ 两张钱卡是 `--`，全页不出现 NaN / undefined / Infinity', async () => {
    stub({ statsData: {} })
    const { container } = render(<DashboardPage />)

    await waitFor(() => expect(container.querySelector('[data-testid="dashboard-metric-today-sales"]')).toBeTruthy())

    expect(metricValue('dashboard-metric-today-sales')).toBe(DASHBOARD_EMPTY_VALUE)
    expect(metricValue('dashboard-metric-month-revenue')).toBe(DASHBOARD_EMPTY_VALUE)
    expect(forbiddenHits(container)).toEqual([])
  })

  it('🔴 200 + data:[]（数组形态的空 data）同样不许出坏值', async () => {
    stub({ statsData: [] })
    const { container } = render(<DashboardPage />)

    await waitFor(() => expect(container.querySelector('[data-testid="dashboard-metric-today-sales"]')).toBeTruthy())

    expect(metricValue('dashboard-metric-today-sales')).toBe(DASHBOARD_EMPTY_VALUE)
    expect(forbiddenHits(container)).toEqual([])
  })

  it('占位后面不挂单位（不出 `--元`）', async () => {
    stub({ statsData: {} })
    const { container } = render(<DashboardPage />)

    await waitFor(() => expect(container.querySelector('[data-testid="dashboard-metric-today-sales"]')).toBeTruthy())

    const salesRow = container.querySelector('[data-testid="dashboard-metric-today-sales"]')!.parentElement!
    expect(salesRow.textContent).toBe(DASHBOARD_EMPTY_VALUE)
    expect(container.textContent).not.toContain('--元')
  })

  it('真给 `0` ⇒ 印 `0.00`（「没有这个数」≠「数是 0」）', async () => {
    stub({ statsData: { todaySales: 0, monthRevenue: 0, todayOrders: 0, activeSessions: 0 } })
    const { container } = render(<DashboardPage />)

    await waitFor(() => expect(container.querySelector('[data-testid="dashboard-metric-today-sales"]')).toBeTruthy())

    expect(metricValue('dashboard-metric-today-sales')).toBe('0.00')
    expect(metricValue('dashboard-metric-month-revenue')).toBe('0.00')
    expect(forbiddenHits(container)).toEqual([])
  })

  it('真给数 ⇒ 正常渲染（123400 分 ⇒ `1,234.00`），正常路径没被改坏', async () => {
    stub({ statsData: { todaySales: 123400, monthRevenue: 5678000, todayOrders: 12, activeSessions: 4 } })
    const { container } = render(<DashboardPage />)

    await waitFor(() => expect(container.querySelector('[data-testid="dashboard-metric-today-sales"]')).toBeTruthy())

    expect(metricValue('dashboard-metric-today-sales')).toBe('1,234.00')
    expect(metricValue('dashboard-metric-month-revenue')).toBe('56,780.00')
    expect(forbiddenHits(container)).toEqual([])
  })

  it('🔴 缺涨跌幅 ⇒ `--`（不得被 `?? 0` 说成「持平 +0.0%」）', async () => {
    stub({ statsData: { todaySales: 0, todayOrdersChange: undefined } })
    const { container } = render(<DashboardPage />)

    await waitFor(() => expect(container.querySelector('[data-testid="dashboard-metric-today-sales"]')).toBeTruthy())

    expect(container.textContent).not.toContain('+0.0%')
    expect(container.textContent).not.toContain('+100.0%')
  })

  it('🔴 反向对照：整页文本含 `NaN` 时扫描器抓得到（上面几条不是空断言）', () => {
    const bad = document.createElement('div')
    bad.innerHTML = '<span class="metric-card__value">NaN</span>'
    expect(forbiddenHits(bad).length).toBeGreaterThan(0)
    expect(forbiddenHits(bad)[0]).toContain('NaN')
  })
})

describe('格式化层的空值口径（issue #6685，涉钱面）', () => {
  it('formatYuan：空 / 缺值 / 坏值 ⇒ `--`，真实数照常（含 0）', () => {
    expect(formatYuan(undefined)).toBe(DASHBOARD_EMPTY_VALUE)
    expect(formatYuan(null)).toBe(DASHBOARD_EMPTY_VALUE)
    expect(formatYuan(NaN)).toBe(DASHBOARD_EMPTY_VALUE)
    expect(formatYuan(Infinity)).toBe(DASHBOARD_EMPTY_VALUE)
    expect(formatYuan(0)).toBe('0.00')
    expect(formatYuan(123400)).toBe('1,234.00')
  })

  it('formatPercent：空 / 缺值 / 坏值 ⇒ `--`，真实数照常（含 0 与正负号）', () => {
    expect(formatPercent(undefined)).toBe(DASHBOARD_EMPTY_VALUE)
    expect(formatPercent(null)).toBe(DASHBOARD_EMPTY_VALUE)
    expect(formatPercent(NaN)).toBe(DASHBOARD_EMPTY_VALUE)
    expect(formatPercent(0)).toBe('0.0%')
    expect(formatPercent(1.5)).toBe('+1.5%')
    expect(formatPercent(-0.5)).toBe('-0.5%')
  })

  it('🔴 反向对照：旧实现（无守卫）逐字照抄 ⇒ 真会印出坏值 / 抛错', () => {
    // 修前 `formatYuan` 逐字照抄（`frontend/bmini-app/src/services/dashboardService.ts`）
    const legacyYuan = (cents: number) =>
      (cents / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    // 🔴 这就是截图上的 `NaN元`（`undefined/100` ⇒ `NaN`）
    expect(legacyYuan(undefined as any)).toContain('NaN')
    expect(legacyYuan(undefined as any)).not.toBe(DASHBOARD_EMPTY_VALUE)

    // 修前 `formatPercent` 逐字照抄：缺值不是印坏值，是**直接抛**（`undefined.toFixed`）
    const legacyPercent = (value: number) => `${value > 0 ? '+' : ''}${value.toFixed(1)}%`
    expect(() => legacyPercent(undefined as any)).toThrow(/toFixed/)
  })
})
