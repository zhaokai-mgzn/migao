// case_ids: PG-021
// PG-021（issue #4205，前端半边）：计件工资报表页 /production/piecework ——
// 消费 GET /api/admin/production/piecework/summary?period=YYYY-MM[&worker_name=]，
// 按期间（月份选择）+ 按工人 / 按工序两档展示；默认期间 = 当前月（不空查）。
// 反 placeholder：断言必须落到**真实金额/数量**，不能只断言页面存在。
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// ── 冻结墙钟（issue #4761，形态 A「用墙钟造期望值」）──────────────────────────
// 病根：期望值取自**断言时刻**的墙钟，页面取**渲染时刻**的墙钟 —— 两个时刻各自算「当前月」，
// 跨月/跨日边界必红（落在 required 的 `admin-web typecheck + unit tests` 里 ⇒ 随机卡任何前端 PR）。
// 修法：把系统时钟冻结在一个**远离月/日边界**的时刻，期望值与页面同刻派生。
//
// ⚠️ 冻结走独立模块 `../helpers/frozen-clock`（导入期夹具）：`import` 声明会被提升，
//    写在文件里「先 `useFakeTimers()` 后 `import Page`」**不成立**（实测，见夹具注释）。
//
// 「月」的**时区口径 = 本地月**（issue #4761 的结论，证据三条）：
//   ① 后端 `ProductionService.pieceworkSummary` 用 `work_date`（`LocalDate`，**无时区**）
//      ∈ `[month.atDay(1), month.atEndOfMonth()]` 过滤 ⇒ `period` 指的是「那一天所在的那个月」；
//   ② 后端 `application.yml` 的 `spring.jackson.time-zone: Asia/Shanghai`（同一份文件）；
//   ③ 同域的财务页默认期间 `getCurrentPeriod()` 用 `getFullYear()/getMonth()`（**本地**月）。
// ⇒ 语义结论：**本地月**。`toISOString().slice(0, 7)` 是 **UTC** 月，**不得**用作期望值：
//    在 UTC+8 的每月 1 日 00:00~08:00 这 8 小时里，UTC 月 = 上一个月。
//
// ✅ 分叉已收口（issue #4772）：页面的 `currentPeriod()` 原为 `new Date().toISOString().slice(0, 7)`
//    （**UTC** 月）⇒ 上面那 8 小时窗口里页面默认查**上一个月**（用户本地已是新月份）= **真实产品缺陷**。
//    已改为**本地月**（`getFullYear()/getMonth()`），故本文件期望值同步改为**本地月派生**。
//    红证见文件末 `describe('默认期间 = 本地月（issue #4772 红证）')`：固定时刻取**显式 +08:00**
//    偏移（不依赖跑测机器时区）⇒ 改前必红（`period=2026-09`）、改后绿（`2026-10`）。
import { FROZEN_NOW } from '../helpers/frozen-clock'

/**
 * 期望值 = 从**冻结后的系统时钟**派生的「当前月」（与页面同一真值源）。
 *
 * ⚠️ 用**本地月**而非 `toISOString().slice(0, 7)`（UTC 月）：后者在 UTC+8 的每月 1 日
 * 00:00~08:00 这 8 小时里给出上一个月（口径证据见文件头三条）。派生口径与页面 `currentPeriod()`
 * 逐字一致 —— 这正是本用例的判别力来源：页面若回退成 UTC 月，文件末的红证会立刻红。
 */
function expectedPeriod(now: Date): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

const mockGetPieceworkSummary = vi.fn()

vi.mock('@/lib/api', () => ({
  productionApi: {
    getPieceworkSummary: (...args: unknown[]) => mockGetPieceworkSummary(...args),
  },
}))

import PieceworkReportPage from '@/app/(dashboard)/production/piecework/page'

