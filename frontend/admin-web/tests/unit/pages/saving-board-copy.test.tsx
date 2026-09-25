// @vitest-environment jsdom
// case_ids: PR-095, UI-057
//
// 省料看板**商家可见文案**（issue #5565）：内部分层代号（L1/L2/L3）不得上屏，两件事要说人话。
//
// 背景：`L1/L2/L3` 是 issue #5159 的**内部度量分层**（L1 逐单落账 / L2 批次结构性 / L3 采购·财务口径），
// 属于实现文档的词汇；页面副标题与两个区块标题把它们直接抄了上去 ⇒ 用户逐字反馈
// 「L2和L3是什么概念，用户不懂，我也不懂」。
//
// ⚠️ 断言口径 = **整页渲染文本**（`container.textContent`），不是 `findByText`：
//    本页「批次余量分档」在**副标题与区块标题里各出现一次**，`getByText` 会命中多个元素 ⇒
//    `findBy*` 会一直重试到 `tests/setup.ts` 的 `asyncUtilTimeout`（5s，issue #4414）超时 ——
//    报错是「Test timed out」而真因是「匹配到多个」（本单实测踩过一次，如实记在这里）。
//    「商家看到的字」本来就该按**整页文本**判，顺带免疫这类多命中陷阱。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'

const mockBoard = vi.fn()
const mockTrend = vi.fn()

vi.mock('@/lib/api', () => ({
  savingBoardApi: {
    board: (...a: unknown[]) => mockBoard(...a),
    trend: (...a: unknown[]) => mockTrend(...a),
  },
}))

import SavingBoardPage from '@/app/(dashboard)/production/saving-board/page'

beforeEach(() => {
  vi.clearAllMocks()
  mockBoard.mockResolvedValue({ data: { data: { cohorts: [], batchGroups: [] } } })
  mockTrend.mockResolvedValue({ data: { data: { points: [], timezone: 'Asia/Shanghai' } } })
})

/** 渲染整页并把「商家看得见的字」取出来（等首屏数据回来，避免断言跑在加载态上） */
async function renderPageText(): Promise<string> {
  const { container } = render(<SavingBoardPage />)
  await waitFor(() => expect(mockBoard).toHaveBeenCalled())
  await waitFor(() => expect(container.textContent ?? '').toContain('省料看板'))
  return container.textContent ?? ''
}

describe('省料看板商家可见文案（issue #5565）', () => {
  it('🔴 渲染文本里不出现内部分层代号（L1/L2/L3 一律不得上屏）', async () => {
    const text = await renderPageText()

    // 严格口径：整页**一个都不要有** —— 代号在页面上没有任何解释，出现即等于内部编号外泄
    expect(text).not.toMatch(/L[123]/)
  })

  it('副标题说人话：看两件事 —— 每批布用剩多少 + 每平方米成品用掉多少米布', async () => {
    const text = await renderPageText()

    expect(text).toContain('每批布用剩多少')
    expect(text).toContain('每平方米成品用掉多少米布')
  })

  it('两个区块标题名仍然点明「这个数是什么」（去掉代号 ≠ 去掉信息）', async () => {
    const text = await renderPageText()

    expect(text).toContain('批次余量分档')
    expect(text).toContain('单位产出的面料消耗')
    // 「按什么分组 / 什么粒度」这类口径信息不许顺手删掉（删了商家就不知道这张表在数什么）
    expect(text).toContain('物料')
    expect(text).toContain('ISO 周')
  })
})