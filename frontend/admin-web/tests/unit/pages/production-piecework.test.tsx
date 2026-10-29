// case_ids: PG-021, CU-010, PG-073
// 追加（issue #6669 第 7 条）：计件金额千分位口径与财务域同源。
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
// 结算单（issue #5653）：列表 / 生成 / 作废 —— 与报表**同一页**的两块读面
const mockGetPieceworkSettlements = vi.fn()
const mockGeneratePieceworkSettlement = vi.fn()
const mockVoidPieceworkSettlement = vi.fn()

vi.mock('@/lib/api', () => ({
  productionApi: {
    getPieceworkSummary: (...args: unknown[]) => mockGetPieceworkSummary(...args),
    getPieceworkSettlements: (...args: unknown[]) => mockGetPieceworkSettlements(...args),
    generatePieceworkSettlement: (...args: unknown[]) => mockGeneratePieceworkSettlement(...args),
    voidPieceworkSettlement: (...args: unknown[]) => mockVoidPieceworkSettlement(...args),
  },
}))

import { productionApi } from '@/lib/api'
import { readFileSync } from 'node:fs'

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
  // 套维（#4725 用户裁定「一樘窗 = 一套」）：键 = **套号**（V92 `set_no`），不是订单行
  per_set: [
    { set_no: 'JG-20260918-6914-001', amount: 83.45, qty: 211 },
    { set_no: 'JG-20260918-6914-002', amount: 40, qty: 100 },
  ],
}

const ok = (data: unknown) => ({ data: { success: true, data } })

// ── 「读面延迟」注入夹具（issue #5088，红证 + 类级探针用）────────────────────
// 默认 0 ⇒ 与 `mockResolvedValue` 等价（同一条已兑现的微任务链，行为一字不变）。
// `ADMIN_WEB_READ_LAG_MS=300 npx vitest run <本文件>` ⇒ 把「请求**已发出**」与「读面**已落到界面**」
// 之间的窗口**确定性地**拉到 300ms ⇒ 任何「等 A（接口被调用）断言 B（界面内容）」的等待方式必红。
//
// 为什么需要它：本 job 的 flake 全是**同一机制**——`waitFor(() => expect(接口).toHaveBeenCalled())`
// 只证明请求发出，**不证明 setState 已提交**（React 的并发调度把提交排在宏任务上），
// 紧随其后的同步 `getBy*` 于是撞进「表单/面板已挂、数据未落」的窗口。CI 实测（run 36005743156，
// PR 5409 = **纯文档 PR**，与本文件任何改动无关）：`Unable to find an element by:
// [data-testid="piecework-unpriced"]`，DOM 里刷新按钮还挂着 `animate-spin`（=仍在 loading）。
// 靠负载碰运气的红，这里用注入延迟变成**必红**。
const READ_LAG_MS = Number(process.env.ADMIN_WEB_READ_LAG_MS ?? 0)
const laggedOk = (data: unknown): Promise<{ data: { success: boolean; data: unknown } }> =>
  READ_LAG_MS > 0
    ? new Promise((resolve) => setTimeout(() => resolve(ok(data)), READ_LAG_MS))
    : Promise.resolve(ok(data))

