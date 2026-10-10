// case_ids: PP-010, CU-010, UI-046. 余料台账匹配入口选择器 + 报废确认弹层（issue #6669 第 2、3 条）
/**
 * `/production/remnants`（余料台账）**首条页面级判据**（issue #6669 第 2、3 条）。
 *
 * 本页此前**整个行为面零测试**（issue 正文：`grep` 全仓 0 命中）⇒ 改坏了没人拦。
 *
 * 两条缺陷（修前实测）：
 * ① **核心入口要商家手输内部 id**（P0）：输入框 `placeholder="订单明细行 id"`，而界面上
 *    **无处能看到/选到**这个 id（`order_items.id` 是 UUID）⇒ 小件优先匹配对商家实际不可用；
 * ② **报废走 `window.prompt`**（P2）：无上下文、无「不可撤销」说明。
 *
 * 判据（各自能单独变红，红证写在每条上）：
 * - 修前形态（手输 id）⇒ 第 1 条红：`getByLabelText('订单明细行 id')` 能取到 / `queryByLabelText('搜索订单或客户')` 为空；
 * - 修前形态（prompt）⇒ 第 3 条红：`window.prompt` 被调用（断言零调用）。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'

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

// 显式列出本页 + `@/components/ui` 各原语用到的图标（**不要用 Proxy**：实测 vitest 收集阶段会挂死）
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: Record<string, unknown>) =>
    React.createElement('span', { 'data-testid': `icon-${name}`, ...props })
  return {
    AlertCircle: stub('alert-circle'),
    RefreshCw: stub('refresh'),
    Search: stub('search'),
    // `@/components/ui` 各原语
    Loader2: stub('loader-2'),
    ChevronDown: stub('chevron-down'),
    ChevronUp: stub('chevron-up'),
    ChevronLeft: stub('chevron-left'),
    ChevronRight: stub('chevron-right'),
    Package: stub('package'),
    FileX: stub('file-x'),
    Inbox: stub('inbox'),
    Upload: stub('upload'),
    File: stub('file'),
    FileText: stub('file-text'),
    Image: stub('image'),
    X: stub('x'),
  }
})

// 真实 Modal / Button（不是 stub）：本包判的就是「弹层真的出现 + 按钮真的禁用」
import RemnantLedgerPage from '@/app/(dashboard)/production/remnants/page'

const LEDGER = {
  summary: {
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
  },
  page: {
    total: 1,
    items: [
      {
        id: 7,
        lengthM: 1.6,
        widthM: 2,
        areaM2: 3.2,
        pieceKind: 'end',
        sourceOrderNo: 'ORD20261010001',
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
      },
    ],
  },
}

const ORDER = {
  id: 'ord-1',
  orderNo: 'ORD20261010001',
  customerName: '张美丽',
  items: [
    { id: 'item-a', productName: '遮光窗帘', color: '米白', specification: '门幅2.8米', quantity: 6 },
    { id: 'item-b', productName: '纱帘', color: '雪白', specification: '门幅2.8米', quantity: 3 },
  ],
}

describe('余料台账 /production/remnants（issue #6669 第 2、3 条）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockLedger.mockResolvedValue({ data: { data: LEDGER } })
    mockScrap.mockResolvedValue({ data: { data: {} } })
    mockMatch.mockResolvedValue({
      data: {
        data: { configured: true, requiredItems: [], recommendations: [], unmatched: [], unconfiguredItems: [] },
      },
    })
    mockGetOrders.mockResolvedValue({ data: { data: { items: [ORDER], total: 1 } } })
    mockGetOrder.mockResolvedValue({ data: { data: ORDER } })
  })

  /**
   * ① 选择器替代手输（P0）。
   * 修前红证：`placeholder="订单明细行 id"` ⇒ `queryByLabelText('搜索订单或客户')` 为空、且
   * `queryByLabelText('订单明细行 id')` 非空 ⇒ 本条红（提示语里那个词不再出现）。
   * 🔴 另一条硬要求：**明细 id 不上屏**（`item-a` / UUID 都不许出现）。
   */
  it('匹配入口按订单/客户搜索 → 列出明细行（不再要求手输内部 id，且 id 不上屏）', async () => {
    render(<RemnantLedgerPage />)
    await waitFor(() => expect(mockLedger).toHaveBeenCalled())

    // 出口：有搜索框，没有「手输 id」框
    expect(screen.getByLabelText('搜索订单或客户')).toBeInTheDocument()
    expect(screen.queryByLabelText('订单明细行 id')).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText('订单明细行 id')).not.toBeInTheDocument()
    // 说明文字也不得再教商家「填 id」
    expect(screen.queryByText(/填订单明细行 id/)).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('搜索订单或客户'), { target: { value: '20261010001' } })
    fireEvent.click(screen.getByTestId('remnant-line-search'))

    await waitFor(() => expect(screen.getByTestId('remnant-line-candidates')).toBeInTheDocument())
    expect(mockGetOrders).toHaveBeenCalledWith(expect.objectContaining({ keyword: '20261010001' }))

    // 候选里点一行 ⇒ 选中态上屏「订单号 + 商品 + 数量」，明细 id **不上屏**
    fireEvent.click(screen.getAllByTestId('remnant-line-option')[1])
    const selected = screen.getByTestId('remnant-line-selected')
    expect(selected).toHaveTextContent('ORD20261010001')
    expect(selected).toHaveTextContent('纱帘')
    expect(selected).toHaveTextContent('3 米')
    expect(selected).not.toHaveTextContent('item-b')

    // 选中后才允许查匹配，且请求里带的是**选中行的 id**（内部传递，不上屏）
    fireEvent.click(screen.getByTestId('remnant-match-run'))
    await waitFor(() => expect(mockMatch).toHaveBeenCalled())
    expect(mockMatch).toHaveBeenCalledWith({ orderItemId: 'item-b', batchNo: undefined })
  })

  it('未选行时「查匹配」禁用（不给商家一个必然报错的按钮）', async () => {
    render(<RemnantLedgerPage />)
    await waitFor(() => expect(mockLedger).toHaveBeenCalled())
    expect(screen.getByTestId('remnant-match-run')).toBeDisabled()
    fireEvent.click(screen.getByTestId('remnant-match-run'))
    expect(mockMatch).not.toHaveBeenCalled()
  })

  /**
   * ③ 报废走自研 Modal（P2）。
   * 修前红证：`window.prompt` 被调用 ⇒ 本条的「零调用」当场红（且 `mockScrap` 收不到 reason）。
   */
  it('报废走自研 Modal：带上下文 + 不可撤销说明；window.prompt 零调用；确认后才落库', async () => {
    const promptSpy = vi.spyOn(window, 'prompt')
    render(<RemnantLedgerPage />)
    await waitFor(() => expect(screen.getByTestId('remnant-row-7')).toBeInTheDocument())

    fireEvent.click(screen.getByTestId('remnant-scrap-btn-7'))

    // 弹层真的出现（不是 prompt）：带上下文（这是哪一块）+ 不可撤销说明
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/ORD20261010001/)).toBeInTheDocument()
    expect(within(dialog).getByText(/无法撤销/)).toBeInTheDocument()
    // 原因必填：没填时确认按钮禁用 ⇒ 不发请求
    expect(screen.getByTestId('remnant-scrap-confirm')).toBeDisabled()
    fireEvent.click(screen.getByTestId('remnant-scrap-confirm'))
    expect(mockScrap).not.toHaveBeenCalled()

    fireEvent.change(screen.getByLabelText('报废原因'), { target: { value: '受潮发霉' } })
    expect(screen.getByTestId('remnant-scrap-confirm')).not.toBeDisabled()
    fireEvent.click(screen.getByTestId('remnant-scrap-confirm'))

    await waitFor(() => expect(mockScrap).toHaveBeenCalledWith(7, '受潮发霉'))
    expect(promptSpy).not.toHaveBeenCalled() // 🔴 原生 prompt 零调用
    promptSpy.mockRestore()
  })
})
