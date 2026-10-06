// case_ids: PR-093, UI-090
//
// 省料看板**重设计**的判据（issue #6430）：把「省料故事」讲清楚 —— 结论先行、门道可视、环比来自服务端、
// 异常优先 + 渐进披露、合计行原样渲染服务端 total。
//
// ## 本文件的判别性做法（与 `SavingBoard.test.tsx` 同源：桩数据**故意不自洽**）
//
// 🔴 **前端零算术、零好坏判定**。夹具里三个「省料米数」是三个**互不相等**的数：
//   · `savedGroups[].savedMeters = 77`（逐单分组腿）
//   · `cohorts` 五个来源组合计 = 12.4 + 5.8 = 18.2（**不是**任何一处显示的合计）
//   · `total.savedMeters = 99`（服务端合计腿 —— 页面上的「合计」与结论条必须是它）
//   ⇒ 前端一旦"顺手"求和（77 / 18.2）或求差，断言立刻红。
//
// 🔴 **好坏词来自服务端 verdict**：同一份夹具，`verdict` 从 `worse` 改成 `better` ⇒ 页面文案必须跟着变
//   （写死"变好了"的前端过不了这条）；`le0_2Share.verdict = null` ⇒ 该行**只给两期数值、不给好坏词**
//   （有意不给：占比方向会被排料省料反向污染，见 #5144）。
//
// 🔴 **环比的期间来自服务端**：页面不得自己算"上个月"（期间由 `MetricDelta.period` / `previousPeriod` 给）。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, within, fireEvent, waitFor } from '@testing-library/react'

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

let bucketSeq = 0
const BUCKET_KEYS = ['le_0_2', 'b0_2_0_5', 'b0_5_1', 'gt_1'] as const
const bucket = (label: string, count: number, share: number | null) => ({
  key: BUCKET_KEYS[bucketSeq++ % 4],
  label,
  batchCount: count,
  share,
  remainingMeters: null,
})

const BUCKETS = () => [
  bucket('≤0.2 米', 0, 0),
  bucket('0.2~0.5 米', 0, 0),
  bucket('0.5~1 米', 0, 0),
  bucket('>1 米', 15, 1),
]

/** 12 个批次分组，**余量乱序**（最大的不是第一行）⇒ 「异常优先」排序可判 */
const manyBatchGroups = () =>
  Array.from({ length: 12 }, (_, i) => ({
    period: '2026-09',
    cohort: 'purchase',
    cohortLabel: '切换后（采购入库）',
    opening: false,
    materialKey: `p${i}|SKU-${i}`,
    productId: `p${i}`,
    skuCode: `SKU-${i}`,
    batchCount: 1,
    le0_2Count: 0,
    le0_2Share: 0,
    // SKU-0 余量最大（9000）却排在最后（同 cohort+period，键只由 skuCode 区分）
    // ⇒ 不排序时它不会出现在「前 8 行」里；SKU-1 余量最小 ⇒ 排序后仍在第 12 位
    remainingMeters: i === 0 ? 9000 : i * 10,
    buckets: BUCKETS(),
  }))

const BOARD: SavingBoard = {
  granularity: 'month',
  timezone: 'Asia/Shanghai',
  cohorts: [
    {
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
      buckets: BUCKETS(),
    },
    {
      cohort: 'opening',
      cohortLabel: '存量导入（切换前历史包袱）',
      opening: true,
      batchCount: 5,
      le0_2Count: 0,
      le0_2Share: 0,
      remainingMeters: 640,
      savedMeters: 5.8,
      savedAmount: 33.8,
      lineCount: 2,
      unknownCostLines: 0,
      buckets: BUCKETS(),
    },
    {
      cohort: 'unknown',
      cohortLabel: '来源未知',
      opening: false,
      batchCount: 0,
      le0_2Count: 0,
      le0_2Share: null,
      remainingMeters: null,
      savedMeters: null,
      savedAmount: null,
      lineCount: 0,
      unknownCostLines: 0,
      buckets: BUCKETS(),
    },
  ],
  batchGroups: manyBatchGroups(),
  savedGroups: [
    {
      period: '2026-10',
      cohort: 'purchase',
      cohortLabel: '切换后（采购入库）',
      opening: false,
      materialKey: 'p1|SKU-A',
      productId: 'p1',
      skuCode: 'SKU-A',
      formulaMeters: 261.9,
      plannedMeters: 254.6,
      savedMeters: 77,
      savedAmount: 88.88,
      lineCount: 6,
      unknownCostLines: 0,
    },
  ],
  // 🔴 服务端合计腿：99 / 999 —— 与逐单 77、来源组和 18.2 **都不等**
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
      current: 99,
      previous: 120,
      verdict: 'worse',
    },
    savedAmount: {
      period: '2026-10',
      previousPeriod: '2026-09',
      current: 999,
      previous: 1500,
      verdict: 'worse',
    },
    // 🔴 有意不给好坏 —— 只给两期数值
    le0_2Share: {
      period: '2026-09',
      previousPeriod: '2026-08',
      current: 0,
      previous: 0.5,
      verdict: null,
    },
  },
}