describe('计件工资报表页 /production/piecework', () => {
  beforeEach(() => {
    vi.setSystemTime(FROZEN_NOW) // 每条用例都回到同一冻结时刻
    mockGetPieceworkSummary.mockReset().mockImplementation(() => laggedOk(REPORT))
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

  /**
   * 🔴 issue #6669 第 7 条（**页面级**，不是只测工具函数）：计件金额与财务域**同口径** ——
   * 千分位 + 固定两位小数。修前这里是 `¥${n.toFixed(2)}` ⇒ 六位数印成 `¥123456.78`（无千分位），
   * 而财务域印 `¥123,456.78` ⇒ **同一条用例在两个域给出两种形态**。
   *
   * 红证：把 `formatMoney` 改回 `¥${Number(v ?? 0).toFixed(2)}` ⇒ 本条红
   * （实测读数 `expected '¥123456.78' to contain '¥123,456.78'`）。
   */
  it('金额带千分位（与财务域同口径）：合计 123456.78 ⇒ ¥123,456.78', async () => {
    mockGetPieceworkSummary.mockImplementation(() =>
      laggedOk({
        ...REPORT,
        total: 123456.78,
        per_worker: [{ worker_name: '张三', amount: 123456.78, qty: 200 }],
        per_operation: [{ operation: '韩褶', logical_name: '韩褶 · 布帘', position: '布帘', amount: 98765.4, qty: 100 }],
      }),
    )
    render(<PieceworkReportPage />)
    await waitFor(() =>
      expect(screen.getByTestId('piecework-report-total')).toHaveTextContent('¥123,456.78'),
    )
    expect(within(screen.getByTestId('piecework-by-worker')).getByTestId('worker-row-张三')).toHaveTextContent(
      '¥123,456.78',
    )
  })

  it('切「按工序」档：展示工序聚合（工序名/金额/数量）', async () => {    render(<PieceworkReportPage />)
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
    mockGetPieceworkSummary.mockImplementation(() =>
      laggedOk({
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
    mockGetPieceworkSummary.mockImplementation(() =>
      laggedOk({ period: '2026-08', total: 0, per_worker: [], per_operation: [] }),
    )
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
    // 等「读面**已落到界面**」（`piecework-by-worker` 只在 `!loading` 时渲染），
    // 不是等「请求已发出」——后者在 loading 态就成立，紧随其后的同步 `getBy*` 于是撞进
    // 「面板已挂、数据未落」的窗口（issue #5088 的 flake 机制；本文件另有注入延迟夹具）。
    await waitFor(() => expect(screen.getByTestId('piecework-by-worker')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('piecework-tab-position'))

    const panel = screen.getByTestId('piecework-by-position')
    expect(within(panel).getByText('布艺遮光帘A 米白')).toBeInTheDocument()
    expect(within(panel).getByText('¥83.45')).toBeInTheDocument()
    expect(within(panel).getByText('纱帘B 本白')).toBeInTheDocument()
    expect(within(panel).getByText('¥40.00')).toBeInTheDocument()
  })

  it('按套下钻：渲染**套（樘窗组）**行 + 金额/数量（#4725：套 = 樘窗，不是订单行）', async () => {
    render(<PieceworkReportPage />)
    // 同上：等读面落地（issue #5088），不是等请求发出。
    await waitFor(() => expect(screen.getByTestId('piecework-by-worker')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('piecework-tab-set'))

    const panel = screen.getByTestId('piecework-by-set')
    // 表头不得再把一樘窗称作「订单行」（旧口径文字钉）
    expect(within(panel).getByText('套')).toBeInTheDocument()
    expect(within(panel).queryByText('套（订单行）')).not.toBeInTheDocument()
    expect(within(panel).getByText('JG-20260918-6914-001')).toBeInTheDocument()
    expect(within(panel).getByText('JG-20260918-6914-002')).toBeInTheDocument()
    // 金额仍是**真实读数**（反 placeholder）
    expect(within(panel).getByText('¥83.45')).toBeInTheDocument()
    expect(within(panel).getByText('¥40.00')).toBeInTheDocument()
  })

  it('下钻红证：缺 per_position / per_set ⇒ 该档显式「无数据」，不崩不静默', async () => {
    // 老后端（未带下钻维度）：人/工序两档**有数据**（否则整页走空态、根本没有 tab），
    // 但 per_position / per_set 缺席 ⇒ 下钻两档应为空态而不是抛错。
    mockGetPieceworkSummary.mockImplementation(() =>
      laggedOk({
        period: '2026-09',
        total: 80,
        per_worker: [{ worker_name: '张三', amount: 80, qty: 200 }],
        per_operation: [{ operation: '韩褶-布', amount: 80, qty: 200 }],
      }),
    )
    render(<PieceworkReportPage />)
    // 同上：等读面落地（issue #5088），不是等请求发出。
    await waitFor(() => expect(screen.getByTestId('piecework-by-worker')).toBeInTheDocument())

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
    mockGetPieceworkSummary.mockImplementation(() =>
      laggedOk({
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
    // 等「读面**已落到界面**」的**正向**信号（`piecework-unpriced` 只在 `!loading` 时渲染），
    // 不是等「请求已发出」——CI 实测红（run 36005743156）：只等调用的写法下，
    // 断言跑在 loading 态（DOM 里 `data-testid="piecework-loading"` 还在）⇒
    // `Unable to find an element by: [data-testid="piecework-unpriced"]`。
    // 断言内容一字未改：否定断言仍在 waitFor **之外**（塞进去会因元素瞬时不在而假绿）。
    await waitFor(() => expect(screen.getByTestId('piecework-unpriced')).toBeInTheDocument())

    expect(screen.queryByTestId('piecework-empty')).not.toBeInTheDocument()
    expect(screen.getByTestId('piecework-unpriced-0')).toHaveTextContent('未定价')
    expect(screen.getByTestId('piecework-unpriced-pricing-link')).toHaveAttribute(
      'href',
      // issue #7182：旧「工艺配置」页已下架 ⇒ 定价入口落到唯一写面（与按钮文案同源）
      '/settings?domain=operation-prices',
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

/**
 * 计件**结算单**（issue #5653）—— 端上入口的判据。
 *
 * 用户 2026-10-16 裁定 **A 快照式**：**生成即冻结**（没有改写金额的入口）、要改就
 * **作废 + 重开**（旧单留痕不删）、**同一期间同一工人只能有一张生效单**（重复生成是具名错误）、
 * **不与财务域耦合**（本轮**没有**发放 / 导出 / 编辑任何入口 —— ④ 是反向断言）。
 *
 * 四条判据都要求「会红」：
 * ① 生成后列表**真出现**该单，且金额**与报表那一行逐值一致**（不是「非空」）；
 * ② 作废后旧单**仍在列表**（状态 + 原因），且同期同工人**可再次生成**（新旧并存）；
 * ③ 重复生成的 409 在界面上是**那句人话**（逐字断言服务端原话，不是「有报错」）；
 * ④ 端上**没有**发放 / 导出 / 编辑入口（DOM 反向 + 消费面源码反向）。
 */
describe('计件结算单 /production/piecework（issue #5653）', () => {
  const PERIOD = expectedPeriod(FROZEN_NOW)

  const settlement = (over: Record<string, unknown> = {}) => ({
    id: 'st-1',
    period: PERIOD,
    worker_name: '张三',
    total_amount: 80,
    line_items: [{ operation: '精裁-布', qty: 200, amount: 80 }],
    generated_by: 'user-owner-001',
    generated_at: '2026-09-15T02:00:00Z',
    voided: false,
    voided_at: null,
    voided_by: null,
    void_reason: null,
    ...over,
  })

  const listOf = (items: Record<string, unknown>[]) => ({
    period: PERIOD,
    total: items.length,
    voided_count: items.filter((i) => i.voided).length,
    items,
  })

  beforeEach(() => {
    vi.setSystemTime(FROZEN_NOW)
    mockGetPieceworkSummary.mockReset().mockImplementation(() => laggedOk(REPORT))
    mockGetPieceworkSettlements.mockReset().mockImplementation(() => laggedOk(listOf([])))
    mockGeneratePieceworkSettlement.mockReset()
    mockVoidPieceworkSettlement.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('🔴 判据① 生成后列表真出现该单，且金额与**报表那一行逐值一致**', async () => {
    const created = settlement()
    mockGeneratePieceworkSettlement.mockResolvedValue(ok(created))
    render(<PieceworkReportPage />)
    // 等**读面已落界面**的正向信号（不是等「请求已发出」——见文件头 #5088 的坑）
    await waitFor(() => expect(screen.getByTestId('worker-row-张三')).toBeInTheDocument())
    // 两块的读面都要落地（结算单块有自己的加载态 ⇒ 不等它就是「用例跑完了、它的 setState 还没提交」）
    await waitFor(() => expect(screen.getByTestId('settlement-empty')).toBeInTheDocument())

    // 生成入口：可选工人 = **同一份报表读数**的按人行（选项上直接带报表金额 ⇒ 同源在界面上可核）
    await userEvent.click(screen.getByTestId('settlement-generate-open'))
    const select = screen.getByTestId('settlement-worker-select') as HTMLSelectElement
    expect(within(select).getByRole('option', { name: /张三 · ¥80\.00/ })).toBeInTheDocument()
    expect(within(select).getByRole('option', { name: /李红梅 · ¥43\.45/ })).toBeInTheDocument()

    await userEvent.selectOptions(select, '张三')
    mockGetPieceworkSettlements.mockImplementation(() => laggedOk(listOf([created])))
    await userEvent.click(screen.getByTestId('settlement-generate-confirm'))

    expect(mockGeneratePieceworkSettlement).toHaveBeenCalledWith({ period: PERIOD, worker_name: '张三' })
    await waitFor(() => expect(screen.getByTestId('settlement-row-st-1')).toBeInTheDocument())

    // **逐值一致**（不是「非空」）：结算单金额与报表同一工人那一行逐字相同
    const reportRow = screen.getByTestId('worker-row-张三')
    const settledRow = screen.getByTestId('settlement-row-st-1')
    expect(within(reportRow).getByText('¥80.00')).toBeInTheDocument()
    expect(within(settledRow).getByText('¥80.00')).toBeInTheDocument()
    expect(screen.getByTestId('settlement-amount-st-1')).toHaveTextContent('¥80.00')
    expect(screen.getByTestId('settlement-summary')).toHaveTextContent('本期 1 张生效 · 合计 ¥80.00')
  })

  it('🔴 判据② 作废后旧单仍在（状态 + 原因），且同期同工人可再次生成（新旧并存）', async () => {
    const active = settlement()
    const voided = settlement({
      voided: true,
      voided_at: '2026-09-15T02:30:00Z',
      voided_by: 'user-owner-001',
      void_reason: '单价录错，重新结算',
    })
    const reopened = settlement({ id: 'st-2', total_amount: 90 })
    mockGetPieceworkSettlements.mockImplementation(() => laggedOk(listOf([active])))
    mockVoidPieceworkSettlement.mockResolvedValue(ok(voided))
    render(<PieceworkReportPage />)
    await waitFor(() => expect(screen.getByTestId('settlement-row-st-1')).toBeInTheDocument())

    // 作废：必须填原因（留痕要答得出「为什么」）
    await userEvent.click(screen.getByTestId('settlement-void-open-st-1'))
    await userEvent.type(screen.getByTestId('settlement-void-reason-st-1'), '单价录错，重新结算')
    mockGetPieceworkSettlements.mockImplementation(() => laggedOk(listOf([voided])))
    await userEvent.click(screen.getByTestId('settlement-void-confirm-st-1'))

    expect(mockVoidPieceworkSettlement).toHaveBeenCalledWith('st-1', { reason: '单价录错，重新结算' })
    // 旧单**仍在列表**：状态与原因都看得见（作废不是删除）
    await waitFor(() => expect(screen.getByTestId('settlement-status-st-1')).toHaveTextContent('已作废'))
    expect(screen.getByTestId('settlement-status-st-1')).toHaveTextContent('单价录错，重新结算')

    // 同期间同工人**可以再生成一张** ⇒ 新旧并存（期间唯一性只约束**生效**单）
    mockGetPieceworkSettlements.mockImplementation(() => laggedOk(listOf([reopened, voided])))
    mockGeneratePieceworkSettlement.mockResolvedValue(ok(reopened))
    await userEvent.click(screen.getByTestId('settlement-generate-open'))
    await userEvent.selectOptions(screen.getByTestId('settlement-worker-select'), '张三')
    await userEvent.click(screen.getByTestId('settlement-generate-confirm'))

    await waitFor(() => expect(screen.getByTestId('settlement-row-st-2')).toBeInTheDocument())
    expect(screen.getByTestId('settlement-row-st-1')).toBeInTheDocument() // 旧单没被顶掉
    expect(screen.getByTestId('settlement-status-st-2')).toHaveTextContent('生效中')
    expect(screen.getByTestId('settlement-status-st-1')).toHaveTextContent('已作废')
    expect(mockGeneratePieceworkSettlement).toHaveBeenCalledTimes(1)
  })

  it('🔴 判据③ 重复生成（409）⇒ 界面给出**那句人话**（逐字断言，不是「有报错」）', async () => {
    // 逐字 = 后端 `PieceworkSettlementService.exists(...)` 的原话（界面**原样透出**，不吞理由、
    // 也不在前端抄写第二份措辞 ⇒ 两处不会各自漂移）
    const sentence =
      `「张三」在 ${PERIOD} 已有一张生效的结算单（结算单生成即冻结、不可改）。` +
      '如需按最新报工重开：先作废那张单（填写原因），再重新生成。'
    mockGetPieceworkSettlements.mockImplementation(() => laggedOk(listOf([settlement()])))
    mockGeneratePieceworkSettlement.mockRejectedValue({
      isAxiosError: true,
      response: { data: { error: { code: 'PIECEWORK_SETTLEMENT_EXISTS', message: sentence } } },
    })
    render(<PieceworkReportPage />)
    await waitFor(() => expect(screen.getByTestId('settlement-row-st-1')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('settlement-generate-open'))
    await userEvent.selectOptions(screen.getByTestId('settlement-worker-select'), '张三')
    await userEvent.click(screen.getByTestId('settlement-generate-confirm'))

    await waitFor(() => expect(screen.getByTestId('settlement-notice')).toBeInTheDocument())
    expect(screen.getByTestId('settlement-notice')).toHaveTextContent('已有一张生效的结算单')
    expect(screen.getByTestId('settlement-notice')).toHaveTextContent('先作废那张单（填写原因），再重新生成')
    expect(screen.getByTestId('settlement-notice')).toHaveTextContent(sentence)
    // 反向：**不是**泛化兜底句（「有报错」不算判据达标）
    expect(screen.getByTestId('settlement-notice')).not.toHaveTextContent('生成失败，请稍后重试')
  })

  it('🔴 判据④ 本轮**不做**发放 / 导出 / 编辑 —— 端上没有任何这类入口（反向断言）', async () => {
    mockGetPieceworkSettlements.mockImplementation(() => laggedOk(listOf([settlement()])))
    render(<PieceworkReportPage />)
    await waitFor(() => expect(screen.getByTestId('settlement-row-st-1')).toBeInTheDocument())

    // (a) DOM 反向：结算单区块里不得出现「发放 / 导出 / 批量 / 编辑 / 改金额」任何入口或字样
    const section = screen.getByTestId('settlement-section')
    expect(within(section).queryByText(/发放|导出|批量|编辑|改金额|修改金额/)).toBeNull()
    const labels = within(section)
      .getAllByRole('button')
      .map((b) => b.textContent ?? '')
    expect(labels.filter((x) => /发放|导出|批量|编辑|改金额/.test(x))).toEqual([])
    // 生效单只有「作废」一个动作（没有「编辑」—— 生成即冻结）
    expect(within(screen.getByTestId('settlement-row-st-1')).getByText('作废')).toBeInTheDocument()

    // (b) 消费面源码反向：`lib/api.ts` 里本域**没有**任何发放 / 导出方法（防越界交付）
    const apiSource = readFileSync('src/lib/api.ts', 'utf8')
    expect(apiSource).not.toMatch(/(disburse|payout|payOut|exportPiecework|PieceworkExport)/)
    expect(Object.keys(productionApi).sort()).toEqual(
      [
        'generatePieceworkSettlement',
        'getPieceworkSettlements',
        'getPieceworkSummary',
        'voidPieceworkSettlement',
      ].sort(),
    )
  })

  it('口径上屏：说明「生成即冻结 / 要改先作废重开 / 作废的单留在列表可查原因」+ 期间口径', async () => {
    render(<PieceworkReportPage />)
    await waitFor(() => expect(screen.getByTestId('settlement-empty')).toBeInTheDocument())
    const section = screen.getByTestId('settlement-section')
    expect(within(section).getByText(/生成后金额固定不变/)).toBeInTheDocument()
    expect(within(section).getByText(/作废的单会留在下面，能查到原因/)).toBeInTheDocument()
    expect(mockGetPieceworkSettlements).toHaveBeenCalledWith({ period: PERIOD, include_voided: true })
  })

  it('已作废默认折叠：折叠态**不渲染**那些行（常驻面不随历史条数增长），展开后才逐条出现', async () => {
    const active = settlement({ id: 'st-live' })
    const old1 = settlement({ id: 'st-old-1', voided: true, void_reason: '第一次录错' })
    const old2 = settlement({ id: 'st-old-2', voided: true, void_reason: '第二次录错' })
    mockGetPieceworkSettlements.mockImplementation(() => laggedOk(listOf([active, old1, old2])))
    render(<PieceworkReportPage />)
    await waitFor(() => expect(screen.getByTestId('settlement-row-st-live')).toBeInTheDocument())

    // 折叠态：DOM 里取不到（不是 CSS 隐藏 —— 这才是可判的读数）
    expect(screen.queryByTestId('settlement-row-st-old-1')).toBeNull()
    expect(screen.queryByTestId('settlement-row-st-old-2')).toBeNull()
    expect(screen.getByTestId('settlement-toggle-voided')).toHaveTextContent('已作废 2 张')
    expect(screen.getByTestId('settlement-summary')).toHaveTextContent('本期 1 张生效 · 合计 ¥80.00')

    await userEvent.click(screen.getByTestId('settlement-toggle-voided'))
    expect(screen.getByTestId('settlement-row-st-old-1')).toBeInTheDocument()
    expect(screen.getByTestId('settlement-row-st-old-2')).toBeInTheDocument()
    expect(screen.getByTestId('settlement-status-st-old-1')).toHaveTextContent('第一次录错')

    await userEvent.click(screen.getByTestId('settlement-toggle-voided'))
    expect(screen.queryByTestId('settlement-row-st-old-1')).toBeNull()
  })

  it('本期没有可结算的工人 ⇒ 生成入口不可点（不编造默认值、不落 0 元单）', async () => {
    mockGetPieceworkSummary.mockImplementation(() =>
      laggedOk({ period: PERIOD, total: 0, per_worker: [], per_operation: [] }),
    )
    render(<PieceworkReportPage />)
    await waitFor(() => expect(screen.getByTestId('settlement-no-worker')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByTestId('settlement-empty')).toBeInTheDocument())
    expect(screen.getByTestId('settlement-generate-open')).toBeDisabled()
    expect(screen.getByTestId('settlement-no-worker')).toHaveTextContent('未定价不等于 0 元')
  })

  // ── issue #8066（扫描器判据①「读失败被吞」收口）────────────────────────────
  // 改前：`load` 的 catch 只 `setData(null)` + 一句 notice ⇒ 摘要行落进「本期还没有结算单」，
  // 而结算单列表整块消失 = 把读失败画成「本期一张都没生成」。
  it('结算单读失败：常驻失败锚在场 + 不印「本期还没有结算单」+ 重试真的重发读请求', async () => {
    mockGetPieceworkSettlements
      .mockReset()
      .mockImplementationOnce(() => Promise.reject(new Error('settlements down')))
    render(<PieceworkReportPage />)

    const anchor = await screen.findByTestId('settlement-load-error')
    expect(anchor).toHaveTextContent('结算单读取失败')
    expect(anchor).toHaveTextContent('不是「本期还没有结算单」')
    expect(screen.queryByTestId('settlement-empty')).toBeNull()

    const before = mockGetPieceworkSettlements.mock.calls.length
    mockGetPieceworkSettlements.mockImplementation(() => laggedOk(listOf([])))
    await userEvent.click(screen.getByTestId('settlement-load-error-retry'))
    await waitFor(() => expect(screen.queryByTestId('settlement-load-error')).toBeNull())
    // 重试**真的**重发（不是只把失败态擦掉）
    expect(mockGetPieceworkSettlements.mock.calls.length).toBe(before + 1)
    // 重试成功后回到**真**空态：失败面没有把空态吃掉
    await waitFor(() => expect(screen.getByTestId('settlement-empty')).toBeInTheDocument())
  }, 20_000) // ⏱ issue #8066 用例：整例 20s（失败面等到底时 RTL 的 asyncUtilTimeout 是 5s，否则红成 Test timed out = 没跑到断言）
})
