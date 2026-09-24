// case_ids: PR-093, PR-094, PR-095, PR-096
//
// PR-093~096（issue #5159）：省料看板页的**可执行判据**（`admin-web` 组件面）。
//
// ## 本文件的判别性做法（为什么桩数据是"不自洽"的）
//
// 🔴 **米数 / 占比 / 金额一律原样渲染服务端值**（要求「看板汇总 == Σ 逐单」逐值相等）。
// 所以桩数据**故意不自洽**：
//   · `savedGroups[].savedMeters = 77` 而 `cohorts[purchase].savedMeters = 12.4`（不是它的和）；
//   · `total.savedMeters = 99`（也不是任何人的和）。
// ⇒ 前端一旦"顺手"求和/求差/重算，两个数就对不上，断言立刻红（判据不会被自己的文案喂绿）。
//
// 🔴 **空数据不冒充 0**（判据 4）：第二组用例把占比与采购米数都置 `null` ⇒ 卡片必须显示
// 「无数据」，**且不得出现 `0.0%` / `0 米`**（0 会被读成「没有浪费」）。
//
// 🔴 **存量单列**（判据 2）：`opening` 有**自己的一张卡**，占比 50.0% 与「切换后」的 0.0%
// 是两个数；两组混算会得到 25.0% ⇒ 任一混淆写法都会让某条断言红。
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
import type { SavingBoard, SavingTrend } from '@/types'

const ok = (data: unknown) => ({ data: { data } })

const TREND: SavingTrend = {
  granularity: 'month',
  timezone: 'Asia/Shanghai',
  points: [
    {
      period: '2026-08',
      purchasedMeters: null, // 该月只有存量导入 ⇒ ② 无数据（不是 0 米）
      openingMeters: 35,
      consumedMeters: 2,
      outputAreaM2: 0, // 分母 0 ⇒ 单位产出读不出
      metersPerM2: null,
      outputLines: 0,
    },
    {
      period: '2026-09',
      purchasedMeters: 15,
      openingMeters: null,
      consumedMeters: 4.8,
      outputAreaM2: 5.8,
      metersPerM2: 0.8276,
      outputLines: 3,
    },
  ],
  purchasedTotalMeters: 15,
  consumedTotalMeters: 6.8,
  openingTotalMeters: 35,
}

let bucketSeq = 0
const BUCKET_KEYS = ['le_0_2', 'b0_2_0_5', 'b0_5_1', 'gt_1'] as const
const bucket = (label: string, count: number, share: number | null) => ({
  // 与真实服务端同形：恒四档、key 唯一（`le_0_2`/`b0_2_0_5`/`b0_5_1`/`gt_1`）
  key: BUCKET_KEYS[bucketSeq++ % 4],
  label,
  batchCount: count,
  share,
  remainingMeters: null,
})

const BOARD: SavingBoard = {
  granularity: 'month',
  timezone: 'Asia/Shanghai',
  cohorts: [
    {
      cohort: 'purchase',
      cohortLabel: '切换后（采购入库）',
      opening: false,
      batchCount: 2,
      le0_2Count: 0,
      le0_2Share: 0,
      remainingMeters: 9.4,
      savedMeters: 12.4,
      savedAmount: 103.76,
      lineCount: 6,
      unknownCostLines: 1,
      buckets: [bucket('≤0.2 米', 0, 0), bucket('0.2~0.5 米', 0, 0), bucket('0.5~1 米', 0, 0), bucket('>1 米', 2, 1)],
    },
    {
      cohort: 'opening',
      cohortLabel: '存量导入（切换前历史包袱）',
      opening: true,
      batchCount: 2,
      le0_2Count: 1,
      le0_2Share: 0.5,
      remainingMeters: 29.2,
      savedMeters: 5.8,
      savedAmount: 33.8,
      lineCount: 2,
      unknownCostLines: 1,
      buckets: [bucket('≤0.2 米', 1, 0.5), bucket('0.2~0.5 米', 0, 0), bucket('0.5~1 米', 0, 0), bucket('>1 米', 1, 0.5)],
    },
    {
      cohort: 'unknown',
      cohortLabel: '来源未知',
      opening: false,
      batchCount: 0,
      le0_2Count: 0,
      le0_2Share: null, // 无数据（**不是 0**）
      remainingMeters: null,
      savedMeters: null,
      savedAmount: null,
      lineCount: 0,
      unknownCostLines: 0,
      buckets: [bucket('≤0.2 米', 0, null), bucket('0.2~0.5 米', 0, null), bucket('0.5~1 米', 0, null), bucket('>1 米', 0, null)],
    },
  ],
  batchGroups: [
    {
      period: '2026-09',
      cohort: 'purchase',
      cohortLabel: '切换后（采购入库）',
      opening: false,
      materialKey: 'p1|SKU-A',
      productId: 'p1',
      skuCode: 'SKU-A',
      batchCount: 2,
      le0_2Count: 0,
      le0_2Share: 0,
      remainingMeters: 9.4,
      buckets: [bucket('≤0.2 米', 0, 0)],
    },
    {
      period: '2026-08',
      cohort: 'opening',
      cohortLabel: '存量导入（切换前历史包袱）',
      opening: true,
      materialKey: 'p1|SKU-A',
      productId: 'p1',
      skuCode: 'SKU-A',
      batchCount: 2,
      le0_2Count: 1,
      le0_2Share: 0.5,
      remainingMeters: 29.2,
      buckets: [bucket('≤0.2 米', 1, 0.5)],
    },
  ],
  // 🔴 故意与 cohorts 的和（18.2）不等 ⇒ 前端任何"顺手求和"都会红
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
}

