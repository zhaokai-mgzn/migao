// @vitest-environment jsdom
// case_ids: UI-076, PR-118
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

/**
 * 按批次库存盘点录入（V143 / issue #5865，**最小录入式**）。
 *
 * 判据（逐条可红）：
 * ① **差异预览**：差异 = 实盘 − 余量（正 = 盘盈、负 = 盘亏），逐行显示 + **合计**；
 * ② **不静默取整**：`2.755` / `-1` ⇒ 行内说明 + **拦住提交**（不发生任何请求）；
 * ③ **零差异零请求**：实盘 == 余量 ⇒ 按钮禁用（后端另有「零写入」判据，前端不许先发一笔空请求）；
 * ④ **提交载荷**：`{productId, runId, lines:[{batchId, actualMeters}]}` —— 只带真的变了差异的行；
 * ⑤ **幂等键语义**：提交成功 ⇒ 换新 runId（下一笔 = 新的一次盘点）；**提交失败 ⇒ 复用同一个 runId**
 *    （网络重试不双记 —— 这是 runId 存在的全部理由）；
 * ⑥ **结果可见**（`migao-dev-flow` §15.1）：提交成功后宿主列表刷新为**新余量**，
 *    不是「提交成功但列表还是旧值」。
 */

const mockBatches = vi.fn()
const mockDistribution = vi.fn()
const mockReconcile = vi.fn()
const mockStocktake = vi.fn()

vi.mock('@/lib/api', () => ({
  batchStockApi: {
    batches: (...a: unknown[]) => mockBatches(...a),
    distribution: (...a: unknown[]) => mockDistribution(...a),
    reconcile: (...a: unknown[]) => mockReconcile(...a),
    stocktake: (...a: unknown[]) => mockStocktake(...a),
  },
}))

import BatchStockPanel from '@/components/products/BatchStockPanel'
import BatchStocktakeForm from '@/components/products/BatchStocktakeForm'

const batch = (over: Record<string, unknown> = {}) => ({
  batchId: 7,
  batchNo: 'PC-20260901-0001',
  productId: 'prod-1',
  skuId: 11,
  skuCode: 'SKU-11',
  inboundNo: 'RK-20260901-0001',
  dyeLot: 'G1',
  receivedDate: '2026-09-01',
  unitCost: '12',
  inboundMeters: '60',
  consumedMeters: '0',
  remainingMeters: '60',
  ...over,
})

const emptyDistribution = { totalBatches: 0, buckets: [] }
const emptyReconcile = {
  rows: [],
  totalDiff: '0',
  unreconciledCount: 0,
  totalFormulaMeters: '0',
  totalPlannedMeters: '0',
  totalSavedMeters: '0',
}

beforeEach(() => {
  vi.clearAllMocks()
  mockBatches.mockResolvedValue({ data: { data: [batch()] } })
  mockDistribution.mockResolvedValue({ data: { data: emptyDistribution } })
  mockReconcile.mockResolvedValue({ data: { data: emptyReconcile } })
  mockStocktake.mockResolvedValue({
    data: {
      data: {
        runId: 'PD-x',
        productId: 'prod-1',
        changedCount: 1,
        unchangedCount: 0,
        replayedCount: 0,
        totalDelta: '-1.5',
        lines: [],
      },
    },
  })
})

