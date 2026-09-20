// case_ids: PG-021
// PG-021（issue #4205，前端半边）：计件工资报表页 /production/piecework ——
// 消费 GET /api/admin/production/piecework/summary?period=YYYY-MM[&worker_name=]，
// 按期间（月份选择）+ 按工人 / 按工序两档展示；默认期间 = 当前月（不空查）。
// 反 placeholder：断言必须落到**真实金额/数量**，不能只断言页面存在。
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const mockGetPieceworkSummary = vi.fn()

vi.mock('@/lib/api', () => ({
  productionApi: {
    getPieceworkSummary: (...args: unknown[]) => mockGetPieceworkSummary(...args),
  },
}))

import PieceworkReportPage from '@/app/(dashboard)/production/piecework/page'

const REPORT = {
  period: '2026-09',
  total: 123.45,
  per_worker: [
    { worker_name: '张三', amount: 80, qty: 200 },
    { worker_name: '李红梅', amount: 43.45, qty: 111 },
  ],
  per_operation: [
    // issue #4621：后端补的显示名派生键（`operation` = 工人端快照名 = 变体名，界面不得渲染）
    { operation: '韩褶-布', logical_name: '韩褶', position: '布帘', amount: 40, qty: 100 },
    { operation: '定型-布', logical_name: '定型', position: '布帘', amount: 83.45, qty: 211 },
  ],
  // 下钻两维（issue #4347 §3.2）：后端**同一份聚合**产出 ⇒ 各维合计 = total = 123.45
  per_position: [
    { position_name: '布艺遮光帘A 米白', amount: 83.45, qty: 211 },
    { position_name: '纱帘B 本白', amount: 40, qty: 100 },
  ],
  per_set: [
    { order_item_id: 'item-A', amount: 83.45, qty: 211 },
    { order_item_id: 'item-B', amount: 40, qty: 100 },
  ],
}

const ok = (data: unknown) => ({ data: { success: true, data } })

