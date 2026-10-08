// case_ids: PR-093, PR-094, PR-095, PR-096
//
// 省料看板页的**可执行判据**（`admin-web` 组件面；首屏形态 = issue #6459 用户裁定）。
//
// ## 本文件的判别性做法（为什么桩数据是"不自洽"的）
//
// 🔴 **米数 / 占比 / 金额一律原样渲染服务端值**（要求「看板汇总 == Σ 逐单」逐值相等）。
// 所以桩数据**故意不自洽** —— 三个「省料米数」互不相等：
//   · `savedGroups[].savedMeters = 77`（逐单分组腿）
//   · `comparison.savedMeters.current = 55`（服务端「本期」值 = 首屏大数字）
//   · `total.savedMeters = 99`（服务端累计腿 = 明细合计行 / 「累计」副行）
// ⇒ 前端一旦「顺手」求和/求差/换用另一个数，断言立刻红。
//
// 🔴 **空数据不冒充 0**（判据 4）：第二组夹具把合计与趋势都置空 ⇒ 必须显示「无数据」，
// **且不得出现 `0 米` / `0.0%`**（0 会被读成「没有浪费」）。
//
// 🔴 **一条读面**（issue #6459）：页面只调 `saving-board`；旧版的两条腿（board + trend）
// 有一类「只给一条腿加筛选 ⇒ 两处口径分属两个域」的漂移面 ⇒ 现在**结构性消失**，本文件把它钉住。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, within, waitFor } from '@testing-library/react'

const mockBoard = vi.fn()
const mockTrend = vi.fn()

vi.mock('@/lib/api', () => ({
  savingBoardApi: {
    board: (...a: unknown[]) => mockBoard(...a),
    trend: (...a: unknown[]) => mockTrend(...a),
  },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn(), dismiss: vi.fn() },
}))

import SavingBoardPage from '@/app/(dashboard)/production/saving-board/page'
import type { SavingBoard } from '@/types'

const ok = (data: unknown) => ({ data: { data } })

const BUCKETS = [
  { key: 'le_0_2', label: '≤0.2 米', batchCount: 0, share: 0, remainingMeters: null },
  { key: 'b0_2_0_5', label: '0.2~0.5 米', batchCount: 0, share: 0, remainingMeters: null },
  { key: 'b0_5_1', label: '0.5~1 米', batchCount: 0, share: 0, remainingMeters: null },
  { key: 'gt_1', label: '>1 米', batchCount: 15, share: 1, remainingMeters: null },
]

const cohort = (over: Record<string, unknown> = {}) => ({
  cohort: 'purchase',
  cohortLabel: '切换后（采购入库）',
  opening: false,
  batchCount: 15,
  le0_2Count: 0,
  le0_2Share: 0,
  remainingMeters: 12540.3,
  savedMeters: 12.4,
  savedAmount: 103.76,
  lineCount: 6,
  unknownCostLines: 1,
  buckets: BUCKETS,
  ...over,
})

const BOARD: SavingBoard = {
  granularity: 'month',
  timezone: 'Asia/Shanghai',
  cohorts: [cohort(), cohort({ cohort: 'opening', opening: true, batchCount: 0, le0_2Share: null })],
  batchGroups: [],
  savedGroups: [
    {
      period: '2026-09',
      cohort: 'purchase',
      cohortLabel: '切换后（采购入库）',
      opening: false,
      materialKey: 'p1|SKU-A',
      // 🔴 展示名 = 服务端下发的人话（issue #6535）；**故意**与机器键不同形 ——
      //    前端若把它换成 materialKey / 自己拼串，下面「物料列」那条断言当场红
      materialLabel: '遮光帘A × 2.8米',
      productId: 'p1',
      skuCode: 'SKU-A',
      formulaMeters: 10,
      plannedMeters: 4.6,
      savedMeters: 77,
      savedAmount: 88.88,
      lineCount: 6,
      unknownCostLines: 0,
    },
  ],
  // 🔴 服务端累计腿：99 / 999 —— 与逐单 77、本期 55 **都不等**
  total: {
    formulaMeters: 100,
    plannedMeters: 1,
    savedMeters: 99,
    savedAmount: 999,
    lineCount: 8,
    unknownCostLines: 2,
    batchCount: 4,
    le0_2Count: 1,
    le0_2Share: 0.25,
  },
  comparison: {
    savedMeters: {
      period: '2026-10',
      previousPeriod: '2026-09',
      current: 55,
      previous: 120,
      verdict: 'worse',
    },
    savedAmount: {
      period: '2026-10',
      previousPeriod: '2026-09',
      current: 555,
      previous: 1500,
      verdict: 'worse',
    },
    le0_2Share: null,
  },
  // 🔴 「几乎用完」1 / 3 与「当期收进」4 / 6 是两组不同的服务端值 —— 混用即红
  batchTrend: [
    { period: '2026-08', batchCount: 4, le0_2Count: 1, le0_2Share: 0.25 },
    { period: '2026-09', batchCount: 6, le0_2Count: 3, le0_2Share: 0.5 },
  ],
}