describe('按批次盘点录入（UI-076 / PR-118）', () => {
  it('UI-076 差异预览：实盘 58.5 vs 余量 60 ⇒ 逐行 -1.5 + 合计 -1.5；盘盈显示 +', () => {
    render(<BatchStocktakeForm productId="prod-1" batches={[batch() as never]} />)

    fireEvent.change(screen.getByTestId('stocktake-input-7'), { target: { value: '58.5' } })
    expect(screen.getByTestId('stocktake-diff-7')).toHaveTextContent('-1.5')
    expect(screen.getByTestId('stocktake-total')).toHaveTextContent('-1.5')

    fireEvent.change(screen.getByTestId('stocktake-input-7'), { target: { value: '62' } })
    expect(screen.getByTestId('stocktake-diff-7')).toHaveTextContent('+2')
    expect(screen.getByTestId('stocktake-total')).toHaveTextContent('+2')
  })

  it('UI-076 不静默取整：2.755 / -1 ⇒ 行内说明 + 按钮禁用 + 零请求', () => {
    render(<BatchStocktakeForm productId="prod-1" batches={[batch() as never]} />)

    fireEvent.change(screen.getByTestId('stocktake-input-7'), { target: { value: '2.755' } })
    expect(screen.getByTestId('stocktake-input-error-7')).toHaveTextContent('1 位小数')
    expect(screen.getByTestId('stocktake-submit')).toBeDisabled()

    // `type=number` 的输入框在 jsdom 下对非法串可能回落成空串 ⇒ 这里显式核 -1（负数）
    fireEvent.change(screen.getByTestId('stocktake-input-7'), { target: { value: '-1' } })
    const submit = screen.getByTestId('stocktake-submit')
    expect(screen.queryByTestId('stocktake-input-error-7') !== null || submit.hasAttribute('disabled')).toBe(true)
    expect(submit).toBeDisabled()

    fireEvent.click(submit)
    expect(mockStocktake).not.toHaveBeenCalled()
  })

  it('UI-076 零差异零请求：实盘 == 余量 ⇒ 按钮禁用（后端另有零写入判据）', () => {
    render(<BatchStocktakeForm productId="prod-1" batches={[batch() as never]} />)

    fireEvent.change(screen.getByTestId('stocktake-input-7'), { target: { value: '60' } })
    expect(screen.getByTestId('stocktake-diff-7')).toHaveTextContent('0')
    expect(screen.getByTestId('stocktake-total')).toHaveTextContent('0')
    expect(screen.getByTestId('stocktake-submit')).toBeDisabled()
    fireEvent.click(screen.getByTestId('stocktake-submit'))
    expect(mockStocktake).not.toHaveBeenCalled()
  })

  it('UI-076 提交载荷：只带真的变了差异的行 + runId 幂等键 + 成功提示', async () => {
    const onApplied = vi.fn()
    render(
      <BatchStocktakeForm productId="prod-1" batches={[batch() as never]} onApplied={onApplied} />,
    )

    fireEvent.change(screen.getByTestId('stocktake-input-7'), { target: { value: '58.5' } })
    fireEvent.click(screen.getByTestId('stocktake-submit'))
    await waitFor(() => expect(mockStocktake).toHaveBeenCalledTimes(1))

    const first = mockStocktake.mock.calls[0][0] as {
      productId: string; runId: string; lines: { batchId: number; actualMeters: number }[]
    }
    expect(first.productId).toBe('prod-1')
    expect(first.runId).toMatch(/^PD-/)
    expect(first.lines).toEqual([{ batchId: 7, actualMeters: 58.5 }])
    await waitFor(() => expect(onApplied).toHaveBeenCalledTimes(1))
    expect(screen.getByTestId('stocktake-result')).toHaveTextContent('1 个批次已落账')
  })

  it('UI-076 幂等键语义：成功 ⇒ 下一笔换新 runId；失败 ⇒ 重试复用同一个 runId', async () => {
    render(<BatchStocktakeForm productId="prod-1" batches={[batch() as never]} />)

    fireEvent.change(screen.getByTestId('stocktake-input-7'), { target: { value: '58.5' } })
    fireEvent.click(screen.getByTestId('stocktake-submit'))
    await waitFor(() => expect(mockStocktake).toHaveBeenCalledTimes(1))
    const firstRunId = (mockStocktake.mock.calls[0][0] as { runId: string }).runId

    // 成功后再盘一笔（金额不同）⇒ 必须是**新的** run id
    fireEvent.change(screen.getByTestId('stocktake-input-7'), { target: { value: '57' } })
    fireEvent.click(screen.getByTestId('stocktake-submit'))
    await waitFor(() => expect(mockStocktake).toHaveBeenCalledTimes(2))
    const secondRunId = (mockStocktake.mock.calls[1][0] as { runId: string }).runId
    expect(secondRunId).not.toBe(firstRunId)

    // 这一笔失败（后端 4xx 原文照实显示）⇒ 重试**复用**同一个 run id（重试不得双记）
    mockStocktake.mockRejectedValueOnce({ response: { data: { message: '实盘米数 最多支持 1 位小数' } } })
    fireEvent.change(screen.getByTestId('stocktake-input-7'), { target: { value: '56' } })
    fireEvent.click(screen.getByTestId('stocktake-submit'))
    await waitFor(() => expect(mockStocktake).toHaveBeenCalledTimes(3))
    const thirdRunId = (mockStocktake.mock.calls[2][0] as { runId: string }).runId
    expect(thirdRunId).not.toBe(secondRunId)
    // 失败首页：后端 4xx 原文照实显示（不吞、不换措辞）
    await waitFor(() =>
      expect(screen.getByTestId('stocktake-error')).toHaveTextContent('最多支持 1 位小数'),
    )
    // 重试 ⇒ **复用**同一个 run id（重试不得双记）
    fireEvent.click(screen.getByTestId('stocktake-submit'))
    await waitFor(() => expect(mockStocktake).toHaveBeenCalledTimes(4))
    expect((mockStocktake.mock.calls[3][0] as { runId: string }).runId).toBe(thirdRunId)
  })

  it('UI-076 结果可见：面板提交成功后列表刷新为**新余量**（不是「提交成功但列表还是旧值」）', async () => {
    mockBatches
      .mockResolvedValueOnce({ data: { data: [batch()] } })
      .mockResolvedValue({ data: { data: [batch({ remainingMeters: '58.5', consumedMeters: '1.5' })] } })

    render(<BatchStockPanel productId="prod-1" />)
    await screen.findByTestId('batch-remaining-table')
    expect(screen.getByTestId('batch-remaining-table')).toHaveTextContent('60')

    fireEvent.change(await screen.findByTestId('stocktake-input-7'), { target: { value: '58.5' } })
    fireEvent.click(screen.getByTestId('stocktake-submit'))

    await waitFor(() => expect(mockStocktake).toHaveBeenCalledTimes(1))
    // 列表重新取数 ⇒ 新余量出现在页面上（派生余量跟着盘点的分录一起变）
    await waitFor(() => expect(mockBatches).toHaveBeenCalledTimes(2))
    await waitFor(() =>
      expect(screen.getByTestId('batch-remaining-table')).toHaveTextContent('58.5'),
    )
  })
})