const EMPTY_BOARD: SavingBoard = {
  ...BOARD,
  cohorts: BOARD.cohorts.map((c) =>
    c.cohort === 'purchase'
      ? { ...c, batchCount: 0, le0_2Count: 0, le0_2Share: null, savedMeters: null, savedAmount: null, remainingMeters: null }
      : c
  ),
  batchGroups: [],
  savedGroups: [],
}

const EMPTY_TREND: SavingTrend = {
  granularity: 'month',
  timezone: 'Asia/Shanghai',
  points: [],
  purchasedTotalMeters: null,
  consumedTotalMeters: null,
  openingTotalMeters: null,
}

const renderPage = async () => {
  render(<SavingBoardPage />)
  // 等首屏两次请求都落地（`Promise.all`）—— 用 findBy* 等待，不用定长 sleep。
  // ⚠️ 不能用指标卡当等待信号：`metricCards` **恒两条**、不等数据（`board = null` 时就已渲染，
  // 只是值显示「无数据」）⇒ 它在「读面未落地 / 已落地」两态下**都成立**，等它等于没等
  // （issue #5300 的「等 A 断言 B」，全文件共用这一处等待）⇒ 改等**只可能来自 board 读面**的来源组卡。
  // 两条腿由同一个 `Promise.all` 落地（同一批 setState）⇒ 等它就同时覆盖了 trend 腿。
  await screen.findByTestId('saving-cohort-purchase')
}