describe('计件工资报表页 /production/piecework', () => {
  beforeEach(() => {
    mockGetPieceworkSummary.mockReset().mockResolvedValue(ok(REPORT))
  })

  it('默认期间 = 当前月（YYYY-MM），首屏即查（不空查）', async () => {
    const expected = new Date().toISOString().slice(0, 7)
    render(<PieceworkReportPage />)

    await waitFor(() => expect(mockGetPieceworkSummary).toHaveBeenCalled())
    expect(mockGetPieceworkSummary).toHaveBeenCalledWith({ period: expected, worker_name: undefined })
    expect(screen.getByTestId('piecework-period')).toHaveValue(expected)
  })

  it('渲染真实报表：合计 + 按工人档（姓名/金额/数量）', async () => {
    render(<PieceworkReportPage />)

    await waitFor(() => expect(screen.getByTestId('piecework-report-total')).toHaveTextContent('¥123.45'))
    const workers = screen.getByTestId('piecework-by-worker')
    expect(within(workers).getByText('张三')).toBeInTheDocument()
    expect(within(workers).getByTestId('worker-row-张三')).toHaveTextContent('¥80.00')
    expect(within(workers).getByTestId('worker-row-张三')).toHaveTextContent('200')
    expect(within(workers).getByTestId('worker-row-李红梅')).toHaveTextContent('¥43.45')
  })

  it('切「按工序」档：展示工序聚合（工序名/金额/数量）', async () => {
    render(<PieceworkReportPage />)
    await waitFor(() => expect(screen.getByTestId('piecework-by-worker')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('piecework-tab-operation'))

    const operations = screen.getByTestId('piecework-by-operation')
    // issue #4621：只显示「逻辑名 · 部位」——变体名（`韩褶-布`）不进界面，也不进 testid
    expect(within(operations).getByTestId('operation-row-韩褶 · 布帘')).toHaveTextContent('¥40.00')
    expect(within(operations).getByTestId('operation-row-定型 · 布帘')).toHaveTextContent('¥83.45')
    expect(within(operations).queryByTestId('operation-row-韩褶-布')).toBeNull()
    expect(within(operations).queryByText('韩褶-布')).toBeNull()
    expect(screen.queryByTestId('piecework-by-worker')).not.toBeInTheDocument()
  })

  it('老数据缺 logical_name ⇒ 退回 operation 原文（不显示空白）', async () => {
    mockGetPieceworkSummary.mockResolvedValue(
      ok({
        ...REPORT,
        per_operation: [{ operation: '定型-布', amount: 83.45, qty: 211 }],
      }),
    )
    render(<PieceworkReportPage />)
    await waitFor(() => expect(screen.getByTestId('piecework-by-worker')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('piecework-tab-operation'))

    const operations = screen.getByTestId('piecework-by-operation')
    expect(within(operations).getByTestId('operation-row-定型-布')).toHaveTextContent('¥83.45')
  })

  it('切「按工人」档可回到工人视图', async () => {
    render(<PieceworkReportPage />)
    await waitFor(() => expect(screen.getByTestId('piecework-by-worker')).toBeInTheDocument())

    await userEvent.click(screen.getByTestId('piecework-tab-operation'))
    await userEvent.click(screen.getByTestId('piecework-tab-worker'))

    expect(screen.getByTestId('piecework-by-worker')).toBeInTheDocument()
  })

  it('换月份：按新期间重查', async () => {
    render(<PieceworkReportPage />)
    await waitFor(() => expect(mockGetPieceworkSummary).toHaveBeenCalledTimes(1))

    const periodInput = screen.getByTestId('piecework-period')
    await userEvent.clear(periodInput)
    await userEvent.type(periodInput, '2026-08')

    await waitFor(() => expect(mockGetPieceworkSummary).toHaveBeenCalledWith({ period: '2026-08', worker_name: undefined }))
  })

  it('按工人筛选：worker_name 传入请求', async () => {
    render(<PieceworkReportPage />)
    await waitFor(() => expect(screen.getByTestId('piecework-by-worker')).toBeInTheDocument())

    await userEvent.type(screen.getByTestId('piecework-worker-input'), '张三')
    await userEvent.click(screen.getByTestId('piecework-search'))

    await waitFor(() =>
      expect(mockGetPieceworkSummary).toHaveBeenLastCalledWith({ period: expect.any(String), worker_name: '张三' }),
    )
  })

  it('期间无报工：空态提示（不显示 ¥0.00 假数据）', async () => {
    mockGetPieceworkSummary.mockResolvedValue(ok({ period: '2026-08', total: 0, per_worker: [], per_operation: [] }))
    render(<PieceworkReportPage />)

    await waitFor(() => expect(screen.getByTestId('piecework-empty')).toBeInTheDocument())
    expect(screen.queryByTestId('piecework-by-worker')).not.toBeInTheDocument()
  })

  it('接口失败：错误提示 + 重试按钮', async () => {
    mockGetPieceworkSummary.mockRejectedValueOnce(new Error('boom'))
    render(<PieceworkReportPage />)

    await waitFor(() => expect(screen.getByTestId('piecework-error')).toBeInTheDocument())
    expect(screen.getByTestId('piecework-retry')).toBeInTheDocument()
  })
  it('按部位下钻：渲染部位行 + 金额/数量（真值源 §4 下钻链）', async () => {
    render(<PieceworkReportPage />)
    await waitFor(() => expect(mockGetPieceworkSummary).toHaveBeenCalled())

    await userEvent.click(screen.getByTestId('piecework-tab-position'))

    const panel = screen.getByTestId('piecework-by-position')
    expect(within(panel).getByText('布艺遮光帘A 米白')).toBeInTheDocument()
    expect(within(panel).getByText('¥83.45')).toBeInTheDocument()
    expect(within(panel).getByText('纱帘B 本白')).toBeInTheDocument()
    expect(within(panel).getByText('¥40.00')).toBeInTheDocument()
  })

  it('按套下钻：渲染订单行（order_item_id）行 + 金额/数量', async () => {
    render(<PieceworkReportPage />)
    await waitFor(() => expect(mockGetPieceworkSummary).toHaveBeenCalled())

    await userEvent.click(screen.getByTestId('piecework-tab-set'))

    const panel = screen.getByTestId('piecework-by-set')
    expect(within(panel).getByText('item-A')).toBeInTheDocument()
    expect(within(panel).getByText('item-B')).toBeInTheDocument()
  })

  it('下钻红证：缺 per_position / per_set ⇒ 该档显式「无数据」，不崩不静默', async () => {
    // 老后端（未带下钻维度）：人/工序两档**有数据**（否则整页走空态、根本没有 tab），
    // 但 per_position / per_set 缺席 ⇒ 下钻两档应为空态而不是抛错。
    mockGetPieceworkSummary.mockResolvedValue(
      ok({
        period: '2026-09',
        total: 80,
        per_worker: [{ worker_name: '张三', amount: 80, qty: 200 }],
        per_operation: [{ operation: '韩褶-布', amount: 80, qty: 200 }],
      }),
    )
    render(<PieceworkReportPage />)
    await waitFor(() => expect(mockGetPieceworkSummary).toHaveBeenCalled())

    await userEvent.click(screen.getByTestId('piecework-tab-position'))
    expect(within(screen.getByTestId('piecework-by-position')).getByText('无数据')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('piecework-tab-set'))
    expect(within(screen.getByTestId('piecework-by-set')).getByText('无数据')).toBeInTheDocument()
  })

})

/**
 * 未定价显式可见（issue #4696，P1）—— **计件报表页**的红证。
 *
 * 缺陷原形：只有未定价报工的期间里 `total`/`per_worker`/`per_operation` 全空 ⇒
 * 页面渲染「该期间暂无计件数据」，把「干了活但没定价、一分钱没有」彻底藏起来。
 */
describe('计件报表页 未定价可见（issue #4696）', () => {
  it('🔴 只有未定价报工 ⇒ **不得**渲染空态，必须显示未定价 + 定价入口', async () => {
    mockGetPieceworkSummary.mockResolvedValue(
      ok({
        period: '2026-09',
        total: 0,
        per_worker: [],
        per_operation: [],
        per_position: [],
        per_set: [],
        unpriced: {
          qty: 5,
          operations: [{ operation: '配料', logical_name: '配料', position: '布料', qty: 5 }],
          hint: '以下工序未定价',
        },
      }),
    )
    render(<PieceworkReportPage />)
    await waitFor(() => expect(mockGetPieceworkSummary).toHaveBeenCalled())

    expect(screen.queryByTestId('piecework-empty')).not.toBeInTheDocument()
    expect(screen.getByTestId('piecework-unpriced')).toBeInTheDocument()
    expect(screen.getByTestId('piecework-unpriced-0')).toHaveTextContent('未定价')
    expect(screen.getByTestId('piecework-unpriced-pricing-link')).toHaveAttribute(
      'href',
      '/production/routings',
    )
  })
})