const TREND: SavingTrend = {
  granularity: 'month',
  timezone: 'Asia/Shanghai',
  points: [
    {
      period: '2026-09',
      purchasedMeters: 12540.3,
      openingMeters: 640,
      consumedMeters: 254.6,
      outputAreaM2: 130.5,
      metersPerM2: 1.951,
      outputLines: 4,
    },
  ],
  purchasedTotalMeters: 12540.3,
  consumedTotalMeters: 254.6,
  openingTotalMeters: 640,
  comparison: {
    purchasedMeters: {
      period: '2026-09',
      previousPeriod: '2026-08',
      current: 12540.3,
      previous: 14000,
      verdict: 'better',
    },
    metersPerM2: {
      period: '2026-09',
      previousPeriod: '2026-08',
      current: 1.951,
      previous: 2.1,
      verdict: 'better',
    },
  },
}

const renderPage = async () => {
  render(<SavingBoardPage />)
  // 等**只可能来自读面**的节点（结论条）落地，不用定长 sleep（同 SavingBoard.test.tsx 的等待纪律）
  await screen.findByTestId('saving-headline')
}

beforeEach(() => {
  vi.clearAllMocks()
  mockBoard.mockResolvedValue(ok(BOARD))
  mockTrend.mockResolvedValue(ok(TREND))
})

