// case_ids: UI-092
//
// 省料看板**首屏形态**的判据（issue #6459，用户三张截图逐字：
// 「省料看板为什么一定要加上切换后（采购入库）这种概念，让新用户如何理解」
// 「这么多废话文字留在页面上只会干扰用户」
// 「这个功能只需要用数据和规则说清楚我们是如何省下多少布料，节省了多少成本即可」）。
//
// ## 三条判据，各在自己的形态上会红
//
// ① 🔴 **内部口径词不上屏**：`切换后` / `存量导入` / `来源未知`（服务端 `cohortLabel` 的三个取值）
//    一个都不许出现在整页渲染文本里。红证 = 把「来源组对照」那张三行表写回去 ⇒ 当场红。
// ② 🔴 **废话不上屏**：门道卡 / 因果链 / 术语词典 / 逐卡 hint 的典型措辞一律不得出现
//    （`为什么` / `两个数` / `误导` / `剩得更多` / `门道` / `术语` / `词典` / `两条指标`）。
//    红证 = 把 `coexistenceNote()` 那一句加回页面 ⇒ 当场红。
// ③ 🔴 **旧形态退场是结构性的**：两张指标卡（`saving-metric-le-0-2` / `saving-metric-purchased`）、
//    来源组表（`saving-cohort-*`）、布剩在哪（`saving-batch-groups`）、单位产出趋势（`saving-trend`）
//    的 testid 在整页里**一个都找不到** —— 不是「藏起来」，是不存在。
//    红证 = 把任一块 JSX 加回页面 ⇒ 对应断言红。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'

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
  { key: 'le_0_2', label: '≤0.2 米', batchCount: 1, share: 0.25, remainingMeters: null },
  { key: 'b0_2_0_5', label: '0.2~0.5 米', batchCount: 0, share: 0, remainingMeters: null },
  { key: 'b0_5_1', label: '0.5~1 米', batchCount: 0, share: 0, remainingMeters: null },
  { key: 'gt_1', label: '>1 米', batchCount: 3, share: 0.75, remainingMeters: null },
]