describe('#5159 省料看板页', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockBoard.mockResolvedValue(ok(BOARD))
    mockTrend.mockResolvedValue(ok(TREND))
  })

  it('🔴 判据3：两条指标**都在**页面上，且写明「单看①会被排料误导」', async () => {
    await renderPage()
    const first = screen.getByTestId('saving-metric-le-0-2')
    const second = screen.getByTestId('saving-metric-purchased')

    // 指标①：剩余 ≤0.2 米的批次占比（档位文案来自服务端 label）
    expect(within(first).getByText(/剩余/)).toBeTruthy()
    expect(within(first).getByText('≤0.2 米', { exact: false })).toBeTruthy()
    expect(within(first).getByText('0.0%')).toBeTruthy()
    // 指标②：入库/采购总米数
    expect(within(second).getByText('入库/采购总米数')).toBeTruthy()
    expect(within(second).getByText('15 米')).toBeTruthy()

    const note = screen.getByTestId('saving-metric-coexistence-note')
    expect(note.textContent).toContain('两条指标必须并用')
    expect(note.textContent).toContain('排料')
    expect(note.textContent).toContain('误导')
    expect(note.textContent).toContain('剩得更多')
    expect(note.textContent).toContain('显示成变差')
  })

  it('🔴 判据4：无数据 ⇒ 显示「无数据」，**不得**渲染成 0', async () => {
    mockBoard.mockResolvedValue(ok(EMPTY_BOARD))
    mockTrend.mockResolvedValue(ok(EMPTY_TREND))
    await renderPage()

    const first = screen.getByTestId('saving-metric-le-0-2')
    const second = screen.getByTestId('saving-metric-purchased')
    expect(within(first).getByText('无数据')).toBeTruthy()
    expect(within(second).getByText('无数据')).toBeTruthy()
    // 红证：实现若把 null 回落成 0 ⇒ 这里会出现「0.0%」/「0 米」⇒ 两条断言之一必红
    expect(within(first).queryByText('0.0%')).toBeNull()
    expect(within(second).queryByText('0 米')).toBeNull()

    // 「来源未知」组的占比无数据（计数 0 照实显示 —— 计数为 0 是事实）
    // ⚠️ 组卡来自 board 读面（`cohorts` 为空时整段不渲染）⇒ 对**异步渲染面**用同步 `getBy*`
    // 会命中不了还没渲染的节点（issue #5300 实测红：`Unable to find
    // [data-testid="saving-cohort-unknown"]`）。等**目标本身**出现，断言语义一字未改。
    const unknown = await screen.findByTestId('saving-cohort-unknown')
    expect(within(unknown).getByTestId('saving-cohort-unknown-le-share').textContent).toBe('无数据')
    expect(within(unknown).getByTestId('saving-cohort-unknown-batch-count').textContent).toBe('0')

    // L2 / L1 / L3 三段空数据都渲染「无数据」，不是空表也不是 0
    expect(screen.getByTestId('saving-batch-groups-empty').textContent).toBe('无数据')
    expect(screen.getByTestId('saving-saved-groups-empty').textContent).toBe('无数据')
    expect(screen.getByTestId('saving-trend-empty').textContent).toBe('无数据')
  })

  it('🔴 判据2：存量导入**独立成卡**（50.0%），不混进「切换后」（0.0%）', async () => {
    await renderPage()
    const purchase = screen.getByTestId('saving-cohort-purchase')
    const opening = screen.getByTestId('saving-cohort-opening')

    expect(within(purchase).getByTestId('saving-cohort-purchase-le-share').textContent).toBe('0.0%')
    expect(within(opening).getByTestId('saving-cohort-opening-le-share').textContent).toBe('50.0%')
    // 「存量导入」必须打得出来（用户看得见这是历史包袱）
    expect(opening.textContent).toContain('存量导入')
    expect(opening.textContent).toContain('单列')
    // 红证：把两组混算 ⇒ 占比会变成 25.0%（1/4），与上面两条断言都不符
    expect(within(purchase).getByTestId('saving-cohort-purchase-le-share').textContent).not.toBe('25.0%')
    expect(within(purchase).getByTestId('saving-cohort-purchase-batch-count').textContent).toBe('2')
    expect(within(opening).getByTestId('saving-cohort-opening-batch-count').textContent).toBe('2')

    // L2 分组表里两组是**两行**（不是一行加总）
    expect(screen.getByTestId('saving-batch-group-purchase-2026-09')).toBeTruthy()
    expect(screen.getByTestId('saving-batch-group-opening-2026-08')).toBeTruthy()
  })

  it('🔴 判据1：米数/金额**原样渲染服务端值**（桩数据不自洽 ⇒ 任何前端重算必红）', async () => {
    await renderPage()
    const group = screen.getByTestId('saving-saved-group-purchase-2026-09')
    // 分组腿：77 米 / 88.88 元（服务端给的，不是 12.4 / 103.76）
    expect(group.textContent).toContain('77 米')
    expect(group.textContent).toContain('88.88 元')
    // 来源组卡：12.4 米 / 103.76 元 —— 与分组腿是两个数，页面**两个都照实显示**
    const purchase = screen.getByTestId('saving-cohort-purchase')
    expect(purchase.textContent).toContain('12.4 米')
    expect(purchase.textContent).toContain('103.76 元')
    // 未记均价的行数必须说出来（否则「读不出」会被读成「只省了这么点」）
    expect(purchase.textContent).toContain('1 行未记批次均价')
  })

  it('🔴 判据3(L3)：② 不含存量导入；分母 0 ⇒ 单位产出显「无数据」', async () => {
    await renderPage()
    const aug = screen.getByTestId('saving-trend-2026-08')
    // 该月只有存量导入 ⇒ ② 无数据（**不是 0 米**），存量导入单列 35 米
    expect(aug.textContent).toContain('无数据')
    expect(aug.textContent).toContain('35 米')
    expect(aug.textContent).not.toContain('0 米')
    // 分母 0 ⇒ 单位产出消耗读不出
    expect(aug.textContent).toContain('无数据')

    const sep = screen.getByTestId('saving-trend-2026-09')
    expect(sep.textContent).toContain('15 米')
    expect(sep.textContent).toContain('0.8276')
    // 时区口径必须看得见（否则跨月边界上是两个数）
    expect(screen.getByTestId('saving-trend').textContent).toContain('Asia/Shanghai')
  })

  it('粒度切换 ⇒ 请求带上 service 认得的取值（未知值由服务端 400 拒绝，前端不静默回落）', async () => {
    await renderPage()
    expect(mockBoard).toHaveBeenCalledWith({ granularity: 'month' })
    expect(mockTrend).toHaveBeenCalledWith({ granularity: 'month' })
  })
})