describe('#6430 省料看板重设计：把故事讲清楚', () => {
  it('🔴 结论条：只用服务端原值（99 米），不是逐单求和（77）也不是来源组求和（18.2）', async () => {
    await renderPage()
    const line = screen.getByTestId('saving-headline')

    expect(line.textContent).toContain('省料')
    expect(line.textContent).toContain('99 米') // total.savedMeters（服务端合计腿）
    expect(line.textContent).not.toContain('18.2') // 来源组求和形态 ⇒ 红
    expect(line.textContent).not.toContain('77 米') // 逐单求和形态 ⇒ 红
    // 「布还剩多少」也在结论条里（新用户第一个问题）
    expect(line.textContent).toContain('12540.3 米')
    expect(line.textContent).toContain('15 批')
  })

  it('🔴 第三张结论卡「省了多少」：渲染服务端 total，不重算', async () => {
    await renderPage()
    const card = screen.getByTestId('saving-metric-saved')

    expect(card.textContent).toContain('99 米')
    expect(card.textContent).toContain('999 元')
    // 未记均价的行数必须说出来（金额是**下界**）
    expect(card.textContent).toContain('2 行未记批次均价')
  })

  it('🔴 门道卡：把因果链讲出来（排料省 ⇒ 剩得多 ⇒ 只盯一个数会看反）', async () => {
    await renderPage()
    const chain = screen.getByTestId('saving-causal-chain')
    const note = screen.getByTestId('saving-metric-coexistence-note')

    expect(chain.textContent).toContain('排料')
    expect(chain.textContent).toContain('剩得更多')
    expect(chain.textContent).toContain('两个数')
    // 既有判据的措辞一条不放宽
    expect(note.textContent).toContain('两条指标必须并用')
    expect(note.textContent).toContain('误导')
    expect(note.textContent).toContain('显示成变差')
  })

  it('🔴 术语词典：新用户看不懂的四个词必须有解释，且不出现内部代号', async () => {
    await renderPage()
    const terms = screen.getByTestId('saving-terms')

    for (const term of ['公式米数', '排料米数', '省料米数', '省料金额', '来源组', '批次余量']) {
      expect(terms.textContent).toContain(term)
    }
    // 「占比按**批数**算，不是按米数」—— 最容易看反的一条
    expect(terms.textContent).toContain('批数')
    // 内部代号一律不上屏（UI-057 的元守卫在整页面上判；这里对词典再加一道）
    expect(terms.textContent).not.toMatch(/L[123]/)
  })

  it('🔴 环比：好坏词来自服务端 verdict（改成 better ⇒ 文案跟着变）', async () => {
    await renderPage()
    const el = screen.getByTestId('saving-comparison-saved')

    expect(el.textContent).toContain('2026-10')
    expect(el.textContent).toContain('2026-09')
    expect(el.textContent).toContain('变差') // verdict=worse ⇒ 服务端词

    // 单变量对照：只把 verdict 改成 better ⇒ 页面必须改口
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
    // ⚠️ 必须 waitFor **条件**（不是 waitFor 元素出现）：第一次渲染的节点此刻已在 DOM 里，
    //    `findAllByTestId` 会立刻返回旧节点 ⇒ 断言跑在第二次请求落地**之前**（本用例首版就踩了这个竞态）。
    await waitFor(() =>
      expect(
        screen
          .getAllByTestId('saving-comparison-saved')
          .some((n) => (n.textContent ?? '').includes('变好'))
      ).toBe(true)
    )
  })

  it('🔴 占比环比：verdict 为 null ⇒ 只给两期数值，**不给好坏词**（有意不给，#5144）', async () => {
    await renderPage()
    const el = screen.getByTestId('saving-comparison-le-share')

    expect(el.textContent).toContain('2026-09')
    expect(el.textContent).toContain('2026-08')
    expect(el.textContent).toContain('50.0%') // 上期（服务端值）
    expect(el.textContent).not.toContain('变好')
    expect(el.textContent).not.toContain('变差')
  })

  it('🔴 采购环比在趋势区：verdict=better ⇒ 说「变好」，且期间来自服务端', async () => {
    await renderPage()
    const el = screen.getByTestId('saving-comparison-purchased')
    expect(el.textContent).toContain('2026-09')
    expect(el.textContent).toContain('2026-08')
    expect(el.textContent).toContain('变好')
  })

  it('🔴 异常优先 + 渐进披露：12 行只先给 8 行，余量最大的排第一；展开后全给', async () => {
    await renderPage()
    // 余量最大的物料（SKU-0）必须出现在首屏（不排序时它在最后，会被前 8 行切掉 ⇒ 红）
    expect(screen.getByTestId('saving-batch-group-purchase-2026-09-SKU-0')).toBeTruthy()
    // 余量最小的 SKU-1 排第 12 位 ⇒ 默认不渲染
    expect(screen.queryByTestId('saving-batch-group-purchase-2026-09-SKU-1')).toBeNull()

    fireEvent.click(screen.getByTestId('saving-batch-groups-toggle'))
    expect(screen.getByTestId('saving-batch-group-purchase-2026-09-SKU-1')).toBeTruthy()
  })

  it('🔴 逐单省料「合计」行 = 服务端 total（99 米 / 999 元），不是逐行求和（77 / 88.88）', async () => {
    await renderPage()
    const total = screen.getByTestId('saving-saved-groups-total')

    expect(total.textContent).toContain('99 米')
    expect(total.textContent).toContain('999')
    expect(total.textContent).not.toContain('88.88')
    // 逐单行照旧原样渲染（判据 1 一字不放宽）
    expect(screen.getByTestId('saving-saved-group-purchase-2026-10').textContent).toContain('77 米')
  })

  it('🔴 两张表的「时间」不是一回事：页面上必须写明（收货月 vs 消耗月）', async () => {
    await renderPage()
    const note = screen.getByTestId('saving-period-axis-note')
    expect(note.textContent).toContain('收货')
    expect(note.textContent).toContain('用掉')
  })

  it('🔴 趋势口径警示：产出面积跨品类不可比 ⇒ 只跟自己的历史比', async () => {
    await renderPage()
    const caveat = screen.getByTestId('saving-trend-caveat')
    expect(caveat.textContent).toContain('不可比')
    expect(caveat.textContent).toContain('自己的历史')
  })

  it('🔴 口径与边界折叠区：无数据 ≠ 0 / 金额是下界 / 存量单列 都在里面', async () => {
    await renderPage()
    const foot = screen.getByTestId('saving-footnotes')
    expect(foot.textContent).toContain('无数据')
    expect(foot.textContent).toContain('下界')
    expect(foot.textContent).toContain('单列')
  })

  it('🔴 两腿同参（防「只给一条腿加筛选」的口径漂移）：board 与 trend 收到的 params 深相等', async () => {
    await renderPage()
    expect(mockBoard).toHaveBeenCalledTimes(1)
    expect(mockTrend).toHaveBeenCalledTimes(1)
    expect(mockBoard.mock.calls[0][0]).toEqual(mockTrend.mock.calls[0][0])
  })

  it('🔴 新用户 5 问：页面文本面能答出这五问（缺任一条即红）', async () => {
    await renderPage()
    const text = document.body.textContent ?? ''

    // ① 这个月省了多少？
    expect(text).toContain('省了')
    expect(text).toContain('99 米')
    // ② 布还剩在哪、还剩多少？
    expect(text).toContain('余量合计')
    expect(text).toContain('12540.3 米')
    // ③ 比上期好还是坏？（词来自服务端）
    expect(text).toContain('变差')
    // ④ 为什么两个指标要一起看？
    expect(text).toContain('剩得更多')
    // ⑤ 存量导入为什么单列？
    expect(text).toContain('存量导入')
    expect(text).toContain('单列')
  })

  it('🔴 向后兼容：后端未部署（无 comparison）⇒ 页面不崩、不出现环比块', async () => {
    mockBoard.mockResolvedValue(ok({ ...BOARD, comparison: undefined }))
    mockTrend.mockResolvedValue(ok({ ...TREND, comparison: undefined }))
    await renderPage()

    expect(screen.getByTestId('saving-headline')).toBeTruthy()
    expect(screen.queryByTestId('saving-comparison-saved')).toBeNull()
    expect(screen.queryByTestId('saving-comparison-le-share')).toBeNull()
    expect(screen.queryByTestId('saving-comparison-purchased')).toBeNull()
  })

  it('🔴 来源组仍是三行单列（判据 2 不放宽）：存量导入有自己的行且带「单列」', async () => {
    await renderPage()
    const opening = screen.getByTestId('saving-cohort-opening')
    expect(opening.textContent).toContain('存量导入')
    expect(opening.textContent).toContain('单列')
    expect(within(opening).getByTestId('saving-cohort-opening-batch-count').textContent).toBe('5')
  })
})