const BOARD: SavingBoard = {
  granularity: 'month',
  timezone: 'Asia/Shanghai',
  cohorts: [
    {
      cohort: 'purchase',
      cohortLabel: '切换后（采购入库）',
      opening: false,
      batchCount: 4,
      le0_2Count: 1,
      le0_2Share: 0.25,
      remainingMeters: 12540.3,
      savedMeters: 12.4,
      savedAmount: 103.76,
      lineCount: 6,
      unknownCostLines: 1,
      buckets: BUCKETS,
    },
  ],
  batchGroups: [],
  savedGroups: [
    {
      period: '2026-09',
      cohort: 'purchase',
      cohortLabel: '切换后（采购入库）',
      opening: false,
      materialKey: 'p1|SKU-A',
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
  batchTrend: [{ period: '2026-09', batchCount: 4, le0_2Count: 1, le0_2Share: 0.25 }],
}

const renderPage = async () => {
  render(<SavingBoardPage />)
  await screen.findByTestId('saving-metric-saved-meters')
}

/** 旧形态的 testid（一个都不该再存在）—— 红证 = 把任一块 JSX 加回页面 */
const RETIRED_TESTIDS = [
  'saving-metric-le-0-2',
  'saving-metric-purchased',
  'saving-metric-coexistence-note',
  'saving-causal-chain',
  'saving-terms',
  'saving-headline',
  'saving-cohorts',
  'saving-cohort-purchase',
  'saving-batch-groups',
  'saving-trend',
]

/** 废话的典型措辞（门道卡 / 因果链 / 术语词典 / 逐卡 hint 的原话片段） */
const RETIRED_PHRASES = [
  '为什么',
  '两个数',
  '误导',
  '剩得更多',
  '门道',
  '术语',
  '词典',
  '两条指标',
  '不相加',
  '来源组',
]

/** 服务端分组标签（`SavingMetricViews.cohortLabel` 的三个取值）—— 内部口径，不上屏 */
const COHORT_JARGON = ['切换后', '存量导入', '来源未知']

beforeEach(() => {
  vi.clearAllMocks()
  mockBoard.mockResolvedValue(ok(BOARD))
  mockTrend.mockResolvedValue(ok({}))
})

describe('#6459 省料看板首屏：只讲「省了多少布 / 多少钱」+ 几乎用完的批数趋势', () => {
  it('🔴 内部口径词一个都不上屏（切换后 / 存量导入 / 来源未知）', async () => {
    await renderPage()
    const text = document.body.textContent ?? ''

    for (const word of COHORT_JARGON) {
      // 红证：把「来源组对照」三行表（`c.cohortLabel`）写回页面 ⇒ 这三个词立刻出现在文本里
      expect(text, `内部口径词「${word}」上屏了 —— 新用户读不懂（issue #6459）`).not.toContain(word)
    }
    // 服务端的 cohortLabel 就摆在夹具里（页面拿到了却**不渲染**，这才是判据的判别力所在）
    expect(BOARD.cohorts[0].cohortLabel).toContain('切换后')
  })

  it('🔴 废话一句都不留（门道卡 / 因果链 / 术语词典 / 逐卡 hint 的措辞）', async () => {
    await renderPage()
    const text = document.body.textContent ?? ''

    for (const phrase of RETIRED_PHRASES) {
      // 红证：把 `coexistenceNote()` 那一句加回页面 ⇒ 「两条指标 / 误导 / 剩得更多」三处同时命中
      expect(text, `删掉的说明文案又回到页面上了：「${phrase}」（issue #6459）`).not.toContain(phrase)
    }
  })

  it('🔴 旧形态**结构性退场**：两张指标卡 / 来源组表 / 布剩在哪 / 单位产出趋势一个都找不到', async () => {
    await renderPage()

    for (const testId of RETIRED_TESTIDS) {
      expect(screen.queryByTestId(testId), `旧形态残留：${testId}`).toBeNull()
    }
  })

  it('🔴 页面只回答两个问题：省了多少布 / 省了多少钱（各一张卡）', async () => {
    await renderPage()
    const meters = screen.getByTestId('saving-metric-saved-meters')
    const amount = screen.getByTestId('saving-metric-saved-amount')

    expect(within(meters).getByText('55 米')).toBeTruthy()
    expect(within(amount).getByText('555 元')).toBeTruthy()
    // 页面上**只有**这两张结论卡（多一张 = 又把别的概念搬回首屏）
    expect(document.querySelectorAll('[data-testid^="saving-metric-"]')).toHaveLength(2)
  })

  it('🔴 规则说清楚了（页头一句）且点明区块是「什么数」（去掉代号 ≠ 去掉信息）', async () => {
    await renderPage()
    const rule = screen.getByTestId('saving-rule').textContent ?? ''

    expect(rule).toContain('该领')
    expect(rule).toContain('排料实际领走')
    expect(rule).toContain('进价')
    expect(screen.getByTestId('saving-batch-trend').textContent).toContain('几乎用完的布')
    expect(screen.getByTestId('saving-saved-groups-details').textContent).toContain('省料明细')
    // 内部度量分层代号（L1/L2/L3）一律不上屏（UI-057 的元守卫在整页面上判）
    expect(document.body.textContent ?? '').not.toMatch(/L[123]/)
  })

  it('🔴 口径与边界收进折叠区（首屏之外），里面说清「无数据 ≠ 0 / 金额是下界 / 老库存不算」', async () => {
    await renderPage()
    const foot = screen.getByTestId('saving-footnotes')

    expect((foot as HTMLDetailsElement).open).toBe(false)
    expect(foot.textContent).toContain('无数据')
    expect(foot.textContent).toContain('下界')
    expect(foot.textContent).toContain('老库存不算')
  })

  it('🔴 两条腿的口径漂移面已消失：页面只调一条读面', async () => {
    await renderPage()
    expect(mockBoard).toHaveBeenCalledTimes(1)
    expect(mockTrend).not.toHaveBeenCalled()
  })

  it('🔴 向后兼容：后端未部署（无 comparison / batchTrend）⇒ 不崩、不渲染环比块、趋势显示无数据', async () => {
    mockBoard.mockResolvedValue(ok({ ...BOARD, comparison: undefined, batchTrend: undefined }))
    await renderPage()

    expect(screen.getByTestId('saving-metric-saved-meters')).toBeTruthy()
    expect(screen.queryByTestId('saving-comparison-saved-meters')).toBeNull()
    // 退回服务端累计值（不是 0、也不是崩）
    expect(screen.getByTestId('saving-metric-saved-meters').textContent).toContain('99 米')
    expect(screen.getByTestId('saving-batch-trend-empty').textContent).toBe('无数据')
  })
})
