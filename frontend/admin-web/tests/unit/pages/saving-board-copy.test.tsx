// @vitest-environment jsdom
// case_ids: PR-095, UI-057, UI-092
//
// 省料看板**商家可见文案**（issue #5565 的零内部代号 + issue #6459 的零内部口径词）。
//
// 背景：`L1/L2/L3` 是 issue #5159 的**内部度量分层**（实现文档词汇），页面曾把它们直接抄上屏 ⇒
// 用户逐字「L2和L3是什么概念，用户不懂，我也不懂」；而 `切换后（采购入库）` / `存量导入（切换前历史包袱）` /
// `来源未知` 是服务端的**分组标签**（`SavingMetricViews.cohortLabel`），也曾被整张表端到新用户面前 ⇒
// 用户逐字「让新用户如何理解」。两类是同一个病：**写码时对着 issue / 服务端字段写，把内部词汇带上了屏**。
//
// ⚠️ 断言口径 = **整页渲染文本**（`container.textContent`），不是 `findByText`：
//    「商家看到的字」本来就该按整页文本判，顺带免疫「同一句话在多处出现」的多命中陷阱
//    （`findBy*` 会一直重试到 `tests/setup.ts` 的 `asyncUtilTimeout`，报错是 Test timed out 而真因是匹配到多个）。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'

const mockBoard = vi.fn()

vi.mock('@/lib/api', () => ({
  savingBoardApi: { board: (...a: unknown[]) => mockBoard(...a) },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn(), dismiss: vi.fn() },
}))

import SavingBoardPage from '@/app/(dashboard)/production/saving-board/page'

/** 服务端四档（**假档位**：一旦页面写死「0.2」，下面那条判别性断言立刻红） */
const buckets = [
  { key: 'le_0_2', label: '≤9.9 米', batchCount: 1, share: 0.5, remainingMeters: null },
  { key: 'b0_2_0_5', label: '9.9~8.8 米', batchCount: 0, share: 0, remainingMeters: null },
  { key: 'b0_5_1', label: '8.8~7.7 米', batchCount: 0, share: 0, remainingMeters: null },
  { key: 'gt_1', label: '>7.7 米', batchCount: 1, share: 0.5, remainingMeters: null },
]

const board = {
  granularity: 'month',
  timezone: 'Asia/Shanghai',
  cohorts: [
    {
      cohort: 'purchase',
      cohortLabel: '切换后（采购入库）',
      opening: false,
      batchCount: 2,
      le0_2Count: 1,
      le0_2Share: 0.5,
      remainingMeters: 3,
      savedMeters: 1,
      savedAmount: 2,
      lineCount: 1,
      unknownCostLines: 0,
      buckets,
    },
  ],
  batchGroups: [],
  savedGroups: [],
  total: {
    formulaMeters: 3,
    plannedMeters: 2,
    savedMeters: 1,
    savedAmount: 2,
    lineCount: 1,
    unknownCostLines: 0,
    batchCount: 2,
    le0_2Count: 1,
    le0_2Share: 0.5,
  },
  batchTrend: [{ period: '2026-09', batchCount: 2, le0_2Count: 1, le0_2Share: 0.5 }],
}

beforeEach(() => {
  vi.clearAllMocks()
  mockBoard.mockResolvedValue({ data: { data: board } })
})

/** 渲染整页并把「商家看得见的字」取出来（等读面落地，避免断言跑在加载态上） */
async function renderPageText(): Promise<string> {
  const { container } = render(<SavingBoardPage />)
  await waitFor(() => expect(mockBoard).toHaveBeenCalled())
  await waitFor(() => expect(container.textContent ?? '').toContain('省料看板'))
  return container.textContent ?? ''
}

describe('省料看板商家可见文案（issue #5565 / #6459）', () => {
  it('🔴 渲染文本里不出现内部分层代号（L1/L2/L3 一律不得上屏）', async () => {
    const text = await renderPageText()

    // 严格口径：整页**一个都不要有** —— 代号在页面上没有任何解释，出现即等于内部编号外泄
    expect(text).not.toMatch(/L[123]/)
  })

  it('🔴 渲染文本里不出现服务端分组标签（切换后 / 存量导入 / 来源未知）', async () => {
    const text = await renderPageText()

    // 判别性：夹具**故意把 cohortLabel 设成内部口径**（页面拿到了，但不许渲染）
    expect(board.cohorts[0].cohortLabel).toContain('切换后')
    expect(text).not.toContain('切换后')
    expect(text).not.toContain('存量导入')
    expect(text).not.toContain('来源未知')
  })

  it('页头写明「省料怎么算」（用户要求：用数据和规则说清楚）', async () => {
    const text = await renderPageText()

    expect(text).toContain('按公式该领的米数')
    expect(text).toContain('排料实际领走的米数')
    expect(text).toContain('进价')
  })

  it('区块标题仍点明「这个数是什么」（去掉代号与术语 ≠ 去掉信息）', async () => {
    const text = await renderPageText()

    expect(text).toContain('几乎用完的布')
    expect(text).toContain('省料明细')
    expect(text).toContain('口径与边界')
  })

  it('🔴 档位文案来自**服务端 label**（写死「0.2」⇒ 红）', async () => {
    const text = await renderPageText()

    expect(text).toContain('≤9.9 米')
    expect(text).not.toContain('0.2 米')
  })
})