const REPORT = {
  period: '2026-09',
  total: 123.45,
  per_worker: [
    { worker_name: '张三', amount: 80, qty: 200 },
    { worker_name: '李红梅', amount: 43.45, qty: 111 },
  ],
  per_operation: [
    // issue #4621：后端补的显示名派生键（`operation` = 工人端快照名 = 变体名，界面不得渲染）
    { operation: '韩褶-布', logical_name: '韩褶', position: '布帘', amount: 40, qty: 100 },
    { operation: '定型-布', logical_name: '定型', position: '布帘', amount: 83.45, qty: 211 },
  ],
  // 下钻两维（issue #4347 §3.2）：后端**同一份聚合**产出 ⇒ 各维合计 = total = 123.45
  per_position: [
    { position_name: '布艺遮光帘A 米白', amount: 83.45, qty: 211 },
    { position_name: '纱帘B 本白', amount: 40, qty: 100 },
  ],
  per_set: [
    { order_item_id: 'item-A', amount: 83.45, qty: 211 },
    { order_item_id: 'item-B', amount: 40, qty: 100 },
  ],
}

const ok = (data: unknown) => ({ data: { success: true, data } })

describe('计件工资报表页 /production/piecework', () => {
  beforeEach(() => {
    vi.setSystemTime(FROZEN_NOW) // 每条用例都回到同一冻结时刻
    mockGetPieceworkSummary.mockReset().mockResolvedValue(ok(REPORT))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('默认期间 = 当前月（YYYY-MM），首屏即查（不空查）', async () => {
    // 期望值从**与页面同一真值源**（冻结后的系统时钟）派生 —— 不再是「断言时刻的墙钟」，
    // 故渲染/断言之间不可能跨月（改前形态：`new Date().toISOString().slice(0, 7)` 各自取时钟）。
    const expected = expectedPeriod(FROZEN_NOW)
    render(<PieceworkReportPage />)

    await waitFor(() => expect(mockGetPieceworkSummary).toHaveBeenCalled())
    expect(mockGetPieceworkSummary).toHaveBeenCalledWith({ period: expected, worker_name: undefined })
    expect(screen.getByTestId('piecework-period')).toHaveValue(expected)
  })

  it('渲染真实报表：合计 + 按工人档（姓名/金额/数量）', async () => {
    render(<PieceworkReportPage />)

    await waitFor(() => expect(screen.getByTestId('piecework-report-total')).toHaveTextContent('¥123.45'))
    const workers = screen.getByTestId('piecework-by-worker')
    expect(within(workers).getByText('张三')).toBeInTheDocument()
    expect(within(workers).getByTestId('worker-row-张三')).toHaveTextContent('¥80.00')
    expect(within(workers).getByTestId('worker-row-张三')).toHaveTextContent('200')
    expect(within(workers).getByTestId('worker-row-李红梅')).toHaveTextContent('¥43.45')
  })

  it('切「按工序」档：展示工序聚合（工序名/金额/数量）', async () => {
    render(<PieceworkReportPage />)
    await waitFor(() => expect(screen.getByTestId('piecework-by-worker')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('piecework-tab-operation'))

    const operations = screen.getByTestId('piecework-by-operation')
    // issue #4621：只显示「逻辑名 · 部位」——变体名（`韩褶-布`）不进界面，也不进 testid
    expect(within(operations).getByTestId('operation-row-韩褶 · 布帘')).toHaveTextContent('¥40.00')
    expect(within(operations).getByTestId('operation-row-定型 · 布帘')).toHaveTextContent('¥83.45')
    expect(within(operations).queryByTestId('operation-row-韩褶-布')).toBeNull()
    expect(within(operations).queryByText('韩褶-布')).toBeNull()
    expect(screen.queryByTestId('piecework-by-worker')).not.toBeInTheDocument()
  })

  it('老数据缺 logical_name ⇒ 退回 operation 原文（不显示空白）', async () => {
    mockGetPieceworkSummary.mockResolvedValue(
      ok({
        ...REPORT,
        per_operation: [{ operation: '定型-布', amount: 83.45, qty: 211 }],
      }),
    )
    render(<PieceworkReportPage />)
    await waitFor(() => expect(screen.getByTestId('piecework-by-worker')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('piecework-tab-operation'))

    const operations = screen.getByTestId('piecework-by-operation')
    expect(within(operations).getByTestId('operation-row-定型-布')).toHaveTextContent('¥83.45')
  })

  it('切「按工人」档可回到工人视图', async () => {
    render(<PieceworkReportPage />)
    await waitFor(() => expect(screen.getByTestId('piecework-by-worker')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('piecework-tab-operation'))
    await userEvent.click(screen.getByTestId('piecework-tab-worker'))

    expect(screen.getByTestId('piecework-by-worker')).toBeInTheDocument()
  })

  it('换月份：按新期间重查', async () => {
    render(<PieceworkReportPage />)
    await waitFor(() => expect(mockGetPieceworkSummary).toHaveBeenCalledTimes(1))

    const periodInput = screen.getByTestId('piecework-period')
    await userEvent.clear(periodInput)
    await userEvent.type(periodInput, '2026-08')

    await waitFor(() => expect(mockGetPieceworkSummary).toHaveBeenCalledWith({ period: '2026-08', worker_name: undefined }))
  })

  it('按工人筛选：worker_name 传入请求', async () => {
    render(<PieceworkReportPage />)
    await waitFor(() => expect(screen.getByTestId('piecework-by-worker')).toBeInTheDocument())

    await userEvent.type(screen.getByTestId('piecework-worker-input'), '张三')
    await userEvent.click(screen.getByTestId('piecework-search'))

    await waitFor(() =>
      expect(mockGetPieceworkSummary).toHaveBeenLastCalledWith({ period: expect.any(String), worker_name: '张三' }),
    )
  })

  it('期间无报工：空态提示（不显示 ¥0.00 假数据）', async () => {
    mockGetPieceworkSummary.mockResolvedValue(ok({ period: '2026-08', total: 0, per_worker: [], per_operation: [] }))
    render(<PieceworkReportPage />)

    await waitFor(() => expect(screen.getByTestId('piecework-empty')).toBeInTheDocument())
    expect(screen.queryByTestId('piecework-by-worker')).not.toBeInTheDocument()
  })

  it('接口失败：错误提示 + 重试按钮', async () => {
    mockGetPieceworkSummary.mockRejectedValueOnce(new Error('boom'))
    render(<PieceworkReportPage />)

    await waitFor(() => expect(screen.getByTestId('piecework-error')).toBeInTheDocument())
    expect(screen.getByTestId('piecework-retry')).toBeInTheDocument()
  })
  it('按部位下钻：渲染部位行 + 金额/数量（真值源 §4 下钻链）', async () => {
    render(<PieceworkReportPage />)
    await waitFor(() => expect(mockGetPieceworkSummary).toHaveBeenCalled())

    await userEvent.click(screen.getByTestId('piecework-tab-position'))

    const panel = screen.getByTestId('piecework-by-position')
    expect(within(panel).getByText('布艺遮光帘A 米白')).toBeInTheDocument()
    expect(within(panel).getByText('¥83.45')).toBeInTheDocument()
    expect(within(panel).getByText('纱帘B 本白')).toBeInTheDocument()
    expect(within(panel).getByText('¥40.00')).toBeInTheDocument()
  })

  it('按套下钻：渲染订单行（order_item_id）行 + 金额/数量', async () => {
    render(<PieceworkReportPage />)
    await waitFor(() => expect(mockGetPieceworkSummary).toHaveBeenCalled())

    await userEvent.click(screen.getByTestId('piecework-tab-set'))

    const panel = screen.getByTestId('piecework-by-set')
    expect(within(panel).getByText('item-A')).toBeInTheDocument()
    expect(within(panel).getByText('item-B')).toBeInTheDocument()
  })

  it('下钻红证：缺 per_position / per_set ⇒ 该档显式「无数据」，不崩不静默', async () => {
    // 老后端（未带下钻维度）：人/工序两档**有数据**（否则整页走空态、根本没有 tab），
    // 但 per_position / per_set 缺席 ⇒ 下钻两档应为空态而不是抛错。
    mockGetPieceworkSummary.mockResolvedValue(
      ok({
        period: '2026-09',
        total: 80,
        per_worker: [{ worker_name: '张三', amount: 80, qty: 200 }],
        per_operation: [{ operation: '韩褶-布', amount: 80, qty: 200 }],
      }),
    )
    render(<PieceworkReportPage />)
    await waitFor(() => expect(mockGetPieceworkSummary).toHaveBeenCalled())

    await userEvent.click(screen.getByTestId('piecework-tab-position'))
    expect(within(screen.getByTestId('piecework-by-position')).getByText('无数据')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('piecework-tab-set'))
    expect(within(screen.getByTestId('piecework-by-set')).getByText('无数据')).toBeInTheDocument()
  })

})

/**
 * 未定价显式可见（issue #4696，P1）—— **计件报表页**的红证。
 *
 * 缺陷原形：只有未定价报工的期间里 `total`/`per_worker`/`per_operation` 全空 ⇒
 * 页面渲染「该期间暂无计件数据」，把「干了活但没定价、一分钱没有」彻底藏起来。
 */
describe('计件报表页 未定价可见（issue #4696）', () => {
  it('🔴 只有未定价报工 ⇒ **不得**渲染空态，必须显示未定价 + 定价入口', async () => {
    mockGetPieceworkSummary.mockResolvedValue(
      ok({
        period: '2026-09',
        total: 0,
        per_worker: [],
        per_operation: [],
        per_position: [],
        per_set: [],
        unpriced: {
          qty: 5,
          operations: [{ operation: '配料', logical_name: '配料', position: '布料', qty: 5 }],
          hint: '以下工序未定价',
        },
      }),
    )
    render(<PieceworkReportPage />)
    await waitFor(() => expect(mockGetPieceworkSummary).toHaveBeenCalled())

    expect(screen.queryByTestId('piecework-empty')).not.toBeInTheDocument()
    expect(screen.getByTestId('piecework-unpriced')).toBeInTheDocument()
    expect(screen.getByTestId('piecework-unpriced-0')).toHaveTextContent('未定价')
    expect(screen.getByTestId('piecework-unpriced-pricing-link')).toHaveAttribute(
      'href',
      '/production/routings',
    )
  })
})

/**
 * 默认期间 = **本地月**（issue #4772 红证）—— 页面 `currentPeriod()` 原为 UTC 月。
 *
 * 缺陷：`new Date().toISOString().slice(0, 7)` 取的是 **UTC** 月 ⇒ 在 UTC+8 下每月 1 日
 * 00:00~08:00（CST）这 8 小时里，用户本地已是新月份、页面却默认查**上一个月**（报表空/少）。
 *
 * 判据形态（**把「CST 的 8 小时窗口」在测试内复现 ⇒ CI 与开发机**同一条判据、都有判别力**）：
 * ① 本 describe 用 `vi.stubEnv('TZ', 'Asia/Shanghai')` 把**进程本地时区**钉成 UTC+8
 *    （实测有效：stub 后 `new Date('…+08:00').getMonth()` 按 +0800 计算）——
 *    否则 CI runner（**UTC**）上「UTC 月 == 本地月」⇒ 缺陷复现不出来（改前也会绿 = **无判别力**）。
 * ② 固定时刻取**显式 `+08:00` 偏移**（`2026-10-01T00:30:00+08:00` ⇒ 绝对时刻
 *    `2026-09-30T16:30:00Z`）= CST 月首 00:30、UTC 仍是上月末 16:30 ⇒ **缺陷窗口正中**。
 * ③ 期望值 = **同一冻结时刻的本地月**（`expectedPeriod(冻结时刻)`），不是硬编码的 `'2026-10'`：
 *    与页面 `currentPeriod()` 同源派生 ⇒ 页面若回退成 UTC 月，两者立刻不等（改前实测：
 *    期望 `2026-10` / 实际 `2026-09`）。
 * ④ **判别力护栏**：断言是**具体月份字符串**（`expect.any(String)` / `/\d{4}-\d{2}/` 这类恒真形态
 *    **不用**）。
 *
 * 红证（实测，`TZ=UTC` 环境 + `origin/main` 的 UTC 月实现）：
 * ```
 * × 月首 00:30（CST）⇒ period = 该时刻的**本地月**，不是 UTC 月
 *   expected "spy" to be called with arguments: [ { period: '2026-10', …(1) } ]
 * -     "period": "2026-10",
 * +     "period": "2026-09",
 * Tests  1 failed | 15 passed (16)
 * ```
 */
describe('默认期间 = 本地月（issue #4772 红证）', () => {
  beforeEach(() => {
    // 把「跑测机器的本地时区」钉成 UTC+8：CI（UTC）与开发机（CST）跑出**同一个**判定。
    vi.stubEnv('TZ', 'Asia/Shanghai')
  })

  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('🔴 月首 00:30（CST）⇒ period = 该时刻的**本地月**，不是 UTC 月', async () => {
    // `+08:00` 显式偏移 = 绝对时刻，与机器时区无关（CI 跑 UTC 也是同一个 instant）
    const instant = new Date('2026-10-01T00:30:00+08:00')
    vi.setSystemTime(instant)
    render(<PieceworkReportPage />)

    const localMonth = expectedPeriod(instant)
    // 本地时区已被 stub 成 UTC+8 ⇒ 本地月 = 2026-10、UTC 月 = 2026-09
    // ⇒ 改前（页面用 UTC 月）此断言必红（实测见上方 describe 注释）
    expect(localMonth).toBe('2026-10')
    await waitFor(() => expect(mockGetPieceworkSummary).toHaveBeenCalled())
    expect(mockGetPieceworkSummary).toHaveBeenCalledWith({ period: localMonth, worker_name: undefined })
    expect(screen.getByTestId('piecework-period')).toHaveValue(localMonth)
  })

  it('月首边界两侧：CST 08:59 与 09:01 都取**本地月**（页面不得跟着 UTC 翻月）', async () => {
    for (const cst of ['2026-10-01T08:59:00+08:00', '2026-10-01T09:01:00+08:00']) {
      const instant = new Date(cst)
      vi.setSystemTime(instant)
      mockGetPieceworkSummary.mockClear()
      const { unmount } = render(<PieceworkReportPage />)
      await waitFor(() => expect(mockGetPieceworkSummary).toHaveBeenCalled())
      expect(mockGetPieceworkSummary).toHaveBeenCalledWith({ period: expectedPeriod(instant), worker_name: undefined })
      unmount()
    }
  })

  it('默认期间与**本地**月一致（跑测机器任意时区都成立）', async () => {
    // 无偏移的本地时刻构造 ⇒ 本地月在任何时区都是 2026-10（CST 与 UTC 同结论）；
    // 若页面用 UTC 月，CST（UTC+8）下这条也红 —— 与上一条互为独立证据面。
    const instant = new Date('2026-10-05T00:30:00')
    vi.setSystemTime(instant)
    render(<PieceworkReportPage />)

    await waitFor(() => expect(mockGetPieceworkSummary).toHaveBeenCalled())
    const localMonth = expectedPeriod(instant)
    expect(localMonth).toBe('2026-10')
    expect(mockGetPieceworkSummary).toHaveBeenCalledWith({ period: localMonth, worker_name: undefined })
  })
})
