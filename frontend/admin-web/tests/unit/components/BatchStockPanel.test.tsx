// @vitest-environment jsdom
// case_ids: PR-057
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'

/**
 * 批次账读面（V116 / issue #5145 阶段 1，PR-054）：
 * ① 批次余量（**派生** = 入库量 − 已派工消耗）；② 剩余量分布（恒四档）；③ 对账（SKU 库存 vs 批次余量）。
 *
 * 口径纪律（后端 `BatchStockViews` 的 javadoc 是单一真值）：
 *   diff = batchRemaining − skuStock；explainedDiff = 已售扣减 − 已派工 − 其它台账；
 *   `unbatchedMeters` = 台账外存量（本功能上线前的库存）—— **差额不是异常**，故文案必须解释它。
 */

const mockBatches = vi.fn()
const mockDistribution = vi.fn()
const mockReconcile = vi.fn()

vi.mock('@/lib/api', () => ({
  batchStockApi: {
    batches: (...a: unknown[]) => mockBatches(...a),
    distribution: (...a: unknown[]) => mockDistribution(...a),
    reconcile: (...a: unknown[]) => mockReconcile(...a),
  },
}))

import BatchStockPanel from '@/components/products/BatchStockPanel'

const batches = [
  {
    batchId: 1,
    batchNo: 'PC-20260901-0001',
    productId: 'prod-1',
    skuId: 11,
    skuCode: 'SKU-11',
    inboundNo: 'RK-20260901-0001',
    dyeLot: 'G1',
    receivedDate: '2026-09-01',
    unitCost: '12',
    inboundMeters: '20',
    consumedMeters: '7.3',
    remainingMeters: '12.7',
  },
]

// 恒四档：空档也回 0
const distribution = {
  totalBatches: 5,
  buckets: [
    { key: 'le_0_2', label: '≤0.2 米', batchCount: 2, share: '40' },
    { key: 'b0_2_0_5', label: '0.2~0.5 米', batchCount: 0, share: '0' },
    { key: 'b0_5_1', label: '0.5~1 米', batchCount: 1, share: '20' },
    { key: 'gt_1', label: '>1 米', batchCount: 2, share: '40' },
  ],
}

const reconcile = (over: Record<string, unknown> = {}) => ({
  rows: [
    {
      skuId: 11,
      skuCode: 'SKU-11',
      productId: 'prod-1',
      skuStock: '10',
      batchRemaining: '12.7',
      inboundMeters: '20',
      dispatchedMeters: '7.3',
      soldDeductedMeters: '9.3',
      otherLedgerDeltaMeters: '0.5',
      unbatchedMeters: '0.2',
      diff: '2.7',
      explainedDiff: '1.5',
      reconciled: true,
      ...over,
    },
  ],
  totalDiff: '2.7',
  unreconciledCount: 0,
})

describe('BatchStockPanel 批次账读面', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockBatches.mockResolvedValue({ data: { data: batches } })
    mockDistribution.mockResolvedValue({ data: { data: distribution } })
    mockReconcile.mockResolvedValue({ data: { data: reconcile() } })
  })

  it('PR-054 余量列表（红证）：批次号/货号/入库量/已消耗/**余量**/收货日期 + 说明「派生（入库量 − 已派工消耗）」', async () => {
    render(<BatchStockPanel productId="prod-1" />)

    const table = await screen.findByTestId('batch-remaining-table')
    // 余量列表要显示**已用完**的批次（onlyAvailable=false），不是只显示可用的那部分
    expect(mockBatches).toHaveBeenCalledWith({ productId: 'prod-1', skuId: undefined, onlyAvailable: false })
    expect(within(table).getByText('PC-20260901-0001')).toBeInTheDocument()
    expect(within(table).getByText('SKU-11')).toBeInTheDocument()
    expect(within(table).getByText('20')).toBeInTheDocument() // 入库量
    expect(within(table).getByText('7.3')).toBeInTheDocument() // 已消耗
    expect(within(table).getByText('12.7')).toBeInTheDocument() // 余量（派生）
    expect(within(table).getByText('2026-09-01')).toBeInTheDocument()
    // 文案：说清这是**派生**余量，不是另一份库存数
    expect(screen.getByText(/派生余量（入库量 − 已派工消耗）/)).toBeInTheDocument()
  })

  it('PR-054 四档分布（红证）：恒四档都渲染（0 档也在）+ 批次数 + 占比', async () => {
    render(<BatchStockPanel productId="prod-1" />)

    const box = await screen.findByTestId('batch-distribution')
    for (const label of ['≤0.2 米', '0.2~0.5 米', '0.5~1 米', '>1 米']) {
      expect(within(box).getByText(label)).toBeInTheDocument()
    }
    // 0 档必须以 0 渲染（缺档 = 数据缺失还是 0，不能靠猜）
    expect(within(box).getByText('0.2~0.5 米').parentElement?.textContent).toContain('0')
    expect(within(box).getByText('≤0.2 米').parentElement?.textContent).toContain('40%')
    expect(screen.getByTestId('distribution-total')).toHaveTextContent('5')
  })

  it('PR-054 对账（红证）：差额与各腿都可读，且文案说清「差额 = 已售未派 + 台账外存量」，不把差额说成异常', async () => {
    render(<BatchStockPanel productId="prod-1" />)

    const table = await screen.findByTestId('reconcile-table')
    const row = within(table).getByText('SKU-11').closest('tr') as HTMLElement
    expect(within(row).getByText('10')).toBeInTheDocument() // skuStock
    expect(within(row).getByText('12.7')).toBeInTheDocument() // batchRemaining
    expect(within(row).getByText('2.7')).toBeInTheDocument() // diff
    expect(within(row).getByText('0.2')).toBeInTheDocument() // 台账外存量
    expect(within(row).getByText('0.5')).toBeInTheDocument() // 其它台账净额
    // 口径解释：已售未派 + 台账外存量，且**不是异常**
    const legend = screen.getByTestId('reconcile-legend')
    expect(legend).toHaveTextContent('已售未派')
    expect(legend).toHaveTextContent('台账外存量')
    expect(legend).toHaveTextContent('不是异常')
    // 恒等式成立 ⇒ 不出现「需排查」
    expect(screen.queryByTestId('reconcile-unbalanced')).toBeNull()
  })

  it('PR-054 对账：reconciled=false ⇒ 显眼告警（unreconciledCount 报数）', async () => {
    mockReconcile.mockResolvedValue({
      data: { data: { ...reconcile({ reconciled: false }), unreconciledCount: 1 } },
    })
    render(<BatchStockPanel productId="prod-1" />)

    const warn = await screen.findByTestId('reconcile-unbalanced')
    expect(warn).toHaveTextContent('1')
    expect(warn).toHaveTextContent('需排查')
  })
})
