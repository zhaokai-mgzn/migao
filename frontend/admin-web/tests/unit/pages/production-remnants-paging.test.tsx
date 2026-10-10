// case_ids: PP-010, UI-046, CU-010
// 实例判据：「屏上写了 total ⇒ 该集合必须可达」（issue #6697）。
/**
 * `/production/remnants`（余料台账）**分页可达性**判据（issue #6697）。
 *
 * ## 修前实测（issue 正文 + 本包复算）
 *
 * 页面只发**一次** `GET /api/admin/production/remnants?page=1&size=100`，而屏上仍逐字渲染
 * 服务端给的 `page.total`（租户 25 实测 `total = 332`）⇒ **232 条（70%）没有任何可达路径**，
 * 且「共 332 块」那句话让商家以为能数到全部 —— **界面承诺与可达集合不一致**。
 *
 * ## 判据（两条，各自能单独变红）
 *
 * ① mock `remnantApi.ledger` 回 `total = 250 / size = 100` ⇒ **屏上必须出现分页控件**
 *    （`data-testid="remnant-pagination"` + 可点的「2」页 + 「每页条数」），
 *    且屏上「共 250 块」与控件里的「共 250 条」是**同一个 total**（不是两个口径）。
 *    修前红证：源码逐字 `{ status: status || undefined, page: 1, size: 100 }` 且**零** Pagination 引入
 *    ⇒ `queryByTestId('remnant-pagination')` 为 `null` ⇒ 本条红。
 * ② **翻页真发请求**：点第 2 页 ⇒ 请求参数里 `page` 从 1 变成 **2**（断言**最后一次**调用的实参），
 *    且渲染的行换成第 2 页的（`行-101` 出现、`行-1` 消失）。
 *    修前红证：`load` 的依赖只有 `[status]`、页码硬编码 1 ⇒ 点任何东西都不会发第二次请求
 *    （`mockLedger` 仍只被调 1 次）⇒ 本条红。
 *
 * ## 边界（照实登记）
 *
 * - 只测**本页**（`/production/remnants`）；类级面在
 *   `tests/unit/lib/displayed-total-reachability-guard.test.ts`（扫描面 = `production/**`，**不是全站**）；
 * - 只 mock `remnantApi` / `orderApi`，**不 mock `@/components/ui` 的 `Pagination`**
 *   —— 判的必须是**真控件**（stub 一个假分页器会把「页面没接」的缺陷测成绿）。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

const mockLedger = vi.fn()
const mockMatch = vi.fn()
const mockRecover = vi.fn()
const mockScrap = vi.fn()
const mockGetOrders = vi.fn()
const mockGetOrder = vi.fn()

vi.mock('@/lib/api', () => ({
  remnantApi: {
    ledger: (...a: unknown[]) => mockLedger(...a),
    match: (...a: unknown[]) => mockMatch(...a),
    recover: (...a: unknown[]) => mockRecover(...a),
    scrap: (...a: unknown[]) => mockScrap(...a),
  },
  orderApi: {
    getOrders: (...a: unknown[]) => mockGetOrders(...a),
    getOrder: (...a: unknown[]) => mockGetOrder(...a),
  },
}))

// 只替 `Modal`（jsdom 里 portal/焦点无关本判据）；**`Pagination` 与 `Button` 用真实现**
// —— 见文件头「边界」：假分页器会把「页面没接控件」测成绿。
vi.mock('@/components/ui', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>()
  return {
    ...actual,
    Modal: ({ open, children }: { open: boolean; children?: React.ReactNode }) =>
      open ? React.createElement('div', { role: 'dialog' }, children) : null,
  }
})

import RemnantLedgerPage from '@/app/(dashboard)/production/remnants/page'

const TOTAL = 250
const SIZE = 100

const SUMMARY = {
  availableCount: 1,
  availableMeters: 3.2,
  usedCount: 0,
  recoveredMetersTotal: 0,
  scrappedCount: 0,
  scrappedMetersTotal: 0,
  customerTakenCount: 0,
  recoveredAmountTotal: 0,
  issuedCostTotal: 500,
  recoveryRate: null,
  scrapRate: null,
}

/** 第 `page` 页的一行（id 用 1 基序号 ⇒ 「行-101」一眼看出是第 2 页） */
function line(page: number, indexInPage: number) {
  const id = (page - 1) * SIZE + indexInPage
  return {
    id,
    lengthM: 1.6,
    widthM: 2,
    areaM2: 3.2,
    pieceKind: 'end',
    sourceOrderNo: `ORD-${id}`,
    sourceBatchNo: 'B-2026-10',
    dyeLot: 'D01',
    status: 'available',
    recoveredAmount: null,
    recoveredMeters: null,
    recoveredUnitCost: null,
    usedByOrderNo: null,
    usedByItemKey: null,
    recoveredBy: null,
    recoveredAt: null,
    scrapReason: null,
    scrappedBy: null,
    scrappedAt: null,
  }
}