const EMPTY_BOARD: SavingBoard = {
  granularity: 'month',
  timezone: 'Asia/Shanghai',
  cohorts: [cohort({ batchCount: 0, le0_2Share: null, savedMeters: null, savedAmount: null, remainingMeters: null })],
  batchGroups: [],
  savedGroups: [],
  total: {
    formulaMeters: null,
    plannedMeters: null,
    savedMeters: null,
    savedAmount: null,
    lineCount: 0,
    unknownCostLines: 0,
    batchCount: 0,
    le0_2Count: 0,
    le0_2Share: null,
  },
  comparison: null,
  batchTrend: [],
}

const renderPage = async () => {
  render(<SavingBoardPage />)
  // 等**只可能来自读面**的节点落地（规则句是静态的，不能当等待信号）
  await screen.findByTestId('saving-metric-saved-meters')
  await waitFor(() => expect(mockBoard).toHaveBeenCalled())
}

beforeEach(() => {
  vi.clearAllMocks()
  mockBoard.mockResolvedValue(ok(BOARD))
  mockTrend.mockResolvedValue(ok({}))
})

describe('#6459 省料看板页（结论数字 + 趋势 + 明细）', () => {
  it('🔴 首屏大数字 = 服务端「本期」值（55 米 / 555 元），不是逐单求和（77）', async () => {
    await renderPage()
    const meters = screen.getByTestId('saving-metric-saved-meters')
    const amount = screen.getByTestId('saving-metric-saved-amount')

    expect(within(meters).getByText('55 米')).toBeTruthy()
    expect(within(amount).getByText('555 元')).toBeTruthy()
    expect(meters.textContent).toContain('省下的布 · 2026-10')
    // 「累计」副行 = 服务端 total（也是原值，不是任何求和）
    expect(meters.textContent).toContain('累计 99 米')
    expect(amount.textContent).toContain('累计 999 元')
    // 红证：任何「顺手」把分组腿求和（77 / 88.88）拿来做大数字的实现都在这里红
    expect(within(meters).queryByText('77 米')).toBeNull()
    expect(within(amount).queryByText('88.88 元')).toBeNull()
  })

  it('🔴 环比：好坏词来自服务端 verdict（worse ⇒ 变差），期间也来自服务端', async () => {
    await renderPage()
    const el = screen.getByTestId('saving-comparison-saved-meters')

    expect(el.textContent).toContain('2026-09')
    expect(el.textContent).toContain('2026-10')
    expect(el.textContent).toContain('变差')

    // 单变量对照：只把 verdict 改成 better ⇒ 页面必须改口（写死「变好了」的前端过不了）
    mockBoard.mockResolvedValue(
      ok({
        ...BOARD,
        comparison: {
          ...BOARD.comparison!,
          savedMeters: { ...BOARD.comparison!.savedMeters, verdict: 'better' },
        },
      })
    )
    render(<SavingBoardPage />)
    await waitFor(() =>
      expect(
        screen
          .getAllByTestId('saving-comparison-saved-meters')
          .some((n) => (n.textContent ?? '').includes('变好'))
      ).toBe(true)
    )
  })

  it('🔴 环比：本期还没过完（verdict=partial）⇒ 说「先不算」，不冒充结论', async () => {
    mockBoard.mockResolvedValue(
      ok({
        ...BOARD,
        comparison: {
          ...BOARD.comparison!,
          savedMeters: { ...BOARD.comparison!.savedMeters, verdict: 'partial' },
        },
      })
    )
    await renderPage()
    const el = screen.getByTestId('saving-comparison-saved-meters')

    expect(el.textContent).toContain('还没过完')
    expect(el.textContent).not.toContain('变好')
    expect(el.textContent).not.toContain('变差')
  })

  it('🔴 趋势表：几乎用完的布（1 / 3 批）与当期收进的布（4 / 6 批）是两组服务端值，占比原样', async () => {
    await renderPage()
    const cellsOf = (testId: string) =>
      within(screen.getByTestId(testId))
        .getAllByRole('cell')
        .map((c) => c.textContent)

    // 逐格断言：把「几乎用完」渲染成当期全部批数（口径松掉）⇒ 第 2 格由 1 变 4 ⇒ 当场红
    expect(cellsOf('saving-batch-trend-2026-08')).toEqual(['2026-08', '1', '4', '25.0%'])
    expect(cellsOf('saving-batch-trend-2026-09')).toEqual(['2026-09', '3', '6', '50.0%'])
    // 档位文案来自服务端 `buckets[].label`（写死「0.2」的另一条判据在 lib 测试里）
    expect(screen.getByTestId('saving-batch-trend').textContent).toContain('≤0.2 米')
  })

  it('🔴 逐单明细原样渲染 + 合计行 = 服务端 total（99 米 / 999 元），不是逐行求和', async () => {
    await renderPage()
    const row = screen.getByTestId('saving-saved-group-2026-09-p1|SKU-A')
    expect(row.textContent).toContain('77 米')
    expect(row.textContent).toContain('88.88 元')

    const total = screen.getByTestId('saving-saved-groups-total')
    expect(total.textContent).toContain('99 米')
    expect(total.textContent).toContain('999')
    expect(total.textContent).not.toContain('88.88')
    // 未记均价的行数必须说出来（金额是**下界**）
    expect(total.textContent).toContain('2 行未记批次均价')
  })

  it('🔴 #6535：「物料」列 = 服务端展示名（人话），内部键 `productId|skuCode` 不上屏（负控：契约与读数逐值不变）', async () => {
    await renderPage()

    // 负控 1：定位串仍是机器键 `materialKey`（`data-testid` 逐字不变 —— 只改展示、不动契约）
    const row = screen.getByTestId('saving-saved-group-2026-09-p1|SKU-A')

    // 🔴 展示：列文本 = 服务端 `materialLabel`，**不含**内部键、不含竖线（§31 P3：不摆内部标识）
    expect(row.textContent).toContain('遮光帘A × 2.8米')
    expect(row.textContent).not.toContain('p1|SKU-A')
    expect(row.textContent).not.toContain('|')
    // 反面形态（UUID 形态的商品键）：夹具形状即错 ⇒ 这条断言是**判别性**的，不是自说自话
    expect(row.textContent).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/)

    // 负控 2：同一行的金额 / 米数读数**逐值不变**（只改展示那一格）
    expect(row.textContent).toContain('77 米')
    expect(row.textContent).toContain('88.88 元')
    expect(within(row).getAllByRole('cell').map((c) => c.textContent)).toEqual([
      '2026-09',
      '遮光帘A × 2.8米',
      '10 米',
      '4.6 米',
      '77 米',
      '88.88 元',
    ])
  })

  it('🔴 明细与口径区**默认收起**（首屏不堆东西；issue #6459）', async () => {
    await renderPage()
    expect((screen.getByTestId('saving-saved-groups-details') as HTMLDetailsElement).open).toBe(false)
    expect((screen.getByTestId('saving-footnotes') as HTMLDetailsElement).open).toBe(false)
  })

  it('🔴 判据4：无数据 ⇒ 显示「无数据」，**不得**渲染成 0', async () => {
    mockBoard.mockResolvedValue(ok(EMPTY_BOARD))
    await renderPage()

    const meters = screen.getByTestId('saving-metric-saved-meters')
    const amount = screen.getByTestId('saving-metric-saved-amount')
    expect(within(meters).getByText('无数据')).toBeTruthy()
    expect(within(amount).getByText('无数据 元')).toBeTruthy()
    // 红证：实现若把 null 回落成 0 ⇒ 这里会出现「0 米」/「0 元」⇒ 断言必红
    expect(meters.textContent).not.toContain('0 米')
    expect(amount.textContent).not.toContain('0 元')
    // 趋势空 ⇒ 「无数据」；明细空 ⇒ 「无数据」（不是空表、也不是 0）
    expect(screen.getByTestId('saving-batch-trend-empty').textContent).toBe('无数据')
    expect(screen.getByTestId('saving-saved-groups-empty').textContent).toBe('无数据')
    // 后端未部署（无 comparison / batchTrend）时同样不崩、不渲染环比块
    expect(screen.queryByTestId('saving-comparison-saved-meters')).toBeNull()
  })

  it('🔴 判据2：趋势只吃服务端 batchTrend —— 存量/来源未知的批次不进序列（页面不自己分来源）', async () => {
    await renderPage()
    // 页面渲染的期数 == 服务端给的期数（多出来的一行只可能来自前端自己聚合 batchGroups）
    const rows = screen.getAllByTestId(/^saving-batch-trend-2026-/)
    expect(rows).toHaveLength(2)
    // 承接服务端口径的文本说明在折叠区（不在首屏刷存在感）
    expect(screen.getByTestId('saving-footnotes').textContent).toContain('老库存不算')
  })

  it('🔴 一条读面：页面只调 saving-board（不再有「两腿不同参」的口径漂移面）', async () => {
    await renderPage()
    expect(mockBoard).toHaveBeenCalledTimes(1)
    expect(mockBoard).toHaveBeenCalledWith({ granularity: 'month' })
    expect(mockTrend).not.toHaveBeenCalled()
  })
})