/** 服务端按 `page` 回**真分页**（不是每页都回同一批 —— 否则「翻页真换内容」判不出来） */
function ledgerResponse(page: number, size = SIZE) {
  const items = Array.from({ length: size }, (_, i) => line(page, i + 1))
  return { data: { data: { summary: SUMMARY, page: { items, total: TOTAL, page, size } } } }
}

describe('余料台账 /production/remnants 分页可达性（issue #6697）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockLedger.mockImplementation((params: { page?: number; size?: number } = {}) =>
      Promise.resolve(ledgerResponse(params.page ?? 1, params.size ?? SIZE)),
    )
    mockMatch.mockResolvedValue({
      data: {
        data: { configured: true, requiredItems: [], recommendations: [], unmatched: [], unconfiguredItems: [] },
      },
    })
    mockGetOrders.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
    mockGetOrder.mockResolvedValue({ data: { data: null } })
  })

  it('① total=250 / 每页 100 ⇒ 屏上出现分页控件，且「共 250 块」与控件同源', async () => {
    render(<RemnantLedgerPage />)
    // 修前第一条红：请求参数逐字 `page: 1, size: 100`（本包只把它从硬编码搬进 state）
    await waitFor(() => expect(mockLedger).toHaveBeenCalledTimes(1))
    expect(mockLedger).toHaveBeenLastCalledWith({ status: undefined, page: 1, size: 100 })

    // 只渲染第 1 页 100 行（这是**事实**，不是缺陷；缺陷是「剩下 150 条没有入口」）
    expect(screen.getAllByTestId(/^remnant-row-/)).toHaveLength(SIZE)
    expect(screen.getByTestId('remnant-row-1')).toBeInTheDocument()
    expect(screen.queryByTestId('remnant-row-101')).not.toBeInTheDocument()
    // 屏上仍写「共 250 块」（服务端 total，一字不改）
    expect(screen.getByText(/共\s*250\s*块/)).toBeInTheDocument()

    // 🔴 修前第二条红：**零分页控件**（源码里连 Pagination 都没引）
    const pager = screen.getByTestId('remnant-pagination')
    expect(pager).toBeInTheDocument()
    // 控件里的 total 与「共 N 块」同源（250）—— 且说清当前可达区间「第 1-100 条」
    expect(pager).toHaveTextContent(/共\s*250\s*条记录/)
    expect(pager).toHaveTextContent(/第 1-100 条/)
    // 250 / 100 ⇒ 3 页：可点的页码按钮里有「3」，且「每页条数」选择器在
    expect(pager).toHaveTextContent('3')
    expect(screen.getByLabelText('每页条数')).toBeInTheDocument()
  })

  it('② 翻到第 2 页 ⇒ 真发 `page=2` 的请求，且渲染换成第 2 页的行', async () => {
    render(<RemnantLedgerPage />)
    await waitFor(() => expect(mockLedger).toHaveBeenCalledTimes(1))

    // 点分页控件里的「2」（真 `Pagination` 的页码按钮）
    fireEvent.click(screen.getByText('2'))

    // 修前红证：load 的依赖只有 `[status]`、页码硬编码 1 ⇒ 这里永远等不到第二次请求
    await waitFor(() => expect(mockLedger).toHaveBeenCalledTimes(2))
    expect(mockLedger).toHaveBeenLastCalledWith({ status: undefined, page: 2, size: 100 })

    // 内容真的换了页（不是发了个请求但还渲染第 1 页）
    await waitFor(() => expect(screen.getByTestId('remnant-row-101')).toBeInTheDocument())
    expect(screen.queryByTestId('remnant-row-1')).not.toBeInTheDocument()
    // 区间读数随页走
    expect(screen.getByTestId('remnant-pagination')).toHaveTextContent(/第 101-200 条/)
  })

  it('③ 换每页条数 ⇒ 回到第 1 页并真发新 size（不给「停在不存在的页 = 空表」）', async () => {
    render(<RemnantLedgerPage />)
    await waitFor(() => expect(mockLedger).toHaveBeenCalledTimes(1))

    fireEvent.click(screen.getByText('2'))
    await waitFor(() => expect(mockLedger).toHaveBeenCalledTimes(2))

    fireEvent.change(screen.getByLabelText('每页条数'), { target: { value: '20' } })
    await waitFor(() => expect(mockLedger).toHaveBeenCalledTimes(3))
    expect(mockLedger).toHaveBeenLastCalledWith({ status: undefined, page: 1, size: 20 })
    expect(screen.getAllByTestId(/^remnant-row-/)).toHaveLength(20)
  })
})
